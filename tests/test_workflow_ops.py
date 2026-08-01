"""PR-M5: operator listing, signal CLI helpers, session round-trip."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from impact_relay.agents.types import WorkflowState
from impact_relay.cli import main
from impact_relay.workflows.ops import (
    approval_from_dict,
    list_operator_cases,
    load_ops_session,
    save_ops_session,
    seed_session_to_wait,
    signal_approval_and_pump,
)
from impact_relay.workflows.runtime import WorkflowRuntime
from impact_relay.workflows.types import WorkflowRunStatus


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _rows():
    return json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]


def test_seed_lists_waiting_cases() -> None:
    runtime, store, binding, tenant_id, ids = seed_session_to_wait(
        expense_rows=_rows()
    )
    assert ids
    cases = list_operator_cases(store, tenant_id, filters=("waiting",))
    assert cases
    assert all(c.bucket == "waiting" for c in cases)
    assert cases[0].command_idempotency_key
    assert cases[0].workflow_state == WorkflowState.REVIEW_PENDING.value


def test_signal_and_pump_approves_expense() -> None:
    runtime, store, binding, tenant_id, ids = seed_session_to_wait(
        expense_rows=_rows()
    )
    wid = ids[0]
    inst = store.get(tenant_id, wid)
    assert inst is not None
    key = inst.context["wait"]["frozen_command"]["idempotency_key"]
    approval = approval_from_dict(
        {
            "tenant_id": tenant_id,
            "command_idempotency_key": key,
            "decision": "APPROVE",
            "approver_id": "ops@hackersdojo.example",
        },
        tenant_id=tenant_id,
    )
    updated = signal_approval_and_pump(
        runtime, tenant_id=tenant_id, workflow_id=wid, approval=approval
    )
    assert updated.workflow_state in (
        WorkflowState.LEDGER_COMMITTED,
        WorkflowState.PUBLICATION_PENDING,
        WorkflowState.PUBLISHED,
        WorkflowState.DELIVERED,
    )
    exp_id = updated.context["expense_id"]
    ledger = binding.for_tenant(tenant_id)
    assert ledger.expenses[exp_id].state.value == "APPROVED"


def test_session_roundtrip(tmp_path: Path) -> None:
    runtime, store, binding, tenant_id, ids = seed_session_to_wait(
        expense_rows=_rows()
    )
    path = tmp_path / "sess.pkl"
    save_ops_session(path, store, binding, tenant_id=tenant_id)
    store2, binding2, tid2 = load_ops_session(path)
    assert tid2 == tenant_id
    cases = list_operator_cases(store2, tid2, filters=("waiting",))
    assert any(c.workflow_id == ids[0] for c in cases)


def test_cli_ops_seed_list_signal(tmp_path: Path) -> None:
    sess = tmp_path / "cli-sess.pkl"
    code = main(
        [
            "--workflow-ops",
            "seed",
            "--workflow-session",
            str(sess),
            "--expense-batch",
            str(BATCH),
        ]
    )
    assert code == 0
    assert sess.is_file()

    # list
    code = main(
        [
            "--workflow-ops",
            "list",
            "--workflow-session",
            str(sess),
            "--workflow-filter",
            "waiting",
        ]
    )
    assert code == 0

    store, binding, tenant_id = load_ops_session(sess)
    cases = list_operator_cases(store, tenant_id, filters=("waiting",))
    assert cases
    wid = cases[0].workflow_id
    key = cases[0].command_idempotency_key
    assert key

    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "command_idempotency_key": key,
                "decision": "APPROVE",
                "approver_id": "cli.ops@example.org",
                "approver_role": "finance_approver",
            }
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "--workflow-ops",
            "signal",
            "--workflow-session",
            str(sess),
            "--workflow-id",
            wid,
            "--approval-json",
            str(approval_path),
        ]
    )
    assert code == 0
    store2, binding2, _ = load_ops_session(sess)
    inst = store2.get(tenant_id, wid)
    assert inst is not None
    assert inst.workflow_state != WorkflowState.REVIEW_PENDING or inst.run_status != WorkflowRunStatus.WAITING_SIGNAL
    # Should have advanced past pure review wait
    assert inst.workflow_state in (
        WorkflowState.LEDGER_COMMITTED,
        WorkflowState.PUBLICATION_PENDING,
        WorkflowState.PUBLISHED,
        WorkflowState.DELIVERED,
        WorkflowState.NEEDS_INFORMATION,
    ) or inst.run_status == WorkflowRunStatus.COMPLETED


def test_cli_ops_demo(tmp_path: Path) -> None:
    sess = tmp_path / "demo.pkl"
    code = main(
        [
            "--workflow-ops",
            "demo",
            "--workflow-session",
            str(sess),
            "--expense-batch",
            str(BATCH),
            "--approver-id",
            "demo.human@example.org",
        ]
    )
    assert code == 0
    store, binding, tenant_id = load_ops_session(sess)
    # After demo approve, waiting should be empty or at next gate
    ledger = binding.for_tenant(tenant_id)
    assert any(e.state.value == "APPROVED" for e in ledger.expenses.values())


def test_rejects_agent_approver_in_demo_path() -> None:
    from impact_relay.agents.authority import AuthorityError
    import pytest

    runtime, store, binding, tenant_id, ids = seed_session_to_wait(
        expense_rows=_rows()
    )
    inst = store.get(tenant_id, ids[0])
    key = inst.context["wait"]["frozen_command"]["idempotency_key"]
    with pytest.raises(AuthorityError):
        signal_approval_and_pump(
            runtime,
            tenant_id=tenant_id,
            workflow_id=ids[0],
            approval=approval_from_dict(
                {
                    "tenant_id": tenant_id,
                    "command_idempotency_key": key,
                    "decision": "APPROVE",
                    "approver_id": "agent:finance_review",
                }
            ),
        )
