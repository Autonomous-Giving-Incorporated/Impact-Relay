"""Minimal HTTP API for host UIs (stdlib only).

  python -m impact_relay.console_server --data-dir .impact-relay/hacker-dojo --port 8787

Hacker-Dojo static pages call these JSON endpoints. Not a production ASGI stack —
for pilot/demo. Host production should still put an authenticating gateway in front.

Auth posture is default-deny:

* Default — every ``/api`` route except ``/api/health`` requires a resolved
  principal. Identity comes from ``Authorization: Bearer <email>``, resolved by
  the pilot fixture OIDC mapper (no signature validation; pilot only).
* ``--trusted-proxy`` — additionally accept ``X-Impact-*`` / ``X-HD-Campaign-Role``
  identity headers. Only enable behind a gateway that authenticates the user and
  strips client-supplied copies of those headers.
* ``--allow-unauthenticated-pilot`` — restore the previous fail-open behaviour
  where anonymous callers act as the default finance approver. Local demos only;
  never for shadow or live cohorts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from impact_relay.auth.rbac import AuthorizationError
from impact_relay.auth.role_map import principal_from_host_headers
from impact_relay.domain.types import NotFoundError
from impact_relay.host.console import open_donor_console, open_finance_console
from impact_relay.policy import tenant_slug
from impact_relay.storage import open_storage
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID, clone_tenant_from_hacker_dojo

DEFAULT_MAX_BODY_BYTES = 1 << 20  # 1 MiB — console payloads are tiny


class AuthenticationRequired(Exception):
    """No usable principal on a route that requires one (HTTP 401)."""


class PayloadTooLarge(Exception):
    """Request body exceeded the configured cap (HTTP 413)."""


# Keys accepted from a seed request body; everything else is ignored.
SEED_KWARGS = frozenset({"expense_batch", "fixture_path"})


@dataclass(frozen=True)
class ServerConfig:
    """Runtime posture for the pilot console server."""

    data_dir: Path
    tenant_id: str = CANONICAL_PILOT_TENANT_ID
    allow_unauthenticated_pilot: bool = False
    trusted_proxy: bool = False
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    allowed_origins: tuple[str, ...] = ()
    identity_provider: Any = None

    def cors_origin_for(self, origin: str | None) -> str | None:
        """Resolve the ``Access-Control-Allow-Origin`` value for a request.

        Exact-match allowlist. Unauthenticated pilot mode with no explicit
        allowlist falls back to ``*`` so local demos keep working.
        """
        if self.allowed_origins:
            if origin and origin in self.allowed_origins:
                return origin
            if "*" in self.allowed_origins:
                return "*"
            return None
        if self.allow_unauthenticated_pilot:
            return "*"
        return None


def resolve_principal_from_request(
    handler: BaseHTTPRequestHandler,
    tenant_id: str,
    *,
    trusted_proxy: bool = False,
    identity_provider: Any = None,
):
    """Resolve a Principal from request identity, or return ``None``.

    Order:
    1. ``X-Impact-Email`` + ``X-HD-Campaign-Role`` / ``X-Impact-Roles`` — only
       honoured when ``trusted_proxy`` is set, because any client can send them.
    2. ``Authorization: Bearer <email>`` — pilot ``FixtureOidcMapper``.
    3. ``None``.
    """
    email_hdr = (handler.headers.get("X-Impact-Email") or "").strip()
    campaign_role = (handler.headers.get("X-HD-Campaign-Role") or "").strip()
    roles_hdr = (handler.headers.get("X-Impact-Roles") or "").strip()
    subject = (handler.headers.get("X-Impact-Subject") or "").strip() or None
    display = (handler.headers.get("X-Impact-Display-Name") or "").strip()

    auth = (handler.headers.get("Authorization") or "").replace("Bearer ", "").strip()

    if trusted_proxy and email_hdr and (campaign_role or roles_hdr):
        impact_roles = [r.strip() for r in roles_hdr.split(",") if r.strip()] if roles_hdr else None
        try:
            return principal_from_host_headers(
                email=email_hdr,
                campaign_role=campaign_role or None,
                subject=subject or f"supabase:{email_hdr}",
                tenant_id=tenant_id,
                display_name=display,
                impact_roles=impact_roles,
            )
        except ValueError as exc:
            # Unmappable role is a misconfiguration, not an anonymous request.
            raise AuthorizationError(str(exc)) from exc

    if auth and identity_provider is not None:
        try:
            return identity_provider.principal_for_token(auth)
        except ValueError:
            return None

    if auth:
        from impact_relay.auth.oidc import hacker_dojo_fixture_oidc

        try:
            return hacker_dojo_fixture_oidc().principal_for_token(auth)
        except ValueError:
            return None
    return None


def _error_body(error: str, message: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"ok": False, "error": error}
    if message:
        body["message"] = message
    return body


# Console helpers return {"ok": False, "error": <slug>} instead of raising.
_RESULT_ERROR_STATUS: dict[str, int] = {
    "principal_required": 401,
    "forbidden": 403,
    "separation_of_duties": 403,
    "approver_must_be_human": 403,
    "not_found": 404,
    "no_workspace": 404,
}


def _status_for_result(result: dict[str, Any], *, default_ok: int = 200) -> int:
    if result.get("ok") is not False:
        return default_ok
    return _RESULT_ERROR_STATUS.get(str(result.get("error") or ""), 400)


def make_handler(
    data_dir: Path,
    tenant_id: str = CANONICAL_PILOT_TENANT_ID,
    *,
    config: ServerConfig | None = None,
    allow_unauthenticated_pilot: bool = False,
    trusted_proxy: bool = False,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    allowed_origins: tuple[str, ...] = (),
):
    cfg = config or ServerConfig(
        data_dir=Path(data_dir),
        tenant_id=tenant_id,
        allow_unauthenticated_pilot=allow_unauthenticated_pilot,
        trusted_proxy=trusted_proxy,
        max_body_bytes=max_body_bytes,
        allowed_origins=tuple(allowed_origins),
    )

    # Determine the base registry directory (parent of tenant data dirs)
    # This is where we store the shared tenant registry or scan for tenant dirs
    REGISTRY_BASE = cfg.data_dir.parent if cfg.data_dir.name != "storage" else cfg.data_dir

    # Admin API handlers (capture cfg and REGISTRY_BASE from closure)
    def await_list_tenants() -> dict[str, Any]:
        """List all registered tenants in the Impact Relay registry."""
        try:
            tenants = []

            # First, check the registry base directory for a shared tenants table
            try:
                store = open_storage(REGISTRY_BASE)
                shared_tenants = store.tenants.list()
                tenants.extend(shared_tenants)
            except Exception:
                pass

            # Also scan for tenant subdirectories (each has its own DB)
            try:
                for entry in REGISTRY_BASE.iterdir():
                    if entry.is_dir() and entry.name.startswith("org_"):
                        try:
                            store = open_storage(entry)
                            tenant = store.tenants.get(entry.name)
                            if tenant and not any(t.tenant_id == tenant.tenant_id for t in tenants):
                                tenants.append(tenant)
                        except Exception:
                            pass
            except Exception:
                pass

            return {
                "ok": True,
                "tenants": [
                    {
                        "tenant_id": t.tenant_id,
                        "display_name": t.display_name,
                        "policy_version": t.policy_version,
                        "policy_slug": t.policy_slug,
                        "status": t.status,
                        "template_source": t.template_source,
                        "created_at": t.created_at,
                        "meta": t.meta
                    }
                    for t in tenants
                ]
            }
        except Exception as e:  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001
            return {"ok": False, "error": "internal_error", "message": str(e)}

    def await_verify_tenant(tenant_id: str) -> dict[str, Any]:
        """Verify tenant isolation and health for a specific tenant."""
        try:
            tenant_dir = (
                cfg.data_dir.parent / tenant_id
                if cfg.data_dir.name != "storage"
                else cfg.data_dir
            )
            if not tenant_dir.exists():
                tenant_dir = cfg.data_dir / tenant_id

            if not tenant_dir.exists():
                return {
                    "ok": True,
                    "tenant_id": tenant_id,
                    "registered": False,
                    "storage_isolated": False,
                    "policy_source": "unknown",
                    "cross_tenant_access": "unknown",
                    "message": "Tenant directory not found"
                }

            store = open_storage(tenant_dir)
            tenant = store.tenants.get(tenant_id)

            if tenant is None:
                return {
                    "ok": True,
                    "tenant_id": tenant_id,
                    "registered": False,
                    "storage_isolated": True,
                    "policy_source": "unknown",
                    "cross_tenant_access": "unknown",
                    "message": "Tenant directory exists but not registered"
                }

            cross_tenant_access = False
            try:
                other_tenants = store.tenants.list()
                cross_tenant_access = len(other_tenants) > 1
            except Exception:
                pass

            return {
                "ok": True,
                "tenant_id": tenant_id,
                "registered": True,
                "display_name": tenant.display_name,
                "policy_version": tenant.policy_version,
                "policy_slug": tenant.policy_slug,
                "status": tenant.status,
                "template_source": tenant.template_source,
                "storage_isolated": not cross_tenant_access,
                "policy_source": tenant.template_source or "unknown",
                "cross_tenant_access": cross_tenant_access,
                "meta": tenant.meta
            }
        except Exception as e:  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001
            return {"ok": False, "error": "internal_error", "message": str(e)}

    class Handler(BaseHTTPRequestHandler):
        config = cfg

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

        # ------------------------------------------------------------------
        # Responses
        # ------------------------------------------------------------------

        def _cors_headers(self) -> None:
            origin = cfg.cors_origin_for((self.headers.get("Origin") or "").strip() or None)
            if origin is None:
                return
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            if origin != "*":
                self.send_header("Vary", "Origin")

        def _json(self, code: int, body: Any) -> None:
            raw = json.dumps(body, indent=2, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        # ------------------------------------------------------------------
        # Identity
        # ------------------------------------------------------------------

        def _principal(self):
            return resolve_principal_from_request(
                self,
                cfg.tenant_id,
                trusted_proxy=cfg.trusted_proxy,
                identity_provider=cfg.identity_provider,
            )

        def _require_principal(self):
            """Principal for a protected route, or ``None`` in pilot mode."""
            principal = self._principal()
            if principal is None and not cfg.allow_unauthenticated_pilot:
                raise AuthenticationRequired(
                    "authentication required: send Authorization: Bearer <email>"
                    + (" or X-Impact-Email with a role header" if cfg.trusted_proxy else "")
                )
            return principal

        def _finance(self):
            principal = self._require_principal()
            return open_finance_console(
                cfg.data_dir,
                tenant_id=cfg.tenant_id,
                principal=principal,
                require_principal_for_approve=not cfg.allow_unauthenticated_pilot,
            )

        def _donor(self, donor_id: str):
            principal = self._require_principal()
            return open_donor_console(
                donor_id,
                cfg.data_dir,
                tenant_id=cfg.tenant_id,
                principal=principal,
            )

        def _read_body(self) -> dict[str, Any]:
            raw_len = (self.headers.get("Content-Length") or "").strip()
            try:
                length = int(raw_len) if raw_len else 0
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0:
                raise ValueError("invalid Content-Length")
            if length > cfg.max_body_bytes:
                raise PayloadTooLarge(f"request body exceeds {cfg.max_body_bytes} bytes")
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("request body must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("request body must be a JSON object")
            return parsed

        # ------------------------------------------------------------------
        # Dispatch
        # ------------------------------------------------------------------

        def _dispatch(self, handler_fn) -> None:
            try:
                code, body = handler_fn()
            except AuthenticationRequired as exc:
                self._json(401, _error_body("authentication_required", str(exc)))
            except AuthorizationError as exc:
                self._json(403, _error_body("forbidden", str(exc)))
            except NotFoundError as exc:
                self._json(404, _error_body("not_found", str(exc)))
            except PayloadTooLarge as exc:
                self._json(413, _error_body("payload_too_large", str(exc)))
            except FileNotFoundError:
                self._json(404, _error_body("no_workspace", "no durable workspace"))
            except ValueError as exc:
                self._json(400, _error_body("bad_request", str(exc)))
            except Exception:  # noqa: BLE001 - last resort; details stay server-side
                traceback.print_exc(file=sys.stderr)
                self._json(500, _error_body("internal_error"))
            else:
                self._json(code, body)

        def do_GET(self) -> None:
            self._dispatch(self._route_get)

        def do_POST(self) -> None:
            self._dispatch(self._route_post)

        def _route_get(self) -> tuple[int, Any]:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)

            if path == "/api/health":
                return 200, {
                    "ok": True,
                    "service": "impact-relay-console",
                    "tenant_id": cfg.tenant_id,
                    "data_dir": str(cfg.data_dir),
                    "auth": {
                        "allow_unauthenticated_pilot": cfg.allow_unauthenticated_pilot,
                        "trusted_proxy": cfg.trusted_proxy,
                        "jwt_validation": cfg.identity_provider is not None,
                    },
                }

            # Admin API endpoints (require master_admin equivalent or trusted proxy)
            if path == "/api/admin/tenants":
                principal = self._principal()
                if principal is None and not cfg.allow_unauthenticated_pilot:
                    raise AuthenticationRequired("admin endpoint requires authentication")
                # Check for admin role (finance_approver or tenant_admin)
                if principal:
                    roles = getattr(principal, "roles", [])
                    if not any(r in roles for r in ["finance_approver", "tenant_admin"]):
                        raise AuthorizationError("admin role required")
                return 200, await_list_tenants()

            if path == "/api/admin/tenants/verify":
                principal = self._principal()
                if principal is None and not cfg.allow_unauthenticated_pilot:
                    raise AuthenticationRequired("admin endpoint requires authentication")
                tenant_id = (qs.get("tenant_id") or [""])[0]
                if not tenant_id:
                    return 400, _error_body("tenant_id_required")
                return 200, await_verify_tenant(tenant_id)

            if path == "/api/finance/metrics":
                return 200, self._finance().metrics()
            if path == "/api/finance/queue":
                filters = (
                    qs.get("filters") or ["waiting,blocked,dead_letter,needs_information,failed"]
                )[0]
                result = self._finance().queue(filters=filters)
                return _status_for_result(result), result
            m = re.fullmatch(r"/api/finance/cases/([^/]+)", path)
            if m:
                result = self._finance().case_detail(m.group(1))
                return _status_for_result(result), result
            m = re.fullmatch(r"/api/donors/([^/]+)/dashboard", path)
            if m:
                cons = self._donor(m.group(1))
                return 200, {"ok": True, "dashboard": cons.dashboard()}
            m = re.fullmatch(r"/api/donors/([^/]+)/timeline", path)
            if m:
                cons = self._donor(m.group(1))
                return 200, {"ok": True, "timeline": cons.timeline()}
            m = re.fullmatch(r"/api/donors/([^/]+)/receipts", path)
            if m:
                cons = self._donor(m.group(1))
                return 200, {"ok": True, "receipts": cons.receipts()}
            m = re.fullmatch(r"/api/donors/([^/]+)/receipts/([^/]+)", path)
            if m:
                cons = self._donor(m.group(1))
                return 200, {"ok": True, "receipt": cons.receipt_detail(m.group(2))}
            return 404, _error_body("not_found") | {"path": path}

        def _route_post(self) -> tuple[int, Any]:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            # Authenticate before reading or parsing any request body.
            if path == "/api/pilot/seed":
                fin = self._finance()
                body = self._read_body()
                result = fin.seed(**{k: v for k, v in body.items() if k in SEED_KWARGS})
                return _status_for_result(result), result
            m = re.fullmatch(r"/api/finance/cases/([^/]+)/approve", path)
            if m:
                fin = self._finance()
                body = self._read_body()
                result = fin.approve(
                    m.group(1),
                    proposer_id=body.get("proposer_id"),
                    approver_id=body.get("approver_id"),
                )
                return _status_for_result(result, default_ok=200), result

            # Admin API: clone tenant from template
            if path == "/api/admin/tenants/clone":
                principal = self._principal()
                if principal is None and not cfg.allow_unauthenticated_pilot:
                    raise AuthenticationRequired("admin endpoint requires authentication")
                # Check for admin role (finance_approver or tenant_admin)
                if principal:
                    roles = getattr(principal, "roles", [])
                    if not any(r in roles for r in ["finance_approver", "tenant_admin"]):
                        raise AuthorizationError("admin role required")
                body = self._read_body()
                tenant_id = (body.get("tenant_id") or "").strip()
                display_name = (body.get("display_name") or "").strip()
                template_source = (body.get("template_source") or "org_hacker_dojo").strip()

                if not tenant_id or not display_name:
                    return 400, _error_body("tenant_id_and_display_name_required")

                if not re.fullmatch(r"org_[a-z0-9_]+", tenant_id):
                    return 400, _error_body("invalid_tenant_id_format")

                try:
                    # Clone tenant policy
                    policy = clone_tenant_from_hacker_dojo(
                        tenant_id=tenant_id,
                        display_name=display_name,
                    )

                    # Register in tenant-specific storage
                    tenant_dir = (
                        cfg.data_dir.parent / tenant_id
                        if cfg.data_dir.name != "storage"
                        else cfg.data_dir
                    )
                    tenant_dir.mkdir(parents=True, exist_ok=True)
                    store = open_storage(tenant_dir)
                    store.tenants.upsert_from_policy(
                        policy,
                        template_source=template_source,
                        meta={
                            "role": "cloned_nonprofit",
                            "policy_slug": tenant_slug(tenant_id),
                            "template": template_source,
                        }
                    )

                    return 200, {
    "ok": True,
    "tenant_id": tenant_id,
    "display_name": display_name,
    "template_source": template_source,
}
                except Exception as e:  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001  # noqa: BLE001
                    return 500, _error_body("clone_failed", str(e))

            return 404, _error_body("not_found")

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Impact Relay console HTTP API (pilot)")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(".impact-relay/hacker-dojo"),
        help="Durable data directory",
    )
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--tenant-id", default=CANONICAL_PILOT_TENANT_ID)
    p.add_argument(
        "--supabase-url",
        default=os.getenv("SUPABASE_URL"),
        help="Supabase project URL. Enables JWKS access-token validation.",
    )
    p.add_argument(
        "--supabase-audience",
        default=os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated"),
        help="Required Supabase JWT audience (default: authenticated).",
    )
    p.add_argument(
        "--trusted-proxy",
        action="store_true",
        help=(
            "Accept X-Impact-* identity headers. Only behind a gateway that "
            "authenticates users and strips client-supplied copies."
        ),
    )
    p.add_argument(
        "--allow-unauthenticated-pilot",
        action="store_true",
        help=(
            "DANGER: allow anonymous callers to read and approve as the default "
            "finance approver. Local demos only — never shadow or live cohorts."
        ),
    )
    p.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="ORIGIN",
        help="Exact CORS origin to allow (repeatable). Default: no CORS headers.",
    )
    p.add_argument(
        "--max-body-bytes",
        type=int,
        default=DEFAULT_MAX_BODY_BYTES,
        help=f"Reject request bodies larger than this (default {DEFAULT_MAX_BODY_BYTES})",
    )
    args = p.parse_args(argv)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    identity_provider = None
    if args.supabase_url:
        from impact_relay.auth.supabase import SupabaseJwksProvider

        identity_provider = SupabaseJwksProvider(
            supabase_url=args.supabase_url,
            tenant_id=args.tenant_id,
            audience=args.supabase_audience,
        )
    cfg = ServerConfig(
        data_dir=args.data_dir,
        tenant_id=args.tenant_id,
        allow_unauthenticated_pilot=args.allow_unauthenticated_pilot,
        trusted_proxy=args.trusted_proxy,
        max_body_bytes=args.max_body_bytes,
        allowed_origins=tuple(args.allow_origin),
        identity_provider=identity_provider,
    )
    handler = make_handler(args.data_dir, args.tenant_id, config=cfg)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    if cfg.allow_unauthenticated_pilot:
        print(
            "WARNING: --allow-unauthenticated-pilot is set; anonymous callers can "
            "approve expenses as the default finance approver.",
            file=sys.stderr,
        )
    print(
        json.dumps(
            {
                "listening": f"http://{args.host}:{args.port}",
                "data_dir": str(args.data_dir.resolve()),
                "tenant_id": args.tenant_id,
                "health": f"http://{args.host}:{args.port}/api/health",
                "auth": {
                    "allow_unauthenticated_pilot": cfg.allow_unauthenticated_pilot,
                    "trusted_proxy": cfg.trusted_proxy,
                    "jwt_validation": cfg.identity_provider is not None,
                    "allowed_origins": list(cfg.allowed_origins),
                },
            },
            indent=2,
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
