"""Workflow state machine transitions (PR-M2).

Business cursor uses ``WorkflowState`` from agents.types.
Scheduler axis ``WorkflowRunStatus`` is validated separately.
"""

from __future__ import annotations

from impact_relay.agents.types import WorkflowState
from impact_relay.workflows.exceptions import WorkflowStateError
from impact_relay.workflows.types import WorkflowRunStatus

# Allowed business-state edges for expense_to_receipt (evidence before classify).
EXPENSE_TO_RECEIPT_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.RECEIVED: frozenset(
        {WorkflowState.NORMALIZED, WorkflowState.BLOCKED, WorkflowState.DUPLICATE}
    ),
    WorkflowState.NORMALIZED: frozenset(
        {
            WorkflowState.EVIDENCE_PENDING,
            WorkflowState.DUPLICATE,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.EVIDENCE_PENDING: frozenset(
        {
            WorkflowState.CLASSIFICATION_PENDING,
            WorkflowState.BLOCKED,
            WorkflowState.NEEDS_INFORMATION,
        }
    ),
    WorkflowState.CLASSIFICATION_PENDING: frozenset(
        {
            WorkflowState.REVIEW_PENDING,
            WorkflowState.NEEDS_INFORMATION,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.REVIEW_PENDING: frozenset(
        {
            WorkflowState.LEDGER_COMMITTED,
            WorkflowState.REJECTED,
            WorkflowState.NEEDS_INFORMATION,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.LEDGER_COMMITTED: frozenset(
        {
            WorkflowState.PUBLICATION_PENDING,
            WorkflowState.RECEIPT_DRAFTED,
            WorkflowState.PUBLISHED,  # collapse publish
        }
    ),
    WorkflowState.RECEIPT_DRAFTED: frozenset(
        {WorkflowState.PUBLICATION_PENDING, WorkflowState.PUBLISHED}
    ),
    WorkflowState.PUBLICATION_PENDING: frozenset(
        {
            WorkflowState.PUBLISHED,
            WorkflowState.REJECTED,
            WorkflowState.NEEDS_INFORMATION,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.PUBLISHED: frozenset(
        {WorkflowState.NOTIFICATION_PENDING, WorkflowState.DELIVERED}
    ),
    WorkflowState.NOTIFICATION_PENDING: frozenset(
        {
            WorkflowState.DELIVERED,
            WorkflowState.NEEDS_INFORMATION,
            WorkflowState.BLOCKED,
            WorkflowState.REJECTED,
        }
    ),
    WorkflowState.DELIVERED: frozenset(),
    WorkflowState.BLOCKED: frozenset(
        {WorkflowState.EVIDENCE_PENDING, WorkflowState.REVIEW_PENDING, WorkflowState.NEEDS_INFORMATION}
    ),
    WorkflowState.NEEDS_INFORMATION: frozenset(
        {
            WorkflowState.EVIDENCE_PENDING,
            WorkflowState.CLASSIFICATION_PENDING,
            WorkflowState.REVIEW_PENDING,
            WorkflowState.PUBLICATION_PENDING,
            WorkflowState.NOTIFICATION_PENDING,
        }
    ),
    WorkflowState.REJECTED: frozenset(),
    WorkflowState.DUPLICATE: frozenset(),
    # APPROVED is audit-only (K12); not a parked cursor for transitions from handlers
    WorkflowState.APPROVED: frozenset(
        {WorkflowState.LEDGER_COMMITTED, WorkflowState.REJECTED}
    ),
}

# Correction workflow (PR-L1): reuse business states; separate transition table.
CORRECTION_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.RECEIVED: frozenset(
        {
            WorkflowState.REVIEW_PENDING,
            WorkflowState.BLOCKED,
            WorkflowState.NEEDS_INFORMATION,
        }
    ),
    WorkflowState.REVIEW_PENDING: frozenset(
        {
            WorkflowState.LEDGER_COMMITTED,
            WorkflowState.REJECTED,
            WorkflowState.NEEDS_INFORMATION,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.LEDGER_COMMITTED: frozenset({WorkflowState.DELIVERED}),
    WorkflowState.DELIVERED: frozenset(),
    WorkflowState.BLOCKED: frozenset(
        {WorkflowState.RECEIVED, WorkflowState.REVIEW_PENDING, WorkflowState.NEEDS_INFORMATION}
    ),
    WorkflowState.NEEDS_INFORMATION: frozenset(
        {WorkflowState.RECEIVED, WorkflowState.REVIEW_PENDING}
    ),
    WorkflowState.REJECTED: frozenset(),
}


HUMAN_GATE_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.REVIEW_PENDING,
        WorkflowState.PUBLICATION_PENDING,
        WorkflowState.NOTIFICATION_PENDING,
    }
)

# Typical run_status for a business state when entering it.
DEFAULT_RUN_STATUS: dict[WorkflowState, WorkflowRunStatus] = {
    WorkflowState.RECEIVED: WorkflowRunStatus.PENDING,
    WorkflowState.NORMALIZED: WorkflowRunStatus.PENDING,
    WorkflowState.EVIDENCE_PENDING: WorkflowRunStatus.PENDING,
    WorkflowState.CLASSIFICATION_PENDING: WorkflowRunStatus.PENDING,
    WorkflowState.REVIEW_PENDING: WorkflowRunStatus.WAITING_SIGNAL,
    WorkflowState.LEDGER_COMMITTED: WorkflowRunStatus.PENDING,
    WorkflowState.RECEIPT_DRAFTED: WorkflowRunStatus.PENDING,
    WorkflowState.PUBLICATION_PENDING: WorkflowRunStatus.WAITING_SIGNAL,
    WorkflowState.PUBLISHED: WorkflowRunStatus.PENDING,
    WorkflowState.NOTIFICATION_PENDING: WorkflowRunStatus.WAITING_SIGNAL,
    WorkflowState.DELIVERED: WorkflowRunStatus.COMPLETED,
    WorkflowState.BLOCKED: WorkflowRunStatus.WAITING_SIGNAL,
    WorkflowState.NEEDS_INFORMATION: WorkflowRunStatus.WAITING_SIGNAL,
    WorkflowState.REJECTED: WorkflowRunStatus.FAILED_TERMINAL,
    WorkflowState.DUPLICATE: WorkflowRunStatus.COMPLETED,
    WorkflowState.APPROVED: WorkflowRunStatus.RUNNING,
}


def can_transition(
    current: WorkflowState,
    nxt: WorkflowState,
    *,
    table: dict[WorkflowState, frozenset[WorkflowState]] | None = None,
) -> bool:
    if current == nxt:
        return True
    edges = table if table is not None else EXPENSE_TO_RECEIPT_TRANSITIONS
    allowed = edges.get(current)
    if allowed is None:
        return False
    return nxt in allowed


def assert_transition(
    current: WorkflowState,
    nxt: WorkflowState,
    *,
    table: dict[WorkflowState, frozenset[WorkflowState]] | None = None,
) -> None:
    if not can_transition(current, nxt, table=table):
        raise WorkflowStateError(
            f"illegal workflow transition {current.value} → {nxt.value}"
        )


def can_correction_transition(current: WorkflowState, nxt: WorkflowState) -> bool:
    return can_transition(current, nxt, table=CORRECTION_TRANSITIONS)


def assert_correction_transition(current: WorkflowState, nxt: WorkflowState) -> None:
    assert_transition(current, nxt, table=CORRECTION_TRANSITIONS)


def is_human_gate(state: WorkflowState) -> bool:
    return state in HUMAN_GATE_STATES


def default_run_status(state: WorkflowState) -> WorkflowRunStatus:
    return DEFAULT_RUN_STATUS.get(state, WorkflowRunStatus.PENDING)
