"""Finance + donor console APIs and HTTP handler smoke tests."""

from __future__ import annotations

from pathlib import Path

from impact_relay.host.console import open_donor_console, open_finance_console
from impact_relay.host.hacker_dojo import finance_approver_fixture
from impact_relay.pilot import run_pilot
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.donor import open_donor_api
from impact_relay.storage import open_storage
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    ensure_canonical_hacker_dojo_tenant,
)


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


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


def test_http_handler_health_and_queue(tmp_path: Path) -> None:
    from impact_relay.console_server import make_handler
    from io import BytesIO

    data_dir = tmp_path / "http"
    Handler = make_handler(data_dir, CANONICAL_PILOT_TENANT_ID)

    def run_get(path: str) -> tuple[int, str]:
        h = Handler.__new__(Handler)
        h.headers = {"Authorization": "Bearer finance.approver@hackersdojo.example"}
        h.path = path
        h.wfile = BytesIO()
        h.rfile = BytesIO()
        h.requestline = f"GET {path} HTTP/1.1"
        h.client_address = ("127.0.0.1", 0)
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        codes: list[int] = []

        def send_response(code, message=None):
            codes.append(code)

        h.send_response = send_response  # type: ignore[method-assign]
        h.send_header = lambda *a, **k: None  # type: ignore[method-assign]
        h.end_headers = lambda: None  # type: ignore[method-assign]
        h.log_message = lambda *a, **k: None  # type: ignore[method-assign]
        h.do_GET()
        return codes[-1] if codes else 0, h.wfile.getvalue().decode()

    code, body = run_get("/api/health")
    assert code == 200
    assert "impact-relay-console" in body

    fin = open_finance_console(data_dir, principal=finance_approver_fixture())
    fin.seed(expense_batch=BATCH)
    code2, body2 = run_get("/api/finance/queue?filters=waiting")
    assert code2 == 200
    assert "cases" in body2
