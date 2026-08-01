"""Agent governance contracts (v0.5).

AI proposes. Deterministic services validate. Authorized humans approve.
These types never mutate the ledger directly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AuthorityLevel(str, Enum):
    """Agent capability ceiling. Agents cannot self-elevate."""

    L0_OBSERVE = "L0"
    L1_PROPOSE = "L1"
    L2_REVERSIBLE = "L2"
    L3_HUMAN_APPROVAL = "L3"


# Numeric rank for comparison (higher = more privileged).
AUTHORITY_RANK: dict[AuthorityLevel, int] = {
    AuthorityLevel.L0_OBSERVE: 0,
    AuthorityLevel.L1_PROPOSE: 1,
    AuthorityLevel.L2_REVERSIBLE: 2,
    AuthorityLevel.L3_HUMAN_APPROVAL: 3,
}


class AgentRunStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    SIMULATED = "SIMULATED"


class ValidationStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    BLOCKED = "BLOCKED"


class EvidenceSufficiency(str, Enum):
    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
    SUFFICIENT = "SUFFICIENT"
    CONTRADICTORY = "CONTRADICTORY"
    EXPIRED = "EXPIRED"
    REDACTION_REQUIRED = "REDACTION_REQUIRED"


class WorkflowState(str, Enum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    CLASSIFICATION_PENDING = "CLASSIFICATION_PENDING"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    REVIEW_PENDING = "REVIEW_PENDING"
    APPROVED = "APPROVED"
    LEDGER_COMMITTED = "LEDGER_COMMITTED"
    RECEIPT_DRAFTED = "RECEIPT_DRAFTED"
    PUBLICATION_PENDING = "PUBLICATION_PENDING"
    PUBLISHED = "PUBLISHED"
    NOTIFICATION_PENDING = "NOTIFICATION_PENDING"
    DELIVERED = "DELIVERED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"


# Consequential command types that always require a human ApprovalReceipt.
L3_COMMAND_TYPES: frozenset[str] = frozenset(
    {
        "approve_expense",
        "reject_expense",
        "publish_use_of_funds_receipt",
        "send_notification",
        "publish_public_evidence",
        "change_attribution_policy",
        "correct_published_amount",
    }
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _enum_value(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _enum_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_enum_value(v) for v in obj]
    return obj


def to_jsonable(obj: Any) -> Any:
    """Convert dataclasses / enums to JSON-serializable structures."""
    if hasattr(obj, "__dataclass_fields__"):
        return _enum_value(asdict(obj))
    return _enum_value(obj)


@dataclass(frozen=True)
class AgentCommand:
    """A bounded action an agent proposes or a human authorizes."""

    command_type: str
    tenant_id: str
    payload: dict[str, Any]
    required_authority: AuthorityLevel = AuthorityLevel.L1_PROPOSE
    idempotency_key: str = ""
    expires_at: str | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            key = stable_hash(
                {
                    "command_type": self.command_type,
                    "tenant_id": self.tenant_id,
                    "payload": self.payload,
                }
            )
            object.__setattr__(self, "idempotency_key", key)
        if self.command_type in L3_COMMAND_TYPES and self.required_authority != AuthorityLevel.L3_HUMAN_APPROVAL:
            object.__setattr__(self, "required_authority", AuthorityLevel.L3_HUMAN_APPROVAL)


@dataclass(frozen=True)
class AgentProposal:
    """Output of Agent.evaluate — never an authorization."""

    proposal_id: str
    tenant_id: str
    agent_name: str
    agent_version: str
    policy_version: str
    prompt_version: str | None
    input_refs: list[str]
    input_hash: str
    proposed_commands: list[AgentCommand]
    evidence_refs: list[str]
    confidence: float | None
    warnings: list[str]
    contradictions: list[str]
    required_authority: AuthorityLevel
    expires_at: str
    idempotency_key: str
    notes: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def is_expired(self, now: str | None = None) -> bool:
        current = now or utc_now_iso()
        return current > self.expires_at


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == ValidationStatus.ACCEPTED


@dataclass(frozen=True)
class ApprovalReceipt:
    """Independently authenticated human decision. Agents cannot mint this for themselves."""

    approval_id: str
    tenant_id: str
    proposal_id: str
    command_idempotency_key: str
    decision: str  # APPROVE | REJECT | REQUEST_INFORMATION | EDIT
    approver_id: str
    approver_role: str
    approved_at: str
    rationale: str = ""
    policy_version: str = "v1.0"

    def __post_init__(self) -> None:
        if not self.approver_id:
            raise ValueError("approver_id is required")
        if self.decision not in (
            "APPROVE",
            "REJECT",
            "REQUEST_INFORMATION",
            "EDIT",
        ):
            raise ValueError(f"invalid decision: {self.decision}")


@dataclass(frozen=True)
class ExecutionReceipt:
    execution_id: str
    tenant_id: str
    command_type: str
    idempotency_key: str
    status: str  # SUCCEEDED | FAILED | SKIPPED | SIMULATED
    output_refs: list[str]
    output_hash: str
    executed_at: str
    simulated: bool = False
    error: str | None = None
    approval_id: str | None = None


@dataclass(frozen=True)
class AgentRunReceipt:
    run_id: str
    tenant_id: str
    workflow: str
    agent: str
    agent_version: str
    policy_version: str
    prompt_version: str | None
    input_refs: list[str]
    input_hash: str
    proposed_actions: list[str]
    accepted_actions: list[str]
    rejected_actions: list[str]
    human_approvals: list[str]
    output_refs: list[str]
    output_hash: str
    started_at: str
    completed_at: str
    status: AgentRunStatus
