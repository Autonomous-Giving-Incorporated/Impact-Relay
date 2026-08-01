"""Pilot P1: ledger command log rehydrate + easy durable CLI."""

from __future__ import annotations

import json
from pathlib import Path

from impact_relay.cli import main
from impact_relay.domain.types import ExpenseState
from impact_relay.workflows.durable import (
    durable_approve,
    durable_list,
    durable_rehydrate_check,
    durable_seed,
    durable_status,
    open_workspace,
)
from impact_relay.domain.ledger_log import (
    FileLedgerCommandLog,
    apply_result_json,
    build_result_json,
    snapshot_ledger_entities,
)


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def test_apply_result_json_roundtrip() -> None:
    from impact_relay.pilot import build_ledger_from_fixture, load_fixture
    import copy

    data = copy.deepcopy(load_fixture())
    # keep expenses for snapshot source
    src = build_ledger_from_fixture(data)
    snap = snapshot_ledger_entities(src)
    result = {
        "command_type": "import_normalized_expense",
        "idempotency_key": "k",
        "entities": snap,
        "output_refs": list(src.expenses.keys()),
        "output_payload": {},
    }
    data2 = copy.deepcopy(load_fixture())
    data2["expenses"] = []
    data2["publish"] = []
    empty = build_ledger_from_fixture(data2)
    apply_result_json(empty, result)
    assert set(empty.expenses.keys()) == set(src.expenses.keys())
    for eid, exp in src.expenses.items():
        assert empty.expenses[eid].state == exp.state
        assert empty.expenses[eid].amount == exp.amount


def test_file_log_append_and_rehydrate(tmp_path: Path) -> None:
    from impact_relay.pilot import build_ledger_from_fixture, load_fixture
    import copy
    from impact_relay.agents.executor import LedgerCommandExecutor
    from impact_relay.agents.types import AgentCommand, AuthorityLevel
    from impact_relay.domain.tenant import TenantWorkspace

    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    log = FileLedgerCommandLog(tmp_path / "log.jsonl")
    ex = LedgerCommandExecutor(
        ledger, workspace=TenantWorkspace(ledger.organization, ledger=ledger)
    )
    row = json.loads(BATCH.read_text())["expenses"][0]
    from impact_relay.agents.expense_workflow import normalize_expense_row
    from impact_relay.agents.types import to_jsonable

    n = normalize_expense_row(row, tenant_id=ledger.organization.id)
    cmd = AgentCommand(
        command_type="import_normalized_expense",
        tenant_id=ledger.organization.id,
        payload={"expense": to_jsonable(n)},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
        idempotency_key="import:test1",
    )
    receipt = ex.execute(cmd)
    assert receipt.status == "SUCCEEDED"
    result = build_result_json(
        command_type=cmd.command_type,
        idempotency_key=cmd.idempotency_key,
        ledger=ledger,
        output_refs=receipt.output_refs,
        output_payload={"expense_id": receipt.output_refs[0]},
    )
    log.append(
        tenant_id=ledger.organization.id,
        idempotency_key=cmd.idempotency_key,
        command_type=cmd.command_type,
        payload=cmd.payload,
        result_json=result,
    )
    expense_id = receipt.output_refs[0]

    # Fresh process simulation
    data2 = copy.deepcopy(load_fixture())
    data2["expenses"] = []
    data2["publish"] = []
    base = build_ledger_from_fixture(data2)
    rebuilt = log.rehydrate(base.organization, base_ledger=base)
    assert expense_id in rebuilt.expenses
    assert rebuilt.expenses[expense_id].external_source_id == row["external_source_id"]


def test_durable_seed_approve_check(tmp_path: Path) -> None:
    data_dir = tmp_path / "dur"
    seed = durable_seed(data_dir, expense_batch=BATCH)
    assert seed["ok"]
    assert seed["waiting"]
    assert seed.get("entity_snapshot", {}).get("ok") is True
    exp_id_before = None
    ws = open_workspace(data_dir)
    # after seed, expense exists in ledger (imported)
    ledger = ws.binding.for_tenant(ws.tenant_id)
    assert ledger.expenses
    exp_id_before = next(iter(ledger.expenses))
    # Host-app path: entity snapshot auto-saved under storage.db
    assert ws.storage is not None
    assert ws.storage.ledger.get_expense(ws.tenant_id, exp_id_before) is not None

    listed = durable_list(data_dir)
    assert listed["count"] >= 1
    wid = listed["cases"][0]["workflow_id"]

    approved = durable_approve(data_dir, workflow_id=wid)
    assert approved["ok"]
    assert approved["expense_id"] == exp_id_before
    assert approved["expense_state"] == ExpenseState.APPROVED.value
    assert approved.get("entity_snapshot", {}).get("ok") is True

    # Restart simulation
    check = durable_rehydrate_check(data_dir)
    assert check["ok"]
    assert check["ids_stable"]
    assert exp_id_before in check["expense_ids_after"]
    assert check["states_after"][exp_id_before] == ExpenseState.APPROVED.value

    status = durable_status(data_dir)
    assert status["ok"]
    assert status["ledger_commands"] >= 1
    assert status.get("entity_snapshot", {}).get("expenses", 0) >= 1
    # Snapshot reflects approved state for host list views
    snap_exp = open_workspace(data_dir).storage.ledger.get_expense(
        status["tenant_id"], exp_id_before
    )
    assert snap_exp is not None
    assert snap_exp["state"] == ExpenseState.APPROVED.value


def test_cli_durable_flow(tmp_path: Path) -> None:
    data_dir = tmp_path / "cli-dur"
    code = main(["--durable", "seed", "--data-dir", str(data_dir)])
    assert code == 0
    code = main(["--durable", "list", "--data-dir", str(data_dir)])
    assert code == 0
    code = main(
        [
            "--durable",
            "approve",
            "--data-dir",
            str(data_dir),
            "--approver-id",
            "human@dojo.example",
        ]
    )
    assert code == 0
    code = main(["--durable", "check", "--data-dir", str(data_dir)])
    assert code == 0
    code = main(["--durable", "status", "--data-dir", str(data_dir)])
    assert code == 0


def test_cli_durable_help() -> None:
    code = main(["--durable", "help"])
    assert code == 0
