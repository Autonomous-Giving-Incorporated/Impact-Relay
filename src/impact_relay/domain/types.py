"""Domain types for the HD-IR-001 use-of-funds ledger pilot."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import Enum
from typing import Any


class RestrictionType(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    BOARD_DESIGNATED = "BOARD_DESIGNATED"
    DONOR_DESIGNATED = "DONOR_DESIGNATED"
    DONOR_RESTRICTED = "DONOR_RESTRICTED"
    GRANT_RESTRICTED = "GRANT_RESTRICTED"
    SPONSOR_RESTRICTED = "SPONSOR_RESTRICTED"
    IN_KIND = "IN_KIND"


class ExpenseState(str, Enum):
    DRAFT = "DRAFT"
    IMPORTED = "IMPORTED"
    CLASSIFICATION_PENDING = "CLASSIFICATION_PENDING"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"
    SUPERSEDED = "SUPERSEDED"


class AttributionMethod(str, Enum):
    DIRECT_RESTRICTED = "DIRECT_RESTRICTED"
    PRO_RATA_POOL = "PRO_RATA_POOL"
    FIFO_ALLOCATION = "FIFO_ALLOCATION"
    COHORT_ALLOCATION = "COHORT_ALLOCATION"
    ASSET_SPONSORSHIP = "ASSET_SPONSORSHIP"
    EXPENSE_BACKED = "EXPENSE_BACKED"
    MANUAL_APPROVED = "MANUAL_APPROVED"
    NONE = "NONE"


# Methods allowed to produce a verified use-of-funds receipt.
ALLOWED_ATTRIBUTION_METHODS: frozenset[AttributionMethod] = frozenset(
    {
        AttributionMethod.DIRECT_RESTRICTED,
        AttributionMethod.PRO_RATA_POOL,
        AttributionMethod.FIFO_ALLOCATION,
        AttributionMethod.COHORT_ALLOCATION,
        AttributionMethod.ASSET_SPONSORSHIP,
        AttributionMethod.EXPENSE_BACKED,
        AttributionMethod.MANUAL_APPROVED,
    }
)

# States that may back a verified use-of-funds receipt.
VERIFIED_EXPENSE_STATES: frozenset[ExpenseState] = frozenset(
    {ExpenseState.APPROVED, ExpenseState.RECONCILED}
)

# Terminal / non-mutable approved lineage states for corrections.
CORRECTED_EXPENSE_STATES: frozenset[ExpenseState] = frozenset(
    {ExpenseState.REVERSED, ExpenseState.SUPERSEDED}
)


class DomainError(Exception):
    """Base domain error."""


class InvariantError(DomainError):
    """Money or balance invariant violated."""


class StateError(DomainError):
    """Illegal state transition or action for current state."""


class AttributionError(DomainError):
    """Missing or disallowed attribution method."""


class NotFoundError(DomainError):
    """Referenced entity not found."""


def money(value: Decimal | str | int | float) -> Decimal:
    """Normalize money to two-decimal Decimal (quantized)."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return d.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    policy_version: str = "v1.0"


@dataclass(frozen=True)
class Donor:
    id: str
    organization_id: str
    display_name: str


@dataclass(frozen=True)
class Donation:
    id: str
    organization_id: str
    donor_id: str
    amount: Decimal
    currency: str
    cleared: bool
    external_source_id: str
    received_at: str  # ISO date string

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


@dataclass(frozen=True)
class Allocation:
    id: str
    organization_id: str
    name: str
    purpose: str
    restriction_type: RestrictionType


@dataclass(frozen=True)
class DonationAllocation:
    id: str
    donation_id: str
    allocation_id: str
    amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


@dataclass(frozen=True)
class Expense:
    id: str
    organization_id: str
    vendor: str
    amount: Decimal
    currency: str
    purchase_date: str
    category: str
    description: str
    state: ExpenseState
    external_source_id: str | None = None
    approved_by: str | None = None
    reconciled_at: str | None = None
    reversed_of_id: str | None = None
    supersedes_id: str | None = None
    # Immutable snapshot of prior approved facts (append-only corrections).
    history_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


