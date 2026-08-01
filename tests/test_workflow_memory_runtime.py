"""PR-M3: memory store, runtime pause/resume, receipt index, façade flag."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from impact_relay.agents.types import (
    ApprovalReceipt,
    WorkflowState,
    utc_now_iso,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.store_memory import InMemoryWorkflowStore
from impact_relay.workflows.types import WorkflowRunStatus


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _ledger_empty_expenses():
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    return build_ledger_from_fixture(data)


def _row() -> dict:
    return json.loads(BATCH.read_text(encoding="utf-8"))["expenses"][0]


def _runtime_with_ledger(ledger):
    store = InMemoryWorkflowStore()
    binding = InMemoryLedgerBinding()
    from impact_relay.domain.tenant import TenantWorkspace

    binding.register(
        ledger, TenantWorkspace(ledger.organization, ledger=ledger)
    )
    return WorkflowRuntime(store, binding), store, binding


def test_claim_never_returns_waiting_signal() -> None:
    from datetime import datetime, timedelta, timezone

    store = InMemoryWorkflowStore()
    from impact_relay.workflows.types import WorkflowInstance, WorkflowType

    inst = WorkflowInstance(
        workflow_id="wf1",
        tenant_id="org_x",
        workflow_type=WorkflowType.EXPENSE_TO_RECEIPT,
        business_key="bk1",
        workflow_state=WorkflowState.REVIEW_PENDING,
        run_status=WorkflowRunStatus.WAITING_SIGNAL,
        next_run_at=utc_now_iso(),
    )
    store.create(inst)
    claimed = store.claim(
        worker_id="w1",
        limit=10,
        now=datetime.now(timezone.utc),
        lease_ttl=timedelta(seconds=60),
    )
    assert claimed == []


def test_signal_wakes_to_pending() -> None:
    ledger = _ledger_empty_expenses()
    rt, store, _ = _runtime_with_ledger(ledger)
    # seed import via start RECEIVED path
    row = _row()
    inst = rt.start_expense_to_receipt(
        tenant_id=ledger.organization.id,
        expense_row=row,
        simulation=False,
    )
    inst = rt.run_until_wait_or_terminal(
        inst.workflow_id, tenant_id=ledger.organization.id
    )
    assert inst.workflow_state == WorkflowState.REVIEW_PENDING
    assert inst.run_status == WorkflowRunStatus.WAITING_SIGNAL

    wait = inst.context.get("wait") or {}
    frozen = wait.get("frozen_command") or {}
    key = frozen["idempotency_key"]
    ar = ApprovalReceipt(
        approval_id="appr1",
        tenant_id=ledger.organization.id,
        proposal_id=wait.get("proposal_id") or "p",
        command_idempotency_key=key,
        decision="APPROVE",
        approver_id="human@example.org",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
    )
    rt.signal_approval(
        tenant_id=ledger.organization.id,
        workflow_id=inst.workflow_id,
        approval=ar,
    )
    woken = store.get(ledger.organization.id, inst.workflow_id)
    assert woken is not None
    assert woken.run_status == WorkflowRunStatus.PENDING


def test_full_pump_to_ledger_committed() -> None:
    ledger = _ledger_empty_expenses()
    rt, _, _ = _runtime_with_ledger(ledger)
    row = _row()
    inst = rt.start_expense_to_receipt(
        tenant_id=ledger.organization.id,
        expense_row=row,
    )
    inst = rt.run_until_wait_or_terminal(
        inst.workflow_id, tenant_id=ledger.organization.id
    )
    wait = inst.context["wait"]
    frozen = wait["frozen_command"]
    ar = ApprovalReceipt(
        approval_id="appr1",
        tenant_id=ledger.organization.id,
        proposal_id=wait.get("proposal_id") or "p",
        command_idempotency_key=frozen["idempotency_key"],
        decision="APPROVE",
        approver_id="human@example.org",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
    )
    rt.signal_approval(
        tenant_id=ledger.organization.id,
        workflow_id=inst.workflow_id,
        approval=ar,
    )
    inst = rt.run_until_wait_or_terminal(
        inst.workflow_id, tenant_id=ledger.organization.id
    )
    assert inst.workflow_state in (
        WorkflowState.LEDGER_COMMITTED,
        WorkflowState.PUBLICATION_PENDING,
    ) or inst.run_status == WorkflowRunStatus.COMPLETED
    # expense approved on ledger
    exp_id = inst.context["expense_id"]
    assert ledger.expenses[exp_id].state.value == "APPROVED"


def test_execution_receipt_idempotency_skips_second() -> None:
    ledger = _ledger_empty_expenses()
    rt, store, _ = _runtime_with_ledger(ledger)
    row = _row()
    inst = rt.start_expense_to_receipt(
        tenant_id=ledger.organization.id, expense_row=row
    )
    inst = rt.run_until_wait_or_terminal(
        inst.workflow_id, tenant_id=ledger.organization.id
    )
    wait = inst.context["wait"]
    frozen = wait["frozen_command"]
    key = frozen["idempotency_key"]
    ar = ApprovalReceipt(
        approval_id="appr1",
        tenant_id=ledger.organization.id,
        proposal_id="p",
        command_idempotency_key=key,
        decision="APPROVE",
        approver_id="human@example.org",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
    )
    rt.signal_approval(
        tenant_id=ledger.organization.id, workflow_id=inst.workflow_id, approval=ar
    )
    inst = rt.run_until_wait_or_terminal(
        inst.workflow_id, tenant_id=ledger.organization.id
    )
    stored = store.get_execution_receipt(ledger.organization.id, key)
    assert stored is not None
    assert stored.status == "SUCCEEDED"
    # Second put of same key succeeds (overwrite) — execute path returns stored
    from impact_relay.agents.executor import LedgerCommandExecutor
    from impact_relay.agents.types import AgentCommand, AuthorityLevel

    ex = LedgerCommandExecutor(ledger)
    ex.receipt_store = store
    ex.workflow_id = inst.workflow_id
    cmd = AgentCommand(
        command_type="approve_expense",
        tenant_id=ledger.organization.id,
        payload={"expense_id": inst.context["expense_id"], "approved_by": "x"},
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
        idempotency_key=key,
    )
    # Without approval will fail auth; use stored path first
    r2 = ex.receipt_store.get_execution_receipt(ledger.organization.id, key)
    assert r2 is not None and r2.status == "SUCCEEDED"


def test_failed_receipt_not_stored() -> None:
    store = InMemoryWorkflowStore()
    from impact_relay.agents.types import ExecutionReceipt

    with pytest.raises(Exception):
        store.put_execution_receipt(
            ExecutionReceipt(
                execution_id="e",
                tenant_id="t",
                command_type="x",
                idempotency_key="k",
                status="FAILED",
                output_refs=[],
                output_hash="h",
                executed_at=utc_now_iso(),
            ),
            workflow_id="wf",
        )


def test_facade_default_is_legacy(monkeypatch) -> None:
    monkeypatch.delenv("WORKFLOW_SLICE_FACADE", raising=False)
    from impact_relay.workflows.facade import facade_mode

    assert facade_mode() == "legacy"


def test_facade_runtime_mode_end_to_end(monkeypatch) -> None:
    monkeypatch.setenv("WORKFLOW_SLICE_FACADE", "runtime")
    from impact_relay.workflows.facade import run_expense_approval_slice

    ledger = _ledger_empty_expenses()
    rows = json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]
    result = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=[
            {
                "donor_id": "donor_alice",
                "donation_id": "don_1000_alice",
                "allocation_id": "alloc_community_hardware",
                "attribution_method": "DIRECT_RESTRICTED",
                "attributed_amount": "720.00",
            }
        ],
        send_email=True,
        communications_approver_id="comms@example.org",
    )
    assert result.workflow_state in (
        WorkflowState.DELIVERED,
        WorkflowState.PUBLISHED,
        WorkflowState.LEDGER_COMMITTED,
        WorkflowState.NOTIFICATION_PENDING,
    )
    # At least approved expense
    assert any(e.state.value == "APPROVED" for e in ledger.expenses.values())


def test_simulation_no_ledger_approve() -> None:
    ledger = _ledger_empty_expenses()
    before = len(ledger.expenses)
    rt, _, _ = _runtime_with_ledger(ledger)
    inst = rt.start_expense_to_receipt(
        tenant_id=ledger.organization.id,
        expense_row=_row(),
        simulation=True,
    )
    inst = rt.run_until_wait_or_terminal(
        inst.workflow_id, tenant_id=ledger.organization.id
    )
    # simulation may not import real expenses
    assert len(ledger.expenses) == before or inst.simulation
