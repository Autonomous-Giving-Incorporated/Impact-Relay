"""Minimal HTTP API for host UIs (stdlib only).

  python -m impact_relay.console_server --data-dir .impact-relay/hacker-dojo --port 8787

Hacker-Dojo static pages call these JSON endpoints. Not a production ASGI stack —
for pilot/demo. Host production should put auth in front (OIDC gateway).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from impact_relay.host.console import open_donor_console, open_finance_console
from impact_relay.host.hacker_dojo import finance_approver_fixture
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID


def _json_response(handler: BaseHTTPRequestHandler, code: int, body: Any) -> None:
    raw = json.dumps(body, indent=2, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.end_headers()
    handler.wfile.write(raw)


def make_handler(data_dir: Path, tenant_id: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, Authorization"
            )
            self.end_headers()

        def _principal(self):
            # Authorization: Bearer email:user@x or fixture email
            auth = self.headers.get("Authorization") or ""
            if not auth:
                return None
            token = auth.replace("Bearer ", "").strip()
            try:
                from impact_relay.auth.oidc import hacker_dojo_fixture_oidc

                return hacker_dojo_fixture_oidc().principal_for_token(token)
            except Exception:  # noqa: BLE001
                return finance_approver_fixture()

        def _finance(self):
            p = self._principal()
            return open_finance_console(
                data_dir,
                tenant_id=tenant_id,
                principal=p,
                require_principal_for_approve=bool(p),
            )

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)

            try:
                if path == "/api/health":
                    return _json_response(
                        self,
                        200,
                        {
                            "ok": True,
                            "service": "impact-relay-console",
                            "tenant_id": tenant_id,
                            "data_dir": str(data_dir),
                        },
                    )
                if path == "/api/finance/metrics":
                    return _json_response(self, 200, self._finance().metrics())
                if path == "/api/finance/queue":
                    filters = (qs.get("filters") or ["waiting,blocked,dead_letter,needs_information,failed"])[0]
                    return _json_response(self, 200, self._finance().queue(filters=filters))
                m = re.fullmatch(r"/api/finance/cases/([^/]+)", path)
                if m:
                    return _json_response(
                        self, 200, self._finance().case_detail(m.group(1))
                    )
                m = re.fullmatch(r"/api/donors/([^/]+)/dashboard", path)
                if m:
                    cons = open_donor_console(
                        m.group(1),
                        data_dir,
                        tenant_id=tenant_id,
                        principal=self._principal(),
                    )
                    return _json_response(self, 200, {"ok": True, "dashboard": cons.dashboard()})
                m = re.fullmatch(r"/api/donors/([^/]+)/timeline", path)
                if m:
                    cons = open_donor_console(
                        m.group(1), data_dir, tenant_id=tenant_id, principal=self._principal()
                    )
                    return _json_response(self, 200, {"ok": True, "timeline": cons.timeline()})
                m = re.fullmatch(r"/api/donors/([^/]+)/receipts", path)
                if m:
                    cons = open_donor_console(
                        m.group(1), data_dir, tenant_id=tenant_id, principal=self._principal()
                    )
                    return _json_response(self, 200, {"ok": True, "receipts": cons.receipts()})
                m = re.fullmatch(r"/api/donors/([^/]+)/receipts/([^/]+)", path)
                if m:
                    cons = open_donor_console(
                        m.group(1), data_dir, tenant_id=tenant_id, principal=self._principal()
                    )
                    return _json_response(
                        self,
                        200,
                        {"ok": True, "receipt": cons.receipt_detail(m.group(2))},
                    )
                return _json_response(self, 404, {"ok": False, "error": "not_found", "path": path})
            except Exception as exc:  # noqa: BLE001
                return _json_response(
                    self, 400, {"ok": False, "error": type(exc).__name__, "message": str(exc)}
                )

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body = {}

            try:
                if path == "/api/pilot/seed":
                    fin = self._finance()
                    return _json_response(self, 200, fin.seed())
                m = re.fullmatch(r"/api/finance/cases/([^/]+)/approve", path)
                if m:
                    fin = self._finance()
                    out = fin.approve(
                        m.group(1),
                        proposer_id=body.get("proposer_id"),
                        approver_id=body.get("approver_id"),
                    )
                    code = 200 if out.get("ok") else 403
                    return _json_response(self, code, out)
                return _json_response(self, 404, {"ok": False, "error": "not_found"})
            except Exception as exc:  # noqa: BLE001
                return _json_response(
                    self, 400, {"ok": False, "error": type(exc).__name__, "message": str(exc)}
                )

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
    args = p.parse_args(argv)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    handler = make_handler(args.data_dir, args.tenant_id)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        json.dumps(
            {
                "listening": f"http://{args.host}:{args.port}",
                "data_dir": str(args.data_dir.resolve()),
                "tenant_id": args.tenant_id,
                "health": f"http://{args.host}:{args.port}/api/health",
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