@dataclass(frozen=True)
class ExpenseAllocation:
    id: str
    expense_id: str
    allocation_id: str
    amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    expense_id: str
    kind: str  # invoice | receipt | accounting_ref
    summary: str
    donor_visible: bool = True


@dataclass(frozen=True)
class DonorExpenseAttribution:
    """Policy-based link between a donor's support and an expenditure."""

    id: str
    donor_id: str
    donation_id: str
    expense_id: str
    allocation_id: str
    attributed_amount: Decimal
    method: AttributionMethod
    policy_version: str
    confidence: str = "policy"  # policy | estimated | manual

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributed_amount", money(self.attributed_amount))


@dataclass(frozen=True)
class AuditReceipt:
    id: str
    organization_id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor: str
    timestamp: str
    payload: dict[str, Any]
    policy_version: str
    receipt_hash: str


@dataclass(frozen=True)
class UseOfFundsReceipt:
    """Donor-visible use-of-funds receipt (preview/publish artifact)."""

    receipt_id: str
    type: str  # USE_OF_FUNDS
    organization_id: str
    organization_name: str
    donation_id: str
    donor_id: str
    allocation_id: str
    allocation_name: str
    restriction_type: str
    expenditure_expense_id: str
    vendor: str
    gross_amount: Decimal
    attributed_amount: Decimal
    purchase_date: str
    category: str
    description: str
    verification_state: str
    remaining_designated_balance: Decimal
    attribution_method: str
    policy_version: str
    approved_by: str | None
    currency: str
    receipt_hash: str
    created_at: str
    corrected: bool = False
    corrects_receipt_id: str | None = None
    correction_kind: str | None = None  # REVERSAL | SUPERSEDE
    evidence_summary: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "type": self.type,
            "organization": {
                "id": self.organization_id,
                "name": self.organization_name,
            },
            "donation_reference": self.donation_id,
            "donor_id": self.donor_id,
            "allocation": {
                "id": self.allocation_id,
                "name": self.allocation_name,
                "restriction_type": self.restriction_type,
            },
            "expenditure": {
                "expense_id": self.expenditure_expense_id,
                "vendor": self.vendor,
                "gross_amount": str(self.gross_amount),
                "attributed_amount": str(self.attributed_amount),
                "purchase_date": self.purchase_date,
                "category": self.category,
                "description": self.description,
                "verification_state": self.verification_state,
                "currency": self.currency,
            },
            "remaining_designated_balance": str(self.remaining_designated_balance),
            "attribution": {
                "method": self.attribution_method,
                "policy_version": self.policy_version,
            },
            "corrected": self.corrected,
            "corrects_receipt_id": self.corrects_receipt_id,
            "correction_kind": self.correction_kind,
            "evidence_summary": self.evidence_summary,
            "provenance": {
                **self.provenance,
                "approved_by": self.approved_by,
                "receipt_hash": self.receipt_hash,
                "created_at": self.created_at,
            },
        }


def with_expense_state(expense: Expense, state: ExpenseState, **kwargs: Any) -> Expense:
    """Return a new Expense with updated state (append-only lineage via new records preferred)."""
    return replace(expense, state=state, **kwargs)


# ---------------------------------------------------------------------------
# Phase 4 — Impact
# ---------------------------------------------------------------------------


class ImpactEventState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AssetLifecycle(str, Enum):
    PROCURED = "PROCURED"
    DEPLOYED = "DEPLOYED"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class Program:
    id: str
    organization_id: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class FundedAsset:
    id: str
    organization_id: str
    name: str
    expense_id: str
    allocation_id: str
    lifecycle: AssetLifecycle = AssetLifecycle.PROCURED


@dataclass(frozen=True)
class ImpactEvent:
    id: str
    organization_id: str
    program_id: str
    event_type: str
    event_date: str
    participants: int
    state: ImpactEventState
    funded_asset_ids: tuple[str, ...] = ()
    expense_ids: tuple[str, ...] = ()
    description: str = ""
    verified_by: str | None = None
    verified_at: str | None = None


