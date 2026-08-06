"""Vertical slice: expense intake → human approval → ledger → UOF receipt."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from impact_relay.agents.authority import AuthorityError
from impact_relay.agents.expense_workflow import (
    EvidenceValidatorAgent,
    LedgerCommandExecutor,
    run_expense_approval_slice,
)
from impact_relay.agents.types import (
    AgentCommand,
    ApprovalReceipt,
    AuthorityLevel,
    EvidenceSufficiency,
    WorkflowState,
    utc_now_iso,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _ledger_without_expenses():
    data = load_fixture()
    data = copy.deepcopy(data)
    data["expenses"] = []
    data["publish"] = []
    return build_ledger_from_fixture(data)


def _batch_rows() -> list[dict]:
    return json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]


def test_full_slice_approve_and_publish() -> None:
    ledger = _ledger_without_expenses()
    rows = _batch_rows()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        simulation=False,
        publish_specs=[
            {
                "donor_id": "donor_alice",
                "donation_id": "don_1000_alice",
                "allocation_id": "alloc_community_hardware",
                "attribution_method": "DIRECT_RESTRICTED",
                "attributed_amount": "720.00",
                "created_at": "2026-08-12T12:00:00+00:00",
            }
        ],
    )
    assert result.workflow_state == WorkflowState.PUBLISHED
    assert len(result.receipts) == 1
    assert result.public_previews
    assert "donor_id" not in str(result.public_previews)
    # Expense approved in ledger
    exp = next(e for e in ledger.expenses.values() if e.external_source_id == "acct_exp_slice_9101")
    assert exp.state.value == "APPROVED"
    assert exp.approved_by == "finance.approver@hackersdojo.example"
    assert result.approvals
    assert all(not a.approver_id.startswith("agent:") for a in result.approvals)
    assert result.run_receipt.status.value in ("SUCCEEDED", "PARTIAL")


def test_slice_stops_at_review_without_approve() -> None:
    ledger = _ledger_without_expenses()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=False,
    )
    assert result.workflow_state == WorkflowState.REVIEW_PENDING
    assert result.packets
    assert result.packets[0].evidence_sufficiency == EvidenceSufficiency.SUFFICIENT.value
    # Imported + allocated but not approved
    exp = next(iter(ledger.expenses.values()))
    assert exp.state.value == "APPROVAL_PENDING"
    assert not result.approvals


def test_simulation_does_not_mutate_ledger() -> None:
    ledger = _ledger_without_expenses()
    before = len(ledger.expenses)
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        simulation=True,
    )
    assert len(ledger.expenses) == before
    assert result.run_receipt.status.value == "SIMULATED"
    assert all(e.simulated for e in result.executions)


def test_duplicate_import_is_idempotent() -> None:
    ledger = _ledger_without_expenses()
    rows = _batch_rows()
    r1 = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
    )
    count = len(ledger.expenses)
    r2 = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=False,
    )
    assert len(ledger.expenses) == count
    # Second intake should skip duplicate external ids
    import_execs = [e for e in r2.executions if e.command_type == "import_normalized_expense"]
    assert any(e.status == "SKIPPED" for e in import_execs) or count == 1
    assert r1.workflow_state in (WorkflowState.LEDGER_COMMITTED, WorkflowState.PUBLISHED)


def test_contradictory_evidence_blocks() -> None:
    ledger = _ledger_without_expenses()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_batch_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        evidence_flags={"contradictory": True},
    )
    assert result.workflow_state == WorkflowState.BLOCKED
    assert result.packets
    assert result.packets[0].evidence_sufficiency == EvidenceSufficiency.CONTRADICTORY.value


def test_missing_evidence_marked() -> None:
    agent = EvidenceValidatorAgent()
    assert agent.assess([]) == EvidenceSufficiency.MISSING
    assert agent.assess([{"kind": "note"}]) == EvidenceSufficiency.PARTIAL
    assert (
        agent.assess([{"kind": "invoice", "donor_visible": True}]) == EvidenceSufficiency.SUFFICIENT
    )


def test_approve_without_human_receipt_fails() -> None:
    ledger = _ledger_without_expenses()
    # Import one expense manually via executor L2
    ex = LedgerCommandExecutor(ledger, simulation=False)
    row = _batch_rows()[0]
    from impact_relay.agents.expense_workflow import normalize_expense_row
    from impact_relay.agents.types import to_jsonable

    n = normalize_expense_row(row, tenant_id=ledger.organization.id)
    cmd = AgentCommand(
        command_type="import_normalized_expense",
        tenant_id=ledger.organization.id,
        payload={"expense": to_jsonable(n)},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
    )
    ex.execute(cmd)
    expense_id = next(iter(ledger.expenses))
    ex.execute(
        AgentCommand(
            command_type="allocate_expense",
            tenant_id=ledger.organization.id,
            payload={
                "expense_id": expense_id,
                "allocation_id": "alloc_community_hardware",
                "amount": "720.00",
            },
            required_authority=AuthorityLevel.L2_REVERSIBLE,
        )
    )
    with pytest.raises(AuthorityError):
        ex.execute(
            AgentCommand(
                command_type="approve_expense",
                tenant_id=ledger.organization.id,
                payload={"expense_id": expense_id, "approved_by": "x"},
                required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
            )
        )


def test_rejection_decision_does_not_approve() -> None:
    ledger = _ledger_without_expenses()
    ex = LedgerCommandExecutor(ledger, simulation=False)
    row = _batch_rows()[0]
    from impact_relay.agents.expense_workflow import normalize_expense_row
    from impact_relay.agents.types import to_jsonable

    n = normalize_expense_row(row, tenant_id=ledger.organization.id)
    import_cmd = AgentCommand(
        command_type="import_normalized_expense",
        tenant_id=ledger.organization.id,
        payload={"expense": to_jsonable(n)},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
    )
    ex.execute(import_cmd)
    expense_id = next(iter(ledger.expenses))
    ex.execute(
        AgentCommand(
            command_type="allocate_expense",
            tenant_id=ledger.organization.id,
            payload={
                "expense_id": expense_id,
                "allocation_id": "alloc_community_hardware",
                "amount": "720.00",
            },
            required_authority=AuthorityLevel.L2_REVERSIBLE,
        )
    )
    approve_cmd = AgentCommand(
        command_type="approve_expense",
        tenant_id=ledger.organization.id,
        payload={"expense_id": expense_id, "approved_by": "human@x"},
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
    )
    with pytest.raises(AuthorityError, match="not APPROVE"):
        ex.execute(
            approve_cmd,
            approval=ApprovalReceipt(
                approval_id="a",
                tenant_id=ledger.organization.id,
                proposal_id="p",
                command_idempotency_key=approve_cmd.idempotency_key,
                decision="REJECT",
                approver_id="human@x",
                approver_role="finance_approver",
                approved_at=utc_now_iso(),
            ),
        )
    assert ledger.expenses[expense_id].state.value == "APPROVAL_PENDING"


def test_agent_approver_id_rejected_in_slice() -> None:
    ledger = _ledger_without_expenses()
    with pytest.raises(AuthorityError, match="must not be an agent"):
        run_expense_approval_slice(
            ledger,
            expense_rows=_batch_rows(),
            human_approver_id="agent:finance_review",
            approve=True,
        )
