"""PR-L1: correction workflow + L3 reverse_expense / supersede_expense (K15)."""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest

from impact_relay.agents.authority import AuthorityError, requires_human_approval
from impact_relay.agents.executor import LedgerCommandExecutor
from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.agents.types import (
    AgentCommand,
    ApprovalReceipt,
    AuthorityLevel,
    L3_COMMAND_TYPES,
    WorkflowState,
    utc_now_iso,
)
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import ExpenseState
from impact_relay.pilot import build_ledger_from_fixture, load_fixture, run_pilot
from impact_relay.workflows.ops import signal_approval_and_pump
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.store_memory import InMemoryWorkflowStore
from impact_relay.workflows.types import WorkflowRunStatus, WorkflowType
from impact_relay.workflows.worker import WorkerConfig, WorkflowWorker


ROOT = Path(__file__).resolve().parents[1]


def _rt_from_pilot():
    ledger, receipts = run_pilot()
    store = InMemoryWorkflowStore()
    binding = InMemoryLedgerBinding()
    binding.register(ledger, TenantWorkspace(ledger.organization, ledger=ledger))
    return WorkflowRuntime(store, binding), store, ledger, receipts


def test_k15_reverse_and_supersede_are_l3() -> None:
    assert "reverse_expense" in L3_COMMAND_TYPES
    assert "supersede_expense" in L3_COMMAND_TYPES
    for ct in ("reverse_expense", "supersede_expense"):
        cmd = AgentCommand(
            command_type=ct,
            tenant_id="org_hacker_dojo",
            payload={"expense_id": "exp_1", "reason": "x"},
        )
        assert cmd.required_authority == AuthorityLevel.L3_HUMAN_APPROVAL
        assert requires_human_approval(cmd)


def test_reverse_expense_requires_approval_receipt() -> None:
    ledger, _ = run_pilot()
    ex = LedgerCommandExecutor(
        ledger, workspace=TenantWorkspace(ledger.organization, ledger=ledger)
    )
    cmd = AgentCommand(
        command_type="reverse_expense",
        tenant_id=ledger.organization.id,
        payload={
            "expense_id": "exp_soldering_842",
            "reason": "void",
            "actor": "should_not_matter_without_approval",
        },
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
        idempotency_key="reverse:exp_soldering_842:void",
    )
    with pytest.raises(AuthorityError, match="requires human"):
        ex.execute(cmd)


def test_executor_reverse_matches_ledger_oracle() -> None:
    ledger, receipts = run_pilot()
    prior = receipts[0]
    prior_hash = prior.receipt_hash
    ex = LedgerCommandExecutor(
        ledger, workspace=TenantWorkspace(ledger.organization, ledger=ledger)
    )
    cmd = AgentCommand(
        command_type="reverse_expense",
        tenant_id=ledger.organization.id,
        payload={
            "expense_id": "exp_soldering_842",
            "reason": "Invoice voided by vendor",
            "actor": "finance.operator@hackersdojo.example",
        },
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
        idempotency_key="reverse:exp_soldering_842:Invoice voided by vendor",
    )
    approval = ApprovalReceipt(
        approval_id="ap_rev_1",
        tenant_id=ledger.organization.id,
        proposal_id="prop_x",
        command_idempotency_key=cmd.idempotency_key,
        decision="APPROVE",
        approver_id="finance.operator@hackersdojo.example",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
        rationale="vendor void",
    )
    receipt = ex.execute(cmd, approval=approval)
    assert receipt.status == "SUCCEEDED"
    assert ledger.expenses["exp_soldering_842"].state == ExpenseState.REVERSED
    still = ledger.get_receipt(prior.receipt_id)
    assert still.receipt_hash == prior_hash
    assert any(r.corrected for r in ledger.receipts.values())


def test_executor_supersede_matches_ledger_oracle() -> None:
    ledger, receipts = run_pilot()
    prior = receipts[0]
    ex = LedgerCommandExecutor(
        ledger, workspace=TenantWorkspace(ledger.organization, ledger=ledger)
    )
    cmd = AgentCommand(
        command_type="supersede_expense",
        tenant_id=ledger.organization.id,
        payload={
            "expense_id": "exp_soldering_842",
            "reason": "Amount corrected after rebate",
            "actor": "finance.operator@hackersdojo.example",
            "approved_by": "finance.operator@hackersdojo.example",
            "replacement": {
                "id": "exp_soldering_corrected",
                "vendor": "Example Vendor LLC",
                "amount": "800.00",
                "currency": "USD",
                "purchase_date": "2026-08-18",
                "category": "CLASSROOM_HARDWARE",
                "description": "Corrected soldering stations invoice",
                "external_source_id": "acct_exp_9001b",
            },
            "splits": [{"allocation_id": "alloc_community_hardware", "amount": "800.00"}],
        },
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
        idempotency_key="supersede:exp_soldering_842:exp_soldering_corrected",
    )
    approval = ApprovalReceipt(
        approval_id="ap_sup_1",
        tenant_id=ledger.organization.id,
        proposal_id="prop_s",
        command_idempotency_key=cmd.idempotency_key,
        decision="APPROVE",
        approver_id="finance.operator@hackersdojo.example",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
        rationale="rebate",
    )
    receipt = ex.execute(cmd, approval=approval)
    assert receipt.status == "SUCCEEDED"
    assert ledger.expenses["exp_soldering_842"].state == ExpenseState.SUPERSEDED
    assert ledger.expenses["exp_soldering_corrected"].state == ExpenseState.APPROVED
    assert ledger.get_receipt(prior.receipt_id).receipt_hash == prior.receipt_hash


