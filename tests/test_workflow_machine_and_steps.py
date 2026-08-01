"""PR-M2: state machine transitions and step handlers."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from impact_relay.agents.base import AgentContext
from impact_relay.agents.types import WorkflowState
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.workflows.expense_to_receipt import (
    HandlerBundle,
    step_classify,
    step_evidence,
    step_intake,
    step_review,
)
from impact_relay.workflows.machine import (
    assert_transition,
    can_transition,
    is_human_gate,
)
from impact_relay.workflows.types import WorkflowRunStatus


ROOT = Path(__file__).resolve().parents[1]


def test_evidence_before_classify_transitions() -> None:
    assert can_transition(WorkflowState.NORMALIZED, WorkflowState.EVIDENCE_PENDING)
    assert can_transition(
        WorkflowState.EVIDENCE_PENDING, WorkflowState.CLASSIFICATION_PENDING
    )
    assert can_transition(
        WorkflowState.CLASSIFICATION_PENDING, WorkflowState.REVIEW_PENDING
    )
    assert is_human_gate(WorkflowState.REVIEW_PENDING)
    assert not can_transition(WorkflowState.DELIVERED, WorkflowState.RECEIVED)


def test_illegal_transition_raises() -> None:
    from impact_relay.workflows.exceptions import WorkflowStateError
    import pytest

    with pytest.raises(WorkflowStateError):
        assert_transition(WorkflowState.DELIVERED, WorkflowState.RECEIVED)


def test_step_intake_emits_import_commands() -> None:
    ctx = AgentContext(tenant_id="org_hacker_dojo", policy_version="v1.0")
    rows = json.loads(
        (ROOT / "fixtures" / "expense_intake_batch_v1.json").read_text(encoding="utf-8")
    )["expenses"]
    out = step_intake(ctx, rows)
    assert out.step.next_state == WorkflowState.NORMALIZED
    assert out.step.commands_to_execute
    assert (
        out.step.commands_to_execute[0].command.command_type
        == "import_normalized_expense"
    )


def test_step_evidence_sufficient_path() -> None:
    ctx = AgentContext(tenant_id="org_hacker_dojo", policy_version="v1.0")
    out = step_evidence(
        ctx,
        expense_id="exp_1",
        evidence_items=[
            {"id": "ev1", "kind": "invoice", "summary": "inv", "donor_visible": True}
        ],
        current=WorkflowState.NORMALIZED,
    )
    assert out.step.next_state == WorkflowState.CLASSIFICATION_PENDING
    assert out.sufficiency is not None


def test_step_evidence_contradictory_blocks() -> None:
    ctx = AgentContext(tenant_id="org_hacker_dojo", policy_version="v1.0")
    out = step_evidence(
        ctx,
        expense_id="exp_1",
        evidence_items=[{"kind": "invoice", "donor_visible": True}],
        evidence_flags={"contradictory": True},
        current=WorkflowState.NORMALIZED,
    )
    assert out.step.next_state == WorkflowState.BLOCKED


def test_step_review_parks_waiting_signal() -> None:
    ctx = AgentContext(tenant_id="org_hacker_dojo", policy_version="v1.0")
    out = step_review(
        ctx,
        expense_id="exp_1",
        vendor="V",
        amount="10.00",
        currency="USD",
        purchase_date="2026-08-01",
        category="HW",
        description="kit",
        allocation_id="alloc_1",
        evidence_sufficiency="SUFFICIENT",
        evidence_summaries=["ok"],
        confidence=0.9,
        warnings=[],
        contradictions=[],
        current=WorkflowState.CLASSIFICATION_PENDING,
    )
    assert out.step.next_state == WorkflowState.REVIEW_PENDING
    assert out.step.run_status == WorkflowRunStatus.WAITING_SIGNAL
    assert out.step.wait_for is not None
    assert "frozen_command" in out.step.wait_payload
    assert out.packet is not None


def test_full_slice_still_works_after_handler_extract() -> None:
    from impact_relay.agents.expense_workflow import run_expense_approval_slice

    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    rows = json.loads(
        (ROOT / "fixtures" / "expense_intake_batch_v1.json").read_text(encoding="utf-8")
    )["expenses"]
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
        communications_approver_id="comms.approver@hackersdojo.example",
    )
    assert result.workflow_state == WorkflowState.DELIVERED
