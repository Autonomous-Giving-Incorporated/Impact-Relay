"""Finance + donor console APIs and HTTP handler auth/semantics tests."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from impact_relay.console_server import make_handler
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.donor import open_donor_api
from impact_relay.host.console import open_finance_console
from impact_relay.host.hacker_dojo import finance_approver_fixture
from impact_relay.pilot import run_pilot
from impact_relay.storage import open_storage
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    ensure_canonical_hacker_dojo_tenant,
)

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"

APPROVER_AUTH = {"Authorization": "Bearer finance.approver@hackersdojo.example"}
AUDITOR_AUTH = {"Authorization": "Bearer auditor@hackersdojo.example"}


class _Response:
    def __init__(self, code: int, headers: list[tuple[str, str]], body: str) -> None:
        self.code = code
        self.headers = headers
        self.raw = body

    @property
    def json(self) -> dict[str, Any]:
        return json.loads(self.raw or "{}")

    def header(self, name: str) -> str | None:
        for key, value in self.headers:
            if key.lower() == name.lower():
                return value
        return None


def _request(
    handler_cls: type,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    raw_body: bytes | None = None,
    content_length: str | None = None,
) -> _Response:
    """Drive one request through the handler without opening a socket."""
    h = handler_cls.__new__(handler_cls)
    req_headers = dict(headers or {})
    payload = (
        raw_body
        if raw_body is not None
        else (json.dumps(body).encode("utf-8") if body is not None else b"")
    )
    if payload or content_length is not None:
        req_headers.setdefault("Content-Length", content_length or str(len(payload)))
    h.headers = req_headers
    h.path = path
    h.rfile = BytesIO(payload)
    h.wfile = BytesIO()
    h.requestline = f"{method} {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 0)
    h.request_version = "HTTP/1.1"
    h.command = method

    codes: list[int] = []
    sent: list[tuple[str, str]] = []
    h.send_response = lambda code, message=None: codes.append(code)  # type: ignore[method-assign]
    h.send_header = lambda k, v: sent.append((k, v))  # type: ignore[method-assign]
    h.end_headers = lambda: None  # type: ignore[method-assign]
    h.log_message = lambda *a, **k: None  # type: ignore[method-assign]

    getattr(h, f"do_{method}")()
    return _Response(codes[-1] if codes else 0, sent, h.wfile.getvalue().decode())


def _seeded(tmp_path: Path) -> tuple[Path, str]:
    """Data dir with one waiting expense case, plus its workflow_id."""
    data_dir = tmp_path / "srv"
    fin = open_finance_console(data_dir, principal=finance_approver_fixture())
    fin.seed(expense_batch=BATCH)
    wid = fin.queue(filters="waiting")["cases"][0]["workflow_id"]
    return data_dir, wid


# ---------------------------------------------------------------------------
# Console API (in-process)
# ---------------------------------------------------------------------------


def test_finance_console_seed_queue_approve(tmp_path: Path) -> None:
    principal = finance_approver_fixture()
    fin = open_finance_console(
        tmp_path / "c",
        principal=principal,
        require_principal_for_approve=True,
    )
    seed = fin.seed(expense_batch=BATCH)
    assert seed["ok"]
    metrics = fin.metrics()
    assert metrics["waiting_count"] >= 1
    queue = fin.queue(filters="waiting")
    assert queue["ok"] and queue["count"] >= 1
    wid = queue["cases"][0]["workflow_id"]
    detail = fin.case_detail(wid)
    assert detail["ok"]
    assert detail["case"]["workflow_id"] == wid
    approved = fin.approve(wid)
    assert approved["ok"] is True


def test_donor_console_from_pilot_snapshot(tmp_path: Path) -> None:
    # Persist pilot ledger into storage under data-dir for donor_api path
    data_dir = tmp_path / "d"
    store = open_storage(data_dir)
    ensure_canonical_hacker_dojo_tenant(store)
    ledger, receipts = run_pilot()
    store.ledger.save_ledger(ledger)
    # Also need workspace meta for open_workspace - use finance seed lighter path:
    # donor_api via console uses open_workspace which needs durable workspace.
    # Use DonorExperienceAPI directly for unit path; console donor needs durable dir.
    api = open_donor_api(TenantWorkspace(ledger.organization, ledger=ledger))
    donor_id = receipts[0].donor_id
    dash = api.dashboard(donor_id)
    assert dash["donor_id"] == donor_id
    assert dash["receipts"]


# ---------------------------------------------------------------------------
# HTTP: happy paths
# ---------------------------------------------------------------------------


def test_health_needs_no_auth_and_reports_posture(tmp_path: Path) -> None:
    handler = make_handler(tmp_path / "http", CANONICAL_PILOT_TENANT_ID)
    res = _request(handler, "GET", "/api/health")
    assert res.code == 200
    assert res.json["service"] == "impact-relay-console"
    assert res.json["auth"] == {
        "allow_unauthenticated_pilot": False,
        "trusted_proxy": False,
    }


def test_authenticated_queue_and_approve(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)

    listed = _request(handler, "GET", "/api/finance/queue?filters=waiting", headers=APPROVER_AUTH)
    assert listed.code == 200
    assert listed.json["count"] >= 1

    approved = _request(
        handler,
        "POST",
        f"/api/finance/cases/{wid}/approve",
        headers=APPROVER_AUTH,
        body={},
    )
    assert approved.code == 200
    assert approved.json["ok"] is True


# ---------------------------------------------------------------------------
# HTTP: default-deny auth
# ---------------------------------------------------------------------------


def test_unauthenticated_approve_is_rejected(tmp_path: Path) -> None:
    """The fail-open regression this suite exists to prevent."""
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)

    res = _request(handler, "POST", f"/api/finance/cases/{wid}/approve", body={})
    assert res.code == 401
    assert res.json["error"] == "authentication_required"

    # And the case is still waiting — nothing was mutated.
    fin = open_finance_console(data_dir, principal=finance_approver_fixture())
    assert fin.queue(filters="waiting")["count"] >= 1


def test_unauthenticated_seed_is_rejected(tmp_path: Path) -> None:
    handler = make_handler(tmp_path / "srv", CANONICAL_PILOT_TENANT_ID)
    res = _request(handler, "POST", "/api/pilot/seed", body={})
    assert res.code == 401


def test_unauthenticated_reads_are_rejected(tmp_path: Path) -> None:
    data_dir, _ = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)
    for path in (
        "/api/finance/queue",
        "/api/finance/metrics",
        "/api/donors/donor_alice/receipts",
    ):
        assert _request(handler, "GET", path).code == 401, path


def test_forged_identity_headers_are_ignored_by_default(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)
    forged = {
        "X-Impact-Email": "attacker@example.com",
        "X-HD-Campaign-Role": "director",
    }
    res = _request(handler, "POST", f"/api/finance/cases/{wid}/approve", headers=forged, body={})
    assert res.code == 401


def test_trusted_proxy_mode_accepts_identity_headers(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID, trusted_proxy=True)
    res = _request(
        handler,
        "POST",
        f"/api/finance/cases/{wid}/approve",
        headers={
            "X-Impact-Email": "lead@hackersdojo.org",
            "X-HD-Campaign-Role": "campaign_lead",
        },
        body={},
    )
    assert res.code == 200
    assert res.json["ok"] is True


def test_unauthenticated_pilot_mode_restores_open_access(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID, allow_unauthenticated_pilot=True)
    res = _request(handler, "POST", f"/api/finance/cases/{wid}/approve", body={})
    assert res.code == 200
    assert res.json["ok"] is True


def test_underprivileged_role_cannot_approve(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)
    res = _request(
        handler,
        "POST",
        f"/api/finance/cases/{wid}/approve",
        headers=AUDITOR_AUTH,
        body={},
    )
    assert res.code == 403
    assert res.json["error"] == "forbidden"


def test_self_approval_is_rejected_with_403(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)
    res = _request(
        handler,
        "POST",
        f"/api/finance/cases/{wid}/approve",
        headers=APPROVER_AUTH,
        body={"proposer_id": "finance.approver@hackersdojo.example"},
    )
    assert res.code == 403
    assert res.json["error"] == "separation_of_duties"


# ---------------------------------------------------------------------------
# HTTP: status semantics, body limits, CORS
# ---------------------------------------------------------------------------


def test_unknown_route_and_unknown_case_are_404(tmp_path: Path) -> None:
    data_dir, _ = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)
    assert _request(handler, "GET", "/api/nope", headers=APPROVER_AUTH).code == 404
    missing = _request(
        handler, "GET", "/api/finance/cases/wf_does_not_exist", headers=APPROVER_AUTH
    )
    assert missing.code == 404


def test_oversized_body_is_rejected(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID, max_body_bytes=64)
    res = _request(
        handler,
        "POST",
        f"/api/finance/cases/{wid}/approve",
        headers=APPROVER_AUTH,
        raw_body=b"x" * 512,
    )
    assert res.code == 413
    assert res.json["error"] == "payload_too_large"


def test_malformed_body_is_400_not_500(tmp_path: Path) -> None:
    data_dir, wid = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)
    res = _request(
        handler,
        "POST",
        f"/api/finance/cases/{wid}/approve",
        headers=APPROVER_AUTH,
        raw_body=b"{not json",
    )
    assert res.code == 400
    assert res.json["error"] == "bad_request"


def test_no_cors_header_unless_configured(tmp_path: Path) -> None:
    data_dir, _ = _seeded(tmp_path)
    strict = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)
    res = _request(strict, "GET", "/api/health", headers={"Origin": "https://evil.example"})
    assert res.header("Access-Control-Allow-Origin") is None

    allowed = make_handler(
        data_dir,
        CANONICAL_PILOT_TENANT_ID,
        allowed_origins=("https://dojo.example",),
    )
    ok = _request(allowed, "GET", "/api/health", headers={"Origin": "https://dojo.example"})
    assert ok.header("Access-Control-Allow-Origin") == "https://dojo.example"
    assert ok.header("Vary") == "Origin"

    denied = _request(allowed, "GET", "/api/health", headers={"Origin": "https://evil.example"})
    assert denied.header("Access-Control-Allow-Origin") is None


def test_internal_errors_do_not_leak_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir, _ = _seeded(tmp_path)
    handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("secret connection string")

    monkeypatch.setattr("impact_relay.console_server.open_finance_console", boom)
    res = _request(handler, "GET", "/api/finance/metrics", headers=APPROVER_AUTH)
    assert res.code == 500
    assert res.json == {"ok": False, "error": "internal_error"}
    assert "secret" not in res.raw
