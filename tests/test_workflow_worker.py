"""PR-M4: worker claim loop, retry/DLQ, approval timeout sweeper."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.agents.types import ApprovalReceipt, WorkflowState, utc_now_iso
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.store_memory import InMemoryWorkflowStore
from impact_relay.workflows.types import (
    WorkflowEventType,
    WorkflowInstance,
    WorkflowRunStatus,
    WorkflowType,
)
from impact_relay.workflows.worker import WorkerConfig, WorkflowWorker

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _ledger():
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    return build_ledger_from_fixture(data)


def _row():
    return json.loads(BATCH.read_text(encoding="utf-8"))["expenses"][0]


def _rt():
    ledger = _ledger()
    store = InMemoryWorkflowStore()
    binding = InMemoryLedgerBinding()
    binding.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
    return WorkflowRuntime(store, binding), store, ledger


def test_worker_tick_claims_and_advances_to_wait() -> None:
    rt, store, ledger = _rt()
    inst = rt.start_expense_to_receipt(tenant_id=ledger.organization.id, expense_row=_row())
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="t1", claim_batch_size=5))
    # Multiple ticks to get through auto steps to WAITING_SIGNAL
    for _ in range(10):
        worker.tick()
        cur = store.get(ledger.organization.id, inst.workflow_id)
        assert cur is not None
        if cur.run_status == WorkflowRunStatus.WAITING_SIGNAL:
            break
    cur = store.get(ledger.organization.id, inst.workflow_id)
    assert cur is not None
    assert cur.workflow_state == WorkflowState.REVIEW_PENDING
    assert cur.run_status == WorkflowRunStatus.WAITING_SIGNAL


def test_worker_plus_signal_reaches_approved() -> None:
    rt, store, ledger = _rt()
    inst = rt.start_expense_to_receipt(tenant_id=ledger.organization.id, expense_row=_row())
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="t2"))
    for _ in range(10):
        worker.tick()
        cur = store.get(ledger.organization.id, inst.workflow_id)
        if cur and cur.run_status == WorkflowRunStatus.WAITING_SIGNAL:
            break
    cur = store.get(ledger.organization.id, inst.workflow_id)
    assert cur is not None
    wait = cur.context["wait"]
    key = wait["frozen_command"]["idempotency_key"]
    rt.signal_approval(
        tenant_id=ledger.organization.id,
        workflow_id=inst.workflow_id,
        approval=ApprovalReceipt(
            approval_id="a1",
            tenant_id=ledger.organization.id,
            proposal_id="p",
            command_idempotency_key=key,
            decision="APPROVE",
            approver_id="human@x",
            approver_role="finance_approver",
            approved_at=utc_now_iso(),
        ),
    )
    for _ in range(10):
        worker.tick()
        cur = store.get(ledger.organization.id, inst.workflow_id)
        if cur and cur.workflow_state == WorkflowState.LEDGER_COMMITTED:
            break
        if cur and cur.run_status == WorkflowRunStatus.COMPLETED:
            break
    cur = store.get(ledger.organization.id, inst.workflow_id)
    assert cur is not None
    assert cur.workflow_state in (
        WorkflowState.LEDGER_COMMITTED,
        WorkflowState.PUBLICATION_PENDING,
    )
    exp_id = cur.context["expense_id"]
    assert ledger.expenses[exp_id].state.value == "APPROVED"


def test_dead_letter_after_max_attempts() -> None:
    store = InMemoryWorkflowStore()
    inst = WorkflowInstance(
        workflow_id="wf_dlq",
        tenant_id="org_x",
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="bk",
        workflow_state=WorkflowState.RECEIVED,
        run_status=WorkflowRunStatus.PENDING,
        attempt_count=5,
        next_run_at=utc_now_iso(),
    )
    store.create(inst)
    # Minimal runtime that will claim this — use real runtime with empty ledger
    ledger = _ledger()
    binding = InMemoryLedgerBinding()
    binding.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
    # re-key tenant to match
    store2 = InMemoryWorkflowStore()
    inst2 = WorkflowInstance(
        workflow_id="wf_dlq2",
        tenant_id=ledger.organization.id,
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="bk2",
        workflow_state=WorkflowState.RECEIVED,
        run_status=WorkflowRunStatus.PENDING,
        attempt_count=5,
        next_run_at=utc_now_iso(),
        context={"expense_row": _row()},
    )
    store2.create(inst2)
    binding2 = InMemoryLedgerBinding()
    binding2.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
    rt = WorkflowRuntime(store2, binding2)
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="dlq", max_attempts=5))
    result = worker.tick()
    assert result.dead_lettered >= 1
    cur = store2.get(ledger.organization.id, "wf_dlq2")
    assert cur is not None
    assert cur.run_status == WorkflowRunStatus.DEAD_LETTER
    # business state preserved
    assert cur.workflow_state == WorkflowState.RECEIVED
    events = store2.list_events(ledger.organization.id, "wf_dlq2")
    assert any(e.event_type == WorkflowEventType.DEAD_LETTERED for e in events)


def test_timeout_sweeper_idempotent() -> None:
    store = InMemoryWorkflowStore()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    inst = WorkflowInstance(
        workflow_id="wf_to",
        tenant_id="org_x",
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="bk",
        workflow_state=WorkflowState.REVIEW_PENDING,
        run_status=WorkflowRunStatus.WAITING_SIGNAL,
        wait_deadline=past,
        context={
            "wait": {
                "command_idempotency_key": "approve:exp:1",
                "frozen_command": {
                    "command_type": "approve_expense",
                    "tenant_id": "org_x",
                    "payload": {},
                    "idempotency_key": "approve:exp:1",
                    "expires_at": None,
                    "required_authority": "L3",
                    "proposal_id": "p",
                    "agent_name": "finance_review",
                },
            }
        },
        wait_descriptor={"command_idempotency_key": "approve:exp:1", "proposal_id": "p"},
    )
    store.create(inst)
    first = store.sweep_approval_timeouts()
    assert first == ["wf_to"]
    cur = store.get("org_x", "wf_to")
    assert cur is not None
    assert cur.workflow_state == WorkflowState.NEEDS_INFORMATION
    assert cur.wait_deadline is None
    assert cur.timeout_applied_at is not None
    assert cur.context.get("wait_expired") is True
    assert "wait" not in cur.context
    assert "expired_wait" in cur.context
    # Second sweep no-op
    second = store.sweep_approval_timeouts()
    assert second == []
    events = store.list_events("org_x", "wf_to")
    timeouts = [e for e in events if e.event_type == WorkflowEventType.APPROVAL_TIMEOUT]
    assert len(timeouts) == 1


def test_late_approve_after_timeout_rejected() -> None:
    rt, store, ledger = _rt()
    inst = rt.start_expense_to_receipt(tenant_id=ledger.organization.id, expense_row=_row())
    # pump to wait
    inst = rt.run_until_wait_or_terminal(inst.workflow_id, tenant_id=ledger.organization.id)
    assert inst.run_status == WorkflowRunStatus.WAITING_SIGNAL
    key = inst.context["wait"]["frozen_command"]["idempotency_key"]
    # Force timeout
    inst.wait_deadline = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.update_instance(inst)
    timed = store.sweep_approval_timeouts()
    assert inst.workflow_id in timed
    cur = store.get(ledger.organization.id, inst.workflow_id)
    assert cur is not None
    assert cur.context.get("wait_expired")
    # Late APPROVE
    rt.signal_approval(
        tenant_id=ledger.organization.id,
        workflow_id=inst.workflow_id,
        approval=ApprovalReceipt(
            approval_id="late",
            tenant_id=ledger.organization.id,
            proposal_id="p",
            command_idempotency_key=key,
            decision="APPROVE",
            approver_id="human@x",
            approver_role="finance_approver",
            approved_at=utc_now_iso(),
        ),
    )
    # claim and advance should reject
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="late"))
    worker.tick()
    cur = store.get(ledger.organization.id, inst.workflow_id)
    assert cur is not None
    # Still needs information / not ledger committed
    assert cur.workflow_state != WorkflowState.LEDGER_COMMITTED
    assert cur.workflow_state == WorkflowState.NEEDS_INFORMATION


def test_worker_run_stop_when_idle() -> None:
    rt, _store, _ledger = _rt()
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="idle"))
    results = worker.run(max_ticks=5, stop_when_idle=True)
    assert len(results) >= 1
    assert results[0].claimed == 0
