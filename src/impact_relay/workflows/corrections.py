"""Correction / reverse / supersede workflow steps (PR-L1).

``workflow_type=correction``:

  RECEIVED → REVIEW_PENDING (WAIT L3 reverse|supersede)
    → LEDGER_COMMITTED → DELIVERED (COMPLETED)

Domain mutations only via LedgerCommandExecutor (K14/K15).
Behavioral oracle: tests/test_receipts_and_corrections.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from impact_relay.agents.types import (
    AgentCommand,
    AuthorityLevel,
    WorkflowState,
    to_jsonable,
)
from impact_relay.workflows.expense_to_receipt import freeze_command
from impact_relay.workflows.machine import assert_correction_transition
from impact_relay.workflows.types import (
    SignalType,
    StepResult,
    WorkflowEventType,
    WorkflowEventWrite,
    WorkflowRunStatus,
)

CorrectionKind = Literal["REVERSE", "SUPERSEDE"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _expires(hours: int = 72) -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)
    ).isoformat()


def _deadline(hours: int = 168) -> str:
    """Default 7-day human gate for corrections."""
    return (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)
    ).isoformat()


def build_reverse_command(
    *,
    tenant_id: str,
    expense_id: str,
    reason: str,
) -> AgentCommand:
    """Propose reverse_expense (L3 — approval required at execute)."""
    return AgentCommand(
        command_type="reverse_expense",
        tenant_id=tenant_id,
        payload={"expense_id": expense_id, "reason": reason},
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
        idempotency_key=f"reverse:{expense_id}:{reason[:48]}",
        expires_at=_expires(),
    )


def build_supersede_command(
    *,
    tenant_id: str,
    expense_id: str,
    reason: str,
    replacement: dict[str, Any],
    splits: list[Any],
) -> AgentCommand:
    return AgentCommand(
        command_type="supersede_expense",
        tenant_id=tenant_id,
        payload={
            "expense_id": expense_id,
            "reason": reason,
            "replacement": dict(replacement),
            "splits": list(splits),
        },
        required_authority=AuthorityLevel.L3_HUMAN_APPROVAL,
        idempotency_key=f"supersede:{expense_id}:{replacement.get('id') or replacement.get('expense_id') or 'new'}",
        expires_at=_expires(),
    )


def step_propose_correction(
    *,
    tenant_id: str,
    kind: CorrectionKind,
    expense_id: str,
    reason: str,
    replacement: dict[str, Any] | None = None,
    splits: list[Any] | None = None,
    current: WorkflowState = WorkflowState.RECEIVED,
) -> StepResult:
    """Build frozen L3 correction command and park at REVIEW_PENDING."""
    assert_correction_transition(current, WorkflowState.REVIEW_PENDING)

    if kind == "REVERSE":
        cmd = build_reverse_command(
            tenant_id=tenant_id, expense_id=expense_id, reason=reason
        )
    elif kind == "SUPERSEDE":
        if not replacement or not splits:
            return StepResult(
                next_state=WorkflowState.NEEDS_INFORMATION,
                run_status=WorkflowRunStatus.WAITING_SIGNAL,
                events=[
                    WorkflowEventWrite(
                        event_type=WorkflowEventType.ERROR,
                        payload={"error": "supersede_requires_replacement_and_splits"},
                    )
                ],
                retryable_error=None,
                terminal_reason=None,
                context_patch={"needs": "replacement_and_splits"},
            )
        cmd = build_supersede_command(
            tenant_id=tenant_id,
            expense_id=expense_id,
            reason=reason,
            replacement=replacement,
            splits=splits,
        )
    else:
        return StepResult(
            next_state=WorkflowState.BLOCKED,
            run_status=WorkflowRunStatus.FAILED_TERMINAL,
            events=[
                WorkflowEventWrite(
                    event_type=WorkflowEventType.ERROR,
                    payload={"error": f"unknown_correction_kind:{kind}"},
                )
            ],
            terminal_reason=f"unknown_correction_kind:{kind}",
        )

    proposal_id = _new_id("prop_corr")
    frozen = freeze_command(
        cmd, proposal_id=proposal_id, agent_name="CorrectionWorkflow"
    )
    wait = {
        "signal_type": SignalType.APPROVAL.value,
        "command_idempotency_key": cmd.idempotency_key,
        "proposal_id": proposal_id,
        "frozen_command": frozen.to_dict(),
        "correction_kind": kind,
        "expense_id": expense_id,
    }
    return StepResult(
        next_state=WorkflowState.REVIEW_PENDING,
        run_status=WorkflowRunStatus.WAITING_SIGNAL,
        events=[
            WorkflowEventWrite(
                event_type=WorkflowEventType.PROPOSAL,
                payload={
                    "proposal_id": proposal_id,
                    "command_type": cmd.command_type,
                    "expense_id": expense_id,
                    "kind": kind,
                },
            ),
            WorkflowEventWrite(
                event_type=WorkflowEventType.STATE_CHANGED,
                payload={"to": WorkflowState.REVIEW_PENDING.value},
            ),
        ],
        wait_for=SignalType.APPROVAL,
        wait_payload=wait,
        wait_deadline=_deadline(),
        context_patch={
            "wait": wait,
            "correction_kind": kind,
            "expense_id": expense_id,
            "reason": reason,
            "proposal_id": proposal_id,
            "replacement": to_jsonable(replacement) if replacement else None,
            "splits": to_jsonable(splits) if splits else None,
        },
    )


def step_after_ledger_correction(
    *,
    current: WorkflowState = WorkflowState.LEDGER_COMMITTED,
) -> StepResult:
    """Receipts already emitted by ledger reverse/supersede — complete."""
    assert_correction_transition(current, WorkflowState.DELIVERED)
    return StepResult(
        next_state=WorkflowState.DELIVERED,
        run_status=WorkflowRunStatus.COMPLETED,
        events=[
            WorkflowEventWrite(
                event_type=WorkflowEventType.STATE_CHANGED,
                payload={"to": WorkflowState.DELIVERED.value},
            )
        ],
    )
