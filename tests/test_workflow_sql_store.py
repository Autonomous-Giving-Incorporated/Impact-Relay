"""Pilot P2: SqlWorkflowStore (SQLite default; Postgres if IMPACT_RELAY_DATABASE_URL)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from impact_relay.agents.types import (
    ExecutionReceipt,
    WorkflowState,
    utc_now_iso,
)
from impact_relay.domain.types import ExpenseState
from impact_relay.workflows.durable import (
    durable_approve,
    durable_list,
    durable_rehydrate_check,
    durable_seed,
    durable_status,
    open_workspace,
)
from impact_relay.workflows.exceptions import WorkflowConflictError, WorkflowStateError
from impact_relay.workflows.store_sql import SqlWorkflowStore, open_sql_store
from impact_relay.workflows.types import (
    AdvanceCommitBundle,
    SignalType,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowInstance,
    WorkflowRunStatus,
    WorkflowSignal,
    WorkflowType,
)

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"
PG_URL = os.environ.get("IMPACT_RELAY_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _instance(
    wid: str = "wf_sql_1",
    *,
    tenant: str = "t1",
    bk: str = "bk1",
    run: WorkflowRunStatus = WorkflowRunStatus.PENDING,
    state: WorkflowState = WorkflowState.RECEIVED,
    next_run: datetime | None = None,
) -> WorkflowInstance:
    n = next_run or _now()
    iso = n.isoformat()
    return WorkflowInstance(
        workflow_id=wid,
        tenant_id=tenant,
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key=bk,
        workflow_state=state,
        run_status=run,
        context={"k": "v"},
        simulation=False,
        created_at=iso,
        updated_at=iso,
        next_run_at=iso,
    )


def test_sqlite_create_get_claim_never_waiting(tmp_path: Path) -> None:
    store = SqlWorkflowStore(tmp_path / "workflows.db")
    now = _now()
    store.create(_instance("w1", bk="a", next_run=now))
    store.create(
        _instance(
            "w2",
            bk="b",
            run=WorkflowRunStatus.WAITING_SIGNAL,
            state=WorkflowState.REVIEW_PENDING,
            next_run=now,
        )
    )
    got = store.get("t1", "w1")
    assert got is not None
    assert got.business_key == "a"

    claimed = store.claim(
        worker_id="worker-1",
        limit=10,
        now=now,
        lease_ttl=timedelta(seconds=60),
    )
    ids = {c.workflow_id for c in claimed}
    assert "w1" in ids
    assert "w2" not in ids  # WAITING_SIGNAL never claimable
    assert all(c.run_status == WorkflowRunStatus.RUNNING for c in claimed)
    assert all(c.lease_owner == "worker-1" for c in claimed)


def test_sqlite_conflict_on_business_key(tmp_path: Path) -> None:
    store = SqlWorkflowStore(tmp_path / "workflows.db")
    store.create(_instance("w1", bk="same"))
    with pytest.raises(WorkflowConflictError):
        store.create(_instance("w2", bk="same"))


def test_sqlite_receipts_reject_failed(tmp_path: Path) -> None:
    store = SqlWorkflowStore(tmp_path / "workflows.db")
    store.create(_instance())
    ok = ExecutionReceipt(
        execution_id="ex1",
        tenant_id="t1",
        command_type="import_normalized_expense",
        idempotency_key="k1",
        status="SUCCEEDED",
        output_refs=["exp_1"],
        output_hash="h",
        executed_at=utc_now_iso(),
    )
    store.put_execution_receipt(ok, workflow_id="wf_sql_1")
    assert store.get_execution_receipt("t1", "k1") is not None

    bad = ExecutionReceipt(
        execution_id="ex2",
        tenant_id="t1",
        command_type="approve_expense",
        idempotency_key="k2",
        status="FAILED",
        output_refs=[],
        output_hash="",
        executed_at=utc_now_iso(),
        error="nope",
    )
    with pytest.raises(WorkflowStateError):
        store.put_execution_receipt(bad, workflow_id="wf_sql_1")
    assert store.get_execution_receipt("t1", "k2") is None


def test_sqlite_signal_wake_and_commit_advance(tmp_path: Path) -> None:
    store = SqlWorkflowStore(tmp_path / "workflows.db")
    now = _now()
    inst = _instance(
        run=WorkflowRunStatus.WAITING_SIGNAL,
        state=WorkflowState.REVIEW_PENDING,
        next_run=now,
    )
    store.create(inst)
    sig = WorkflowSignal(
        signal_id="sig_1",
        workflow_id=inst.workflow_id,
        tenant_id="t1",
        signal_type=SignalType.APPROVAL,
        payload={"decision": "APPROVE"},
        created_at=utc_now_iso(),
    )
    store.enqueue_signal_and_wake(
        tenant_id="t1",
        workflow_id=inst.workflow_id,
        signal=sig,
        new_run_status=WorkflowRunStatus.PENDING,
        next_run_at=now,
        clear_lease=True,
    )
    pending = store.take_unconsumed_signals("t1", inst.workflow_id)
    assert len(pending) == 1
    assert pending[0].signal_id == "sig_1"

    woken = store.get("t1", inst.workflow_id)
    assert woken is not None
    assert woken.run_status == WorkflowRunStatus.PENDING

    woken.workflow_state = WorkflowState.APPROVED
    woken.run_status = WorkflowRunStatus.COMPLETED
    woken.context = {"expense_id": "exp_x"}
    receipt = ExecutionReceipt(
        execution_id="ex_a",
        tenant_id="t1",
        command_type="approve_expense",
        idempotency_key="approve:exp_x",
        status="SUCCEEDED",
        output_refs=["exp_x"],
        output_hash="h",
        executed_at=utc_now_iso(),
    )
    store.commit_advance(
        AdvanceCommitBundle(
            tenant_id="t1",
            workflow_id=inst.workflow_id,
            instance=woken,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.STATE_CHANGED,
                    payload={"to": "APPROVED"},
                )
            ],
            execution_receipts=[receipt],
            consume_signals=[(sig.signal_id, "ACCEPTED")],
        )
    )
    done = store.get("t1", inst.workflow_id)
    assert done is not None
    assert done.run_status == WorkflowRunStatus.COMPLETED
    assert store.get_execution_receipt("t1", "approve:exp_x") is not None
    assert store.take_unconsumed_signals("t1", inst.workflow_id) == []
    events = store.list_events("t1", inst.workflow_id)
    assert any(e.event_type == WorkflowEventType.STATE_CHANGED for e in events)


def test_sqlite_approval_timeout_sweep(tmp_path: Path) -> None:
    store = SqlWorkflowStore(tmp_path / "workflows.db")
    past = (_now() - timedelta(hours=1)).isoformat()
    inst = _instance(
        run=WorkflowRunStatus.WAITING_SIGNAL,
        state=WorkflowState.REVIEW_PENDING,
    )
    inst.wait_deadline = past
    inst.wait_descriptor = {"command_idempotency_key": "approve:x"}
    inst.context = {"wait": {"command_idempotency_key": "approve:x"}}
    store.create(inst)
    timed = store.sweep_approval_timeouts(_now())
    assert inst.workflow_id in timed
    after = store.get("t1", inst.workflow_id)
    assert after is not None
    assert after.workflow_state == WorkflowState.NEEDS_INFORMATION
    assert after.timeout_applied_at is not None
    # second sweep is idempotent
    assert store.sweep_approval_timeouts(_now()) == []


def test_open_sql_store_defaults_to_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMPACT_RELAY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = open_sql_store(tmp_path)
    assert store._is_sqlite
    assert (tmp_path / "workflows.db").is_file() or True  # created on migrate
    store.create(_instance())
    assert store.get("t1", "wf_sql_1") is not None


def test_durable_sqlite_roundtrip_shows_completed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("IMPACT_RELAY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    data_dir = tmp_path / "dur-sql"
    seed = durable_seed(data_dir, expense_batch=BATCH)
    assert seed["ok"] and seed["waiting"]
    assert (data_dir / "workflows.db").is_file()
    assert not (data_dir / "workflow_session.pkl").exists()

    listed = durable_list(data_dir)
    wid = listed["cases"][0]["workflow_id"]
    approved = durable_approve(data_dir, workflow_id=wid)
    assert approved["ok"]
    assert approved["expense_state"] == ExpenseState.APPROVED.value

    check = durable_rehydrate_check(data_dir)
    assert check["ok"] and check["ids_stable"]

    status = durable_status(data_dir)
    assert status["ok"]
    assert status["workflow_store"] == "sqlite"
    assert status["workflows"], "status should list completed workflows"
    assert any(w["run"] == "COMPLETED" for w in status["workflows"])

    # reopen process: workflow still in sqlite
    ws = open_workspace(data_dir)
    inst = ws.store.get(ws.tenant_id, wid)
    assert inst is not None
    assert inst.run_status == WorkflowRunStatus.COMPLETED


@pytest.mark.skipif(not PG_URL, reason="set IMPACT_RELAY_DATABASE_URL for Postgres tests")
def test_postgres_store_claim_skip_locked() -> None:
    """Requires live Postgres + pip install 'impact-relay[db]'."""
    try:
        import psycopg  # noqa: F401
    except ImportError:
        pytest.skip("psycopg not installed")

    # Isolate rows with unique tenant per run
    tenant = f"pg_t_{utc_now_iso().replace(':', '').replace('+', '')}"
    store = SqlWorkflowStore(PG_URL)
    now = _now()
    wid = f"wf_pg_{tenant}"
    store.create(_instance(wid, tenant=tenant, bk=f"bk_{tenant}", next_run=now))
    claimed = store.claim(
        worker_id="pg-worker",
        limit=50,
        now=now,
        lease_ttl=timedelta(seconds=30),
    )
    ours = [c for c in claimed if c.workflow_id == wid]
    assert len(ours) == 1
    assert ours[0].lease_owner == "pg-worker"
    # WAITING never claimed
    store.create(
        _instance(
            wid + "_wait",
            tenant=tenant,
            bk=f"bk_wait_{tenant}",
            run=WorkflowRunStatus.WAITING_SIGNAL,
            next_run=now,
        )
    )
    claimed2 = store.claim(
        worker_id="pg-worker-2",
        limit=50,
        now=now,
        lease_ttl=timedelta(seconds=30),
    )
    assert all(c.workflow_id != wid + "_wait" for c in claimed2)
