"""Durable workflow types (PR-M1).

Dual axes:
- ``WorkflowState`` (business cursor) — re-exported from agents.types
- ``WorkflowRunStatus`` (scheduler / claim) — defined here

No runtime behavior: pure data contracts for store ports and later machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    ApprovalReceipt,
    ExecutionReceipt,
    WorkflowState,
    to_jsonable,
    utc_now_iso,
)

# Re-export for workflow consumers that only import workflows.types
__all__ = [
    "AdvanceCommitBundle",
    "ExecutableCommand",
    "FrozenProposedCommand",
    "RetryPolicy",
    "SignalConsumeResult",
    "SignalType",
    "StepResult",
    "WorkflowEvent",
    "WorkflowEventType",
    "WorkflowEventWrite",
    "WorkflowInstance",
    "WorkflowRunStatus",
    "WorkflowSignal",
    "WorkflowState",
    "WorkflowType",
]


class WorkflowRunStatus(str, Enum):
    """Scheduler / claim axis (K7). WAITING_SIGNAL is never claimable."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_SIGNAL = "WAITING_SIGNAL"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


# Run statuses that the claim loop may pick up (canonical predicate).
CLAIMABLE_RUN_STATUSES: frozenset[WorkflowRunStatus] = frozenset(
    {
        WorkflowRunStatus.PENDING,
        WorkflowRunStatus.RETRY_SCHEDULED,
        # RUNNING only when lease expired — store implements that check
    }
)

TERMINAL_RUN_STATUSES: frozenset[WorkflowRunStatus] = frozenset(
    {
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED_TERMINAL,
        WorkflowRunStatus.DEAD_LETTER,
        WorkflowRunStatus.CANCELLED,
    }
)


class WorkflowType(str, Enum):
    EXPENSE_TO_RECEIPT = "expense_to_receipt"
    CORRECTION = "correction"
    SCHEDULED_DIGEST = "scheduled_digest"


class SignalType(str, Enum):
    APPROVAL = "APPROVAL"
    RESUBMIT = "RESUBMIT"
    UNBLOCK = "UNBLOCK"
    CANCEL = "CANCEL"


class SignalConsumeResult(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_INVALID = "REJECTED_INVALID"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class WorkflowEventType(str, Enum):
    CREATED = "CREATED"
    STATE_CHANGED = "STATE_CHANGED"
    PROPOSAL = "PROPOSAL"
    SIGNAL_RECEIVED = "SIGNAL_RECEIVED"
    SIGNAL_CONSUMED = "SIGNAL_CONSUMED"
    EXECUTION = "EXECUTION"
    APPROVAL = "APPROVAL"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
    DEAD_LETTERED = "DEAD_LETTERED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 900.0  # 15m
    jitter: bool = True

    def delay_for_attempt(self, attempt: int) -> float:
        """Exponential backoff 2^n (attempt is 1-based after failure)."""
        if attempt < 1:
            attempt = 1
        delay = self.base_delay_seconds * (2 ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


@dataclass(frozen=True)
class FrozenProposedCommand:
    """Snapshot stored at wait time — never regenerate idempotency keys on resume."""

    command_type: str
    tenant_id: str
    payload: dict[str, Any]
    idempotency_key: str
    expires_at: str | None
    required_authority: str
    proposal_id: str
    agent_name: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrozenProposedCommand:
        return cls(
            command_type=str(data["command_type"]),
            tenant_id=str(data["tenant_id"]),
            payload=dict(data.get("payload") or {}),
            idempotency_key=str(data["idempotency_key"]),
            expires_at=data.get("expires_at"),
            required_authority=str(data.get("required_authority") or "L3"),
            proposal_id=str(data.get("proposal_id") or ""),
            agent_name=str(data.get("agent_name") or ""),
        )


@dataclass(frozen=True)
class ExecutableCommand:
    command: AgentCommand
    requires_approval: bool
    approval: ApprovalReceipt | None
    agent_name: str | None
    proposal: AgentProposal | None = None


@dataclass(frozen=True)
class WorkflowEventWrite:
    """Event to append (seq assigned by store)."""

    event_type: WorkflowEventType
    payload: dict[str, Any] = field(default_factory=dict)
    at: str | None = None


@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    workflow_id: str
    tenant_id: str
    seq: int
    event_type: WorkflowEventType
    payload: dict[str, Any]
    at: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class WorkflowSignal:
    signal_id: str
    workflow_id: str
    tenant_id: str
    signal_type: SignalType
    payload: dict[str, Any]
    created_at: str
    consumed: bool = False
    consume_result: str | None = None

    def approval_receipt(self) -> ApprovalReceipt | None:
        """If payload is a full ApprovalReceipt dict, reconstruct it."""
        if self.signal_type != SignalType.APPROVAL:
            return None
        p = self.payload
        if "approval_id" not in p:
            return None
        return ApprovalReceipt(
            approval_id=str(p["approval_id"]),
            tenant_id=str(p["tenant_id"]),
            proposal_id=str(p["proposal_id"]),
            command_idempotency_key=str(p["command_idempotency_key"]),
            decision=str(p["decision"]),
            approver_id=str(p["approver_id"]),
            approver_role=str(p.get("approver_role") or "finance_approver"),
            approved_at=str(p.get("approved_at") or utc_now_iso()),
            rationale=str(p.get("rationale") or ""),
            policy_version=str(p.get("policy_version") or "v1.0"),
        )


@dataclass
class WorkflowInstance:
    """Mutable cursor for one business workflow (one expense after intake)."""

    workflow_id: str
    tenant_id: str
    workflow_type: WorkflowType
    business_key: str
    workflow_state: WorkflowState
    run_status: WorkflowRunStatus
    context: dict[str, Any] = field(default_factory=dict)
    simulation: bool = False
    attempt_count: int = 0
    next_run_at: str | None = None  # ISO
    wait_deadline: str | None = None
    wait_descriptor: dict[str, Any] | None = None
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    last_error: str | None = None
    timeout_applied_at: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    policy_version: str = "v1.0"
    event_seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

    def touch(self, now: str | None = None) -> None:
        self.updated_at = now or utc_now_iso()


@dataclass(frozen=True)
class StepResult:
    next_state: WorkflowState
    run_status: WorkflowRunStatus
    events: list[WorkflowEventWrite] = field(default_factory=list)
    commands_to_execute: list[ExecutableCommand] = field(default_factory=list)
    wait_for: SignalType | None = None
    wait_payload: dict[str, Any] = field(default_factory=dict)
    wait_deadline: datetime | str | None = None
    retryable_error: str | None = None
    terminal_reason: str | None = None
    context_patch: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvanceCommitBundle:
    """Atomic unit for store.commit_advance (K5 / signal consume ordering)."""

    tenant_id: str
    workflow_id: str
    instance: WorkflowInstance
    events: list[WorkflowEventWrite] = field(default_factory=list)
    execution_receipts: list[ExecutionReceipt] = field(default_factory=list)
    consume_signals: list[tuple[str, SignalConsumeResult]] = field(default_factory=list)
    # Optional T2 ledger log rows: (idempotency_key, command_type, payload, result_json)
    ledger_command_results: list[dict[str, Any]] = field(default_factory=list)
