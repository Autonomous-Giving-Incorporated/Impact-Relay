"""Pilot P3: durable worker entrypoint, K11 guard, restart drain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from impact_relay.cli import main
from impact_relay.workflows.durable import (
    durable_seed,
    durable_worker,
    open_workspace,
)
from impact_relay.workflows.guards import (
    DurabilityGuardError,
    assert_durable_worker_allowed,
    resolve_worker_enabled,
)
from impact_relay.workflows.types import WorkflowRunStatus
from impact_relay.workflows.worker import main as worker_main

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def test_guard_refuses_sql_without_ledger() -> None:
    with pytest.raises(DurabilityGuardError, match="K11"):
        assert_durable_worker_allowed(
            workflow_engine="postgres",
            ledger_durability="none",
            worker_enabled=True,
        )
    with pytest.raises(DurabilityGuardError, match="K11"):
        assert_durable_worker_allowed(
            workflow_engine="sqlite",
            ledger_durability="none",
            worker_enabled=True,
        )


def test_guard_allows_sql_with_command_log() -> None:
    assert_durable_worker_allowed(
        workflow_engine="sqlite",
        ledger_durability="command_log",
        worker_enabled=True,
    )


def test_guard_requires_enablement_for_continuous() -> None:
    with pytest.raises(DurabilityGuardError, match="not enabled"):
        assert_durable_worker_allowed(
            workflow_engine="sqlite",
            ledger_durability="command_log",
            worker_enabled=False,
            require_enabled=True,
        )


def test_resolve_worker_enabled_once_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKFLOW_WORKER_ENABLED", raising=False)
    assert resolve_worker_enabled(once=True) is True
    assert resolve_worker_enabled(once=False) is False
    monkeypatch.setenv("WORKFLOW_WORKER_ENABLED", "1")
    assert resolve_worker_enabled(once=False) is True
    assert resolve_worker_enabled(force=True) is True


def test_durable_worker_drains_pending_after_restart(tmp_path: Path) -> None:
    """Simulate kill after start (no seed pump): reopen + worker --once → wait."""
    data_dir = tmp_path / "dur-w"
    ws = open_workspace(data_dir, create=True)
    row = json.loads(BATCH.read_text(encoding="utf-8"))["expenses"][0]
    inst = ws.runtime.start_expense_to_receipt(tenant_id=ws.tenant_id, expense_row=row)
    assert inst.run_status == WorkflowRunStatus.PENDING
    ws.save()

    # Process restart: new open_workspace + worker drain
    out = durable_worker(data_dir, once=True, max_ticks=30)
    assert out["ok"] is True
    assert out["summary"]["claimed"] >= 1
    assert out["summary"]["advanced"] >= 1
    assert out["config"]["ledger_durability"] == "command_log"
    assert out["waiting"], "should park at human approval"
    assert out["waiting"][0]["workflow_id"] == inst.workflow_id

    ws2 = open_workspace(data_dir)
    cur = ws2.store.get(ws2.tenant_id, inst.workflow_id)
    assert cur is not None
    assert cur.run_status == WorkflowRunStatus.WAITING_SIGNAL


def test_durable_worker_continuous_refused_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORKFLOW_WORKER_ENABLED", raising=False)
    durable_seed(tmp_path / "d", expense_batch=BATCH, worker_ticks=0)
    out = durable_worker(tmp_path / "d", once=False, max_ticks=None)
    assert out["ok"] is False
    assert out["error"] == "durability_guard"


def test_cli_durable_worker_once(tmp_path: Path) -> None:
    data_dir = tmp_path / "cli-w"
    # leave PENDING
    code = main(
        [
            "--durable",
            "seed",
            "--data-dir",
            str(data_dir),
        ]
    )
    # seed already pumps; worker --once should idle-exit cleanly
    assert code == 0
    code = main(["--durable", "worker", "--once", "--data-dir", str(data_dir), "--max-ticks", "5"])
    assert code == 0


def test_module_worker_main_once(tmp_path: Path) -> None:
    data_dir = tmp_path / "mod-w"
    ws = open_workspace(data_dir, create=True)
    row = json.loads(BATCH.read_text(encoding="utf-8"))["expenses"][0]
    ws.runtime.start_expense_to_receipt(tenant_id=ws.tenant_id, expense_row=row)
    ws.save()
    code = worker_main(["--data-dir", str(data_dir), "--once", "--max-ticks", "25"])
    assert code == 0
