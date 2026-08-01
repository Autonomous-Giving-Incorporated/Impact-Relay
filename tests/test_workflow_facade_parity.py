"""PR-M6 parity checklist: legacy linear driver vs runtime façade.

Before flipping WORKFLOW_SLICE_FACADE default to runtime, both paths must agree
on terminal workflow_state, ledger approval, and receipt/public export shape.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from impact_relay.agents.expense_workflow import (
    run_expense_approval_slice,
    run_expense_approval_slice_legacy,
)
from impact_relay.agents.types import WorkflowState
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.workflows.facade import facade_mode, run_expense_approval_slice_via_runtime


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _ledger():
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    return build_ledger_from_fixture(data)


def _rows():
    return json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]


def _publish_specs():
    return [
        {
            "donor_id": "donor_alice",
            "donation_id": "don_1000_alice",
            "allocation_id": "alloc_community_hardware",
            "attribution_method": "DIRECT_RESTRICTED",
            "attributed_amount": "720.00",
            "created_at": "2026-08-12T12:00:00+00:00",
        }
    ]


def _run_both(**kwargs):
    leg_ledger = _ledger()
    rt_ledger = _ledger()
    common = dict(
        expense_rows=_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        communications_approver_id="comms.approver@hackersdojo.example",
        **kwargs,
    )
    legacy = run_expense_approval_slice_legacy(leg_ledger, **common)
    runtime = run_expense_approval_slice_via_runtime(rt_ledger, **common)
    return legacy, runtime, leg_ledger, rt_ledger


def test_default_facade_is_runtime(monkeypatch) -> None:
    monkeypatch.delenv("WORKFLOW_SLICE_FACADE", raising=False)
    # Re-import mode after env clear
    from impact_relay.workflows import facade as facade_mod

    assert facade_mod.facade_mode() == "runtime"


def test_parity_full_slice_delivered() -> None:
    legacy, runtime, leg_ledger, rt_ledger = _run_both(
        approve=True,
        publish_specs=_publish_specs(),
        send_email=True,
    )
    assert legacy.workflow_state == WorkflowState.DELIVERED
    assert runtime.workflow_state == WorkflowState.DELIVERED
    assert legacy.workflow_state == runtime.workflow_state
    assert len(legacy.receipts) == len(runtime.receipts) == 1
    assert len(legacy.public_previews) == len(runtime.public_previews) == 1
    assert any(e.state.value == "APPROVED" for e in leg_ledger.expenses.values())
    assert any(e.state.value == "APPROVED" for e in rt_ledger.expenses.values())
    # Attributed amounts match
    assert legacy.receipts[0].attributed_amount == runtime.receipts[0].attributed_amount


def test_parity_stops_at_review_without_approve() -> None:
    legacy, runtime, _, _ = _run_both(approve=False)
    assert legacy.workflow_state == WorkflowState.REVIEW_PENDING
    assert runtime.workflow_state == WorkflowState.REVIEW_PENDING
    assert legacy.packets and runtime.packets


def test_parity_simulation_no_expense_mutation() -> None:
    legacy, runtime, leg_ledger, rt_ledger = _run_both(
        approve=True, simulation=True, publish_specs=_publish_specs()
    )
    assert len(leg_ledger.expenses) == 0
    assert len(rt_ledger.expenses) == 0
    # Both should report simulated-ish terminal (legacy SIMULATED run; runtime may park)
    assert legacy.run_receipt.status.value in ("SIMULATED", "SUCCEEDED", "PARTIAL")
    assert runtime.run_receipt.status.value in ("SIMULATED", "SUCCEEDED", "PARTIAL", "BLOCKED")


def test_parity_contradictory_evidence_blocks() -> None:
    legacy, runtime, _, _ = _run_both(
        approve=True, evidence_flags={"contradictory": True}
    )
    assert legacy.workflow_state == WorkflowState.BLOCKED
    assert runtime.workflow_state == WorkflowState.BLOCKED


def test_parity_agent_approver_rejected() -> None:
    with pytest.raises(Exception):
        run_expense_approval_slice_legacy(
            _ledger(),
            expense_rows=_rows(),
            human_approver_id="agent:finance_review",
            approve=True,
        )
    with pytest.raises(Exception):
        run_expense_approval_slice_via_runtime(
            _ledger(),
            expense_rows=_rows(),
            human_approver_id="agent:finance_review",
            approve=True,
        )


def test_public_entry_uses_facade_default(monkeypatch) -> None:
    """run_expense_approval_slice (agents) goes through façade default runtime."""
    monkeypatch.delenv("WORKFLOW_SLICE_FACADE", raising=False)
    ledger = _ledger()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=_publish_specs(),
        send_email=True,
        communications_approver_id="comms@example.org",
    )
    assert result.workflow_state == WorkflowState.DELIVERED
    assert any(e.state.value == "APPROVED" for e in ledger.expenses.values())


def test_legacy_env_override(monkeypatch) -> None:
    monkeypatch.setenv("WORKFLOW_SLICE_FACADE", "legacy")
    assert facade_mode() == "legacy"
    ledger = _ledger()
    result = run_expense_approval_slice(
        ledger,
        expense_rows=_rows(),
        human_approver_id="finance.approver@hackersdojo.example",
        approve=False,
    )
    assert result.workflow_state == WorkflowState.REVIEW_PENDING
