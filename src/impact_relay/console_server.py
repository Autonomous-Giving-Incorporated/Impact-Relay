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
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID

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
                self, cfg.tenant_id, trusted_proxy=cfg.trusted_proxy
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
                    },
                }
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
    cfg = ServerConfig(
        data_dir=args.data_dir,
        tenant_id=args.tenant_id,
        allow_unauthenticated_pilot=args.allow_unauthenticated_pilot,
        trusted_proxy=args.trusted_proxy,
        max_body_bytes=args.max_body_bytes,
        allowed_origins=tuple(args.allow_origin),
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