def test_correction_workflow_reverse_pause_resume() -> None:
    rt, store, ledger, receipts = _rt_from_pilot()
    prior = receipts[0]
    prior_hash = prior.receipt_hash
    tenant = ledger.organization.id

    inst = rt.start_correction(
        tenant_id=tenant,
        expense_id="exp_soldering_842",
        kind="REVERSE",
        reason="Invoice voided by vendor",
    )
    assert inst.workflow_type == WorkflowType.CORRECTION

    worker = WorkflowWorker(rt, WorkerConfig(worker_id="corr-w", poll_interval_seconds=0.0))
    for _ in range(5):
        worker.tick()
        cur = store.get(tenant, inst.workflow_id)
        if cur and cur.run_status == WorkflowRunStatus.WAITING_SIGNAL:
            break
    cur = store.get(tenant, inst.workflow_id)
    assert cur is not None
    assert cur.workflow_state == WorkflowState.REVIEW_PENDING
    assert cur.run_status == WorkflowRunStatus.WAITING_SIGNAL
    wait = cur.context["wait"]
    key = wait["command_idempotency_key"]
    assert wait["frozen_command"]["command_type"] == "reverse_expense"

    # Agent approver rejected
    with pytest.raises(AuthorityError):
        rt.signal_approval(
            tenant_id=tenant,
            workflow_id=inst.workflow_id,
            approval=ApprovalReceipt(
                approval_id="bad",
                tenant_id=tenant,
                proposal_id="p",
                command_idempotency_key=key,
                decision="APPROVE",
                approver_id="agent:bot",
                approver_role="finance_approver",
                approved_at=utc_now_iso(),
                rationale="nope",
            ),
        )

    approval = ApprovalReceipt(
        approval_id="ap_wf_rev",
        tenant_id=tenant,
        proposal_id=wait.get("proposal_id") or "p",
        command_idempotency_key=key,
        decision="APPROVE",
        approver_id="finance.approver@hackersdojo.example",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
        rationale="void confirmed",
    )
    updated = signal_approval_and_pump(
        rt, tenant_id=tenant, workflow_id=inst.workflow_id, approval=approval
    )
    assert updated is not None
    assert updated.run_status == WorkflowRunStatus.COMPLETED
    assert updated.workflow_state == WorkflowState.DELIVERED
    assert ledger.expenses["exp_soldering_842"].state == ExpenseState.REVERSED
    assert ledger.get_receipt(prior.receipt_id).receipt_hash == prior_hash


def test_correction_workflow_supersede() -> None:
    rt, store, ledger, receipts = _rt_from_pilot()
    tenant = ledger.organization.id
    inst = rt.start_correction(
        tenant_id=tenant,
        expense_id="exp_soldering_842",
        kind="SUPERSEDE",
        reason="Amount corrected after rebate",
        replacement={
            "id": "exp_soldering_corrected",
            "vendor": "Example Vendor LLC",
            "amount": "800.00",
            "currency": "USD",
            "purchase_date": "2026-08-18",
            "category": "CLASSROOM_HARDWARE",
            "description": "Corrected soldering stations invoice",
            "external_source_id": "acct_exp_9001b",
        },
        splits=[{"allocation_id": "alloc_community_hardware", "amount": "800.00"}],
    )
    worker = WorkflowWorker(rt, WorkerConfig(worker_id="corr-s", poll_interval_seconds=0.0))
    for _ in range(5):
        worker.tick()
        cur = store.get(tenant, inst.workflow_id)
        if cur and cur.run_status == WorkflowRunStatus.WAITING_SIGNAL:
            break
    cur = store.get(tenant, inst.workflow_id)
    assert cur is not None
    key = cur.context["wait"]["command_idempotency_key"]
    approval = ApprovalReceipt(
        approval_id="ap_wf_sup",
        tenant_id=tenant,
        proposal_id="p",
        command_idempotency_key=key,
        decision="APPROVE",
        approver_id="finance.approver@hackersdojo.example",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
        rationale="rebate",
    )
    updated = signal_approval_and_pump(
        rt, tenant_id=tenant, workflow_id=inst.workflow_id, approval=approval
    )
    assert updated is not None
    assert updated.run_status == WorkflowRunStatus.COMPLETED
    assert ledger.expenses["exp_soldering_842"].state == ExpenseState.SUPERSEDED
    assert ledger.expenses["exp_soldering_corrected"].state == ExpenseState.APPROVED
    assert ledger.expenses["exp_soldering_corrected"].amount == Decimal("800.00")


def test_reverse_without_l3_cannot_be_disguised_as_l2() -> None:
    """K15: even if caller asks for L2, reverse_expense is forced to L3."""
    cmd = AgentCommand(
        command_type="reverse_expense",
        tenant_id="org_hacker_dojo",
        payload={"expense_id": "e", "reason": "x"},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
    )
    assert cmd.required_authority == AuthorityLevel.L3_HUMAN_APPROVAL