@dataclass(frozen=True)
class ImpactReceipt:
    """Donor-visible IMPACT receipt (publish artifact)."""

    receipt_id: str
    type: str  # IMPACT
    organization_id: str
    organization_name: str
    donor_id: str
    donation_id: str
    allocation_id: str
    allocation_name: str
    impact_event_id: str
    program_id: str
    program_name: str
    event_type: str
    event_date: str
    participants: int
    evidence_state: str
    linked_expense_ids: tuple[str, ...]
    attribution_method: str
    policy_version: str
    receipt_hash: str
    created_at: str
    description: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "type": self.type,
            "organization": {
                "id": self.organization_id,
                "name": self.organization_name,
            },
            "donor_id": self.donor_id,
            "donation_id": self.donation_id,
            "allocation": {"id": self.allocation_id, "name": self.allocation_name},
            "impact": {
                "event_id": self.impact_event_id,
                "program_id": self.program_id,
                "program_name": self.program_name,
                "event_type": self.event_type,
                "event_date": self.event_date,
                "participants": self.participants,
                "evidence_state": self.evidence_state,
                "description": self.description,
                "linked_expense_ids": list(self.linked_expense_ids),
            },
            "attribution": {
                "method": self.attribution_method,
                "policy_version": self.policy_version,
            },
            "provenance": {
                **self.provenance,
                "receipt_hash": self.receipt_hash,
                "created_at": self.created_at,
            },
        }


# ---------------------------------------------------------------------------
# Phase 3 — Notifications
# ---------------------------------------------------------------------------


class NotificationChannel(str, Enum):
    PUSH = "PUSH"
    EMAIL = "EMAIL"
    SMS = "SMS"


class NotificationMessageClass(str, Enum):
    MONEY_USED = "MONEY_USED"
    IMPACT_OCCURRED = "IMPACT_OCCURRED"
    CORRECTION = "CORRECTION"
    DIGEST = "DIGEST"


class NotificationIntentStatus(str, Enum):
    CREATED = "CREATED"
    BLOCKED_NO_CONSENT = "BLOCKED_NO_CONSENT"
    BLOCKED_PREFERENCE = "BLOCKED_PREFERENCE"
    DEFERRED_QUIET_HOURS = "DEFERRED_QUIET_HOURS"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


@dataclass(frozen=True)
class NotificationPreference:
    donor_id: str
    organization_id: str
    channel: NotificationChannel
    enabled: bool
    topics: tuple[str, ...] = ()
    cadence: str = "immediate"  # immediate | weekly | monthly
    # Quiet hours in UTC "HH:MM" (inclusive start, exclusive end; wraps midnight)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


@dataclass(frozen=True)
class ConsentRecord:
    donor_id: str
    organization_id: str
    channel: NotificationChannel
    granted: bool
    provenance: str
    recorded_at: str


@dataclass(frozen=True)
class NotificationIntent:
    id: str
    organization_id: str
    donor_id: str
    channel: NotificationChannel
    message_class: NotificationMessageClass
    source_type: str  # USE_OF_FUNDS | IMPACT | CORRECTION
    source_id: str
    dedup_key: str
    policy_version: str
    status: NotificationIntentStatus
    template_version: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class NotificationDelivery:
    id: str
    intent_id: str
    organization_id: str
    donor_id: str
    channel: NotificationChannel
    success: bool
    provider: str
    provider_receipt: str
    attempted_at: str
    detail: str = ""


# ---------------------------------------------------------------------------
# Phase 2 — Donor read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllocationBalanceView:
    allocation_id: str
    allocation_name: str
    restriction_type: str
    designated_total: Decimal
    used: Decimal
    remaining: Decimal
    pending_unreconciled: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "allocation_name": self.allocation_name,
            "restriction_type": self.restriction_type,
            "designated_total": str(self.designated_total),
            "used": str(self.used),
            "remaining": str(self.remaining),
            "pending_unreconciled": str(self.pending_unreconciled),
        }


@dataclass(frozen=True)
class TimelineEvent:
    at: str
    kind: str
    summary: str
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "kind": self.kind,
            "summary": self.summary,
            "refs": self.refs,
        }


class TenantIsolationError(DomainError):
    """Cross-tenant access denied."""


class ConsentError(DomainError):
    """Consent or preference blocks notification."""
