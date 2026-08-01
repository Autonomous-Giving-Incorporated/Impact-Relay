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
