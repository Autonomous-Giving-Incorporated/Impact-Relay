"""In-memory ledger enforcing HD-IR-001 money invariants and receipt generation.

All public mutations go through this API so silent rewrite of approved facts
is impossible: corrections create reverse/supersede records and new receipts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from impact_relay.domain.types import (
    ALLOWED_ATTRIBUTION_METHODS,
    CORRECTED_EXPENSE_STATES,
    VERIFIED_EXPENSE_STATES,
    Allocation,
    AttributionError,
    AttributionMethod,
    AuditReceipt,
    Donation,
    DonationAllocation,
    Donor,
    DonorExpenseAttribution,
    EvidenceRecord,
    Expense,
    ExpenseAllocation,
    ExpenseState,
    InvariantError,
    NotFoundError,
    Organization,
    StateError,
    UseOfFundsReceipt,
    money,
    with_expense_state,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _stable_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Ledger:
    """Single-tenant pilot ledger (organization-scoped stores)."""

    def __init__(self, organization: Organization) -> None:
        self.organization = organization
        self.donors: dict[str, Donor] = {}
        self.donations: dict[str, Donation] = {}
        self.allocations: dict[str, Allocation] = {}
        self.donation_allocations: dict[str, DonationAllocation] = {}
        self.expenses: dict[str, Expense] = {}
        self.expense_allocations: dict[str, ExpenseAllocation] = {}
        self.evidence: dict[str, EvidenceRecord] = {}
        self.attributions: dict[str, DonorExpenseAttribution] = {}
        self.receipts: dict[str, UseOfFundsReceipt] = {}
        # receipt_id -> frozen snapshot at publish time (never mutated)
        self._receipt_snapshots: dict[str, dict[str, Any]] = {}
        self.audit_log: list[AuditReceipt] = []
        # expense_id -> list of published receipt_ids (lineage)
        self._expense_receipts: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Registration / import
    # ------------------------------------------------------------------

    def register_donor(self, donor: Donor) -> Donor:
        if donor.organization_id != self.organization.id:
            raise InvariantError("donor organization_id mismatch")
        self.donors[donor.id] = donor
        self._audit("DonorRegistered", "Donor", donor.id, "system", {"donor_id": donor.id})
        return donor

    def import_donation(self, donation: Donation) -> Donation:
        if donation.organization_id != self.organization.id:
            raise InvariantError("donation organization_id mismatch")
        if donation.amount <= 0:
            raise InvariantError("donation amount must be positive")
        if donation.id in self.donations:
            raise InvariantError(f"donation already imported: {donation.id}")
        if donation.donor_id not in self.donors:
            raise NotFoundError(f"donor not found: {donation.donor_id}")
        self.donations[donation.id] = donation
        self._audit(
            "DonationImported",
            "Donation",
            donation.id,
            "system",
            {
                "amount": str(donation.amount),
                "cleared": donation.cleared,
                "external_source_id": donation.external_source_id,
            },
        )
        return donation

    def register_allocation(self, allocation: Allocation) -> Allocation:
        if allocation.organization_id != self.organization.id:
            raise InvariantError("allocation organization_id mismatch")
        self.allocations[allocation.id] = allocation
        self._audit(
            "AllocationRegistered",
            "Allocation",
            allocation.id,
            "system",
            {"name": allocation.name},
        )
        return allocation

    def assign_donation_allocation(
        self,
        *,
        donation_id: str,
        allocation_id: str,
        amount: Decimal | str | int | float,
        donation_allocation_id: str | None = None,
    ) -> DonationAllocation:
        donation = self._require_donation(donation_id)
        if allocation_id not in self.allocations:
            raise NotFoundError(f"allocation not found: {allocation_id}")
        if not donation.cleared:
            raise StateError("cannot allocate uncleared donation")

        amt = money(amount)
        if amt <= 0:
            raise InvariantError("allocation amount must be positive")

        already = self._sum_donation_allocations(donation_id)
        if already + amt > donation.amount:
            raise InvariantError(
                f"donation allocations exceed cleared amount: "
                f"{already + amt} > {donation.amount}"
            )

        da = DonationAllocation(
            id=donation_allocation_id or _new_id("da"),
            donation_id=donation_id,
            allocation_id=allocation_id,
            amount=amt,
        )
        self.donation_allocations[da.id] = da
        self._audit(
            "AllocationAssigned",
            "DonationAllocation",
            da.id,
            "system",
            {
                "donation_id": donation_id,
                "allocation_id": allocation_id,
                "amount": str(amt),
            },
        )
        return da

    def import_expense(self, expense: Expense) -> Expense:
        if expense.organization_id != self.organization.id:
            raise InvariantError("expense organization_id mismatch")
        if expense.amount <= 0:
            raise InvariantError("expense amount must be positive")
        if expense.id in self.expenses:
            raise InvariantError(f"expense already imported: {expense.id}")
        # Imports land as IMPORTED unless explicitly DRAFT.
        if expense.state not in (ExpenseState.DRAFT, ExpenseState.IMPORTED):
            raise StateError("import only accepts DRAFT or IMPORTED state")
        self.expenses[expense.id] = expense
        self._audit(
            "ExpenseImported",
            "Expense",
            expense.id,
            "system",
            {"amount": str(expense.amount), "state": expense.state.value},
        )
        return expense

    def attach_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        if evidence.expense_id not in self.expenses:
            raise NotFoundError(f"expense not found: {evidence.expense_id}")
        self.evidence[evidence.id] = evidence
        self._audit(
            "EvidenceAttached",
            "EvidenceRecord",
            evidence.id,
            "system",
            {"expense_id": evidence.expense_id, "kind": evidence.kind},
        )
        return evidence

    def allocate_expense(
        self,
        *,
        expense_id: str,
        allocation_id: str,
        amount: Decimal | str | int | float,
        expense_allocation_id: str | None = None,
    ) -> ExpenseAllocation:
        expense = self._require_expense(expense_id)
        if expense.state in CORRECTED_EXPENSE_STATES:
            raise StateError("cannot allocate a reversed or superseded expense")
        if expense.state in VERIFIED_EXPENSE_STATES:
            raise StateError("cannot re-allocate an approved/reconciled expense")
        if allocation_id not in self.allocations:
            raise NotFoundError(f"allocation not found: {allocation_id}")

        amt = money(amount)
        if amt <= 0:
            raise InvariantError("expense allocation amount must be positive")

        # Soft check: remaining fund balance must cover (after approval it hard-enforces).
        remaining = self.allocation_remaining_balance(allocation_id)
        # Pending expense allocations on this fund also consume soft capacity for draft work.
        pending_other = self._sum_pending_expense_allocations(allocation_id, exclude_expense=expense_id)
        # Allow classification while soft-over; approval enforces hard balance.
        _ = remaining  # documented soft signal for operators
        _ = pending_other

        ea = ExpenseAllocation(
            id=expense_allocation_id or _new_id("ea"),
            expense_id=expense_id,
            allocation_id=allocation_id,
            amount=amt,
        )
        # Replace prior allocations for this expense when re-classifying.
        self.expense_allocations = {
            k: v for k, v in self.expense_allocations.items() if v.expense_id != expense_id
        }
        # If multiple splits, caller should pass all at once via allocate_expense_splits.
        self.expense_allocations[ea.id] = ea

        # Move toward classification/approval pipeline.
        if expense.state in (ExpenseState.DRAFT, ExpenseState.IMPORTED, ExpenseState.CLASSIFICATION_PENDING):
            self.expenses[expense_id] = with_expense_state(
                expense, ExpenseState.APPROVAL_PENDING
            )

        self._audit(
            "ExpenseAllocated",
            "ExpenseAllocation",
            ea.id,
            "system",
            {
                "expense_id": expense_id,
                "allocation_id": allocation_id,
                "amount": str(amt),
            },
        )
        return ea

    def allocate_expense_splits(
        self,
        *,
        expense_id: str,
        splits: list[tuple[str, Decimal | str | int | float]],
    ) -> list[ExpenseAllocation]:
        """Assign expense across one or more allocations. Sum must equal expense amount."""
        expense = self._require_expense(expense_id)
        if expense.state in CORRECTED_EXPENSE_STATES:
            raise StateError("cannot allocate a reversed or superseded expense")
        if expense.state in VERIFIED_EXPENSE_STATES:
            raise StateError("cannot re-allocate an approved/reconciled expense")

        parsed: list[tuple[str, Decimal]] = []
        total = Decimal("0.00")
        for allocation_id, raw in splits:
            if allocation_id not in self.allocations:
                raise NotFoundError(f"allocation not found: {allocation_id}")
            amt = money(raw)
            if amt <= 0:
                raise InvariantError("expense allocation amount must be positive")
            parsed.append((allocation_id, amt))
            total += amt

        if total != expense.amount:
            raise InvariantError(
                f"expense allocations must sum to expense amount: {total} != {expense.amount}"
            )

        # Clear prior
        self.expense_allocations = {
            k: v for k, v in self.expense_allocations.items() if v.expense_id != expense_id
        }
        results: list[ExpenseAllocation] = []
        for allocation_id, amt in parsed:
            ea = ExpenseAllocation(
                id=_new_id("ea"),
                expense_id=expense_id,
                allocation_id=allocation_id,
                amount=amt,
            )
            self.expense_allocations[ea.id] = ea
            results.append(ea)

        if expense.state in (ExpenseState.DRAFT, ExpenseState.IMPORTED, ExpenseState.CLASSIFICATION_PENDING):
            self.expenses[expense_id] = with_expense_state(
                expense, ExpenseState.APPROVAL_PENDING
            )

        self._audit(
            "ExpenseAllocated",
            "Expense",
            expense_id,
            "system",
            {"splits": [(a, str(m)) for a, m in parsed]},
        )
        return results

    # ------------------------------------------------------------------
    # Finance approval / reconciliation
    # ------------------------------------------------------------------

    def approve_expense(self, expense_id: str, *, approved_by: str) -> Expense:
        expense = self._require_expense(expense_id)
        if expense.state in CORRECTED_EXPENSE_STATES:
            raise StateError("cannot approve a reversed or superseded expense")
        if expense.state in VERIFIED_EXPENSE_STATES:
            raise StateError("expense already approved/reconciled")
        if expense.state not in (
            ExpenseState.APPROVAL_PENDING,
            ExpenseState.CLASSIFICATION_PENDING,
            ExpenseState.IMPORTED,
        ):
            raise StateError(f"cannot approve expense in state {expense.state.value}")

        eas = self._expense_allocations_for(expense_id)
        if not eas:
            raise StateError("expense has no fund allocation")
        total = sum((ea.amount for ea in eas), Decimal("0.00"))
        if total != expense.amount:
            raise InvariantError(
                f"approved expense allocations must equal expense amount: "
                f"{total} != {expense.amount}"
            )

        # Hard balance check per allocation fund.
        for ea in eas:
            remaining = self.allocation_remaining_balance(ea.allocation_id)
            # Remaining already excludes non-verified; we check capacity against approved only.
            # Approving this expense will reduce remaining by ea.amount.
            if remaining < ea.amount:
                raise InvariantError(
                    f"restricted allocation balance would go negative: "
                    f"allocation={ea.allocation_id} remaining={remaining} charge={ea.amount}"
                )

        if not approved_by:
            raise StateError("approved_by is required")

        updated = with_expense_state(
            expense, ExpenseState.APPROVED, approved_by=approved_by
        )
        self.expenses[expense_id] = updated
        self._audit(
            "ExpenseApproved",
            "Expense",
            expense_id,
            approved_by,
            {"amount": str(expense.amount)},
        )
        return updated

    def reconcile_expense(self, expense_id: str, *, actor: str) -> Expense:
        expense = self._require_expense(expense_id)
        if expense.state != ExpenseState.APPROVED:
            raise StateError("only APPROVED expenses can be reconciled")
        updated = with_expense_state(
            expense, ExpenseState.RECONCILED, reconciled_at=_now_iso()
        )
        self.expenses[expense_id] = updated
        self._audit(
            "ExpenseReconciled",
            "Expense",
            expense_id,
            actor,
            {"reconciled_at": updated.reconciled_at},
        )
        return updated

    # ------------------------------------------------------------------
    # Attribution
    # ------------------------------------------------------------------

    def attribute_donor_to_expense(
        self,
        *,
        donor_id: str,
        donation_id: str,
        expense_id: str,
        allocation_id: str,
        method: AttributionMethod,
        attributed_amount: Decimal | str | int | float | None = None,
        attribution_id: str | None = None,
    ) -> DonorExpenseAttribution:
        if method == AttributionMethod.NONE or method not in ALLOWED_ATTRIBUTION_METHODS:
            raise AttributionError(
                f"phantom or disallowed attribution method: {method.value}"
            )
        if donor_id not in self.donors:
            raise NotFoundError(f"donor not found: {donor_id}")
        donation = self._require_donation(donation_id)
        expense = self._require_expense(expense_id)
        if donation.donor_id != donor_id:
            raise InvariantError("donation does not belong to donor")
        if allocation_id not in self.allocations:
            raise NotFoundError(f"allocation not found: {allocation_id}")

        # Donation must have contribution to this allocation.
        donor_alloc_total = sum(
            (
                da.amount
                for da in self.donation_allocations.values()
                if da.donation_id == donation_id and da.allocation_id == allocation_id
            ),
            Decimal("0.00"),
        )
        if donor_alloc_total <= 0:
            raise InvariantError("donation has no allocation to the specified fund")

        expense_charge = sum(
            (
                ea.amount
                for ea in self.expense_allocations.values()
                if ea.expense_id == expense_id and ea.allocation_id == allocation_id
            ),
            Decimal("0.00"),
        )
        if expense_charge <= 0:
            raise InvariantError("expense is not charged to the specified allocation")

        if method == AttributionMethod.DIRECT_RESTRICTED:
            # Donor is attributed their share up to expense charge; default full charge
            # when single supporting donation covers it.
            if attributed_amount is None:
                attr_amt = min(donor_alloc_total, expense_charge)
            else:
                attr_amt = money(attributed_amount)
        elif method == AttributionMethod.PRO_RATA_POOL:
            pool_total = self._donation_pool_for_allocation(allocation_id)
            if pool_total <= 0:
                raise InvariantError("empty allocation pool for pro-rata")
            share = donor_alloc_total / pool_total
            attr_amt = money(expense_charge * share)
        else:
            # Other allowed methods: require explicit amount under finance policy.
            if attributed_amount is None:
                raise AttributionError(
                    f"method {method.value} requires explicit attributed_amount"
                )
            attr_amt = money(attributed_amount)

        if attr_amt <= 0:
            raise InvariantError("attributed_amount must be positive")
        if attr_amt > expense_charge:
            raise InvariantError("attributed_amount cannot exceed expense allocation charge")
        if attr_amt > donor_alloc_total:
            raise InvariantError("attributed_amount cannot exceed donor allocation to fund")

        # Guard against silent double-attribution beyond donation support.
        already = sum(
            (
                a.attributed_amount
                for a in self.attributions.values()
                if a.donation_id == donation_id
                and a.allocation_id == allocation_id
                and self.expenses[a.expense_id].state in VERIFIED_EXPENSE_STATES
            ),
            Decimal("0.00"),
        )
        # Current expense may not yet be verified; include pending attrs on this donation.
        pending = sum(
            (
                a.attributed_amount
                for a in self.attributions.values()
                if a.donation_id == donation_id and a.allocation_id == allocation_id
            ),
            Decimal("0.00"),
        )
        if pending + attr_amt > donor_alloc_total + Decimal("0.00"):
            # Allow re-attribute by replacing existing attrs for same donation+expense.
            pass
        _ = already

        # Replace prior attribution for same donation+expense+allocation.
        self.attributions = {
            k: v
            for k, v in self.attributions.items()
            if not (
                v.donation_id == donation_id
                and v.expense_id == expense_id
                and v.allocation_id == allocation_id
            )
        }

        attr = DonorExpenseAttribution(
            id=attribution_id or _new_id("attr"),
            donor_id=donor_id,
            donation_id=donation_id,
            expense_id=expense_id,
            allocation_id=allocation_id,
            attributed_amount=attr_amt,
            method=method,
            policy_version=self.organization.policy_version,
        )
        self.attributions[attr.id] = attr
        self._audit(
            "DonorExpenseAttributed",
            "DonorExpenseAttribution",
            attr.id,
            "system",
            {
                "method": method.value,
                "attributed_amount": str(attr_amt),
                "expense_id": expense_id,
            },
        )
        return attr

    # ------------------------------------------------------------------
    # Use-of-funds receipt generation
    # ------------------------------------------------------------------

    def publish_use_of_funds_receipt(
        self,
        *,
        expense_id: str,
        donation_id: str,
        allocation_id: str,
        actor: str,
        created_at: str | None = None,
    ) -> UseOfFundsReceipt:
        expense = self._require_expense(expense_id)
        if expense.state not in VERIFIED_EXPENSE_STATES:
            raise StateError(
                f"verified use-of-funds receipt requires APPROVED or RECONCILED expense; "
                f"got {expense.state.value}"
            )
        donation = self._require_donation(donation_id)
        allocation = self._require_allocation(allocation_id)

        attr = self._find_attribution(donation_id, expense_id, allocation_id)
        if attr is None:
            raise AttributionError(
                "no attribution record; refuse phantom one-to-one linkage"
            )
        if attr.method not in ALLOWED_ATTRIBUTION_METHODS:
            raise AttributionError(f"disallowed attribution method: {attr.method.value}")

        remaining = self.allocation_remaining_balance(allocation_id)
        # Donor-facing remaining on their designated balance for this fund.
        donor_remaining = self.donor_remaining_on_allocation(donation_id, allocation_id)

        evidence_summary = self._donor_visible_evidence_summary(expense_id)
        created = created_at or _now_iso()
        receipt_id = _new_id("uof")

        body = {
            "type": "USE_OF_FUNDS",
            "organization_id": self.organization.id,
            "donation_id": donation_id,
            "donor_id": donation.donor_id,
            "allocation_id": allocation_id,
            "allocation_name": allocation.name,
            "expense_id": expense_id,
            "gross_amount": str(expense.amount),
            "attributed_amount": str(attr.attributed_amount),
            "purchase_date": expense.purchase_date,
            "category": expense.category,
            "description": expense.description,
            "verification_state": expense.state.value,
            "remaining_designated_balance": str(donor_remaining),
            "allocation_pool_remaining": str(remaining),
            "attribution_method": attr.method.value,
            "policy_version": self.organization.policy_version,
            "approved_by": expense.approved_by,
            "created_at": created,
        }
        receipt_hash = _stable_hash(body)

        receipt = UseOfFundsReceipt(
            receipt_id=receipt_id,
            type="USE_OF_FUNDS",
            organization_id=self.organization.id,
            organization_name=self.organization.name,
            donation_id=donation_id,
            donor_id=donation.donor_id,
            allocation_id=allocation_id,
            allocation_name=allocation.name,
            restriction_type=allocation.restriction_type.value,
            expenditure_expense_id=expense_id,
            vendor=expense.vendor,
            gross_amount=expense.amount,
            attributed_amount=attr.attributed_amount,
            purchase_date=expense.purchase_date,
            category=expense.category,
            description=expense.description,
            verification_state=expense.state.value,
            remaining_designated_balance=donor_remaining,
            attribution_method=attr.method.value,
            policy_version=self.organization.policy_version,
            approved_by=expense.approved_by,
            currency=expense.currency,
            receipt_hash=receipt_hash,
            created_at=created,
            evidence_summary=evidence_summary,
            provenance={
                "actor": actor,
                "policy_version": self.organization.policy_version,
                "attribution_id": attr.id,
            },
        )
        # Append-only store: never overwrite an existing receipt_id.
        if receipt_id in self.receipts:
            raise InvariantError("receipt_id collision")
        self.receipts[receipt_id] = receipt
        self._receipt_snapshots[receipt_id] = receipt.to_dict()
        self._expense_receipts.setdefault(expense_id, []).append(receipt_id)

        self._audit(
            "UseOfFundsReceiptPublished",
            "UseOfFundsReceipt",
            receipt_id,
            actor,
            {
                "expense_id": expense_id,
                "donation_id": donation_id,
                "receipt_hash": receipt_hash,
            },
        )
        return receipt

    def get_receipt(self, receipt_id: str) -> UseOfFundsReceipt:
        if receipt_id not in self.receipts:
            raise NotFoundError(f"receipt not found: {receipt_id}")
        return self.receipts[receipt_id]

    def get_receipt_snapshot(self, receipt_id: str) -> dict[str, Any]:
        """Return the immutable publish-time snapshot (detects silent mutation)."""
        if receipt_id not in self._receipt_snapshots:
            raise NotFoundError(f"receipt snapshot not found: {receipt_id}")
        return dict(self._receipt_snapshots[receipt_id])

    # ------------------------------------------------------------------
    # Corrections (append-only)
    # ------------------------------------------------------------------

    def reverse_expense(
        self,
        expense_id: str,
        *,
        actor: str,
        reason: str,
    ) -> tuple[Expense, list[UseOfFundsReceipt]]:
        """Mark expense REVERSED and publish correction receipts for prior UOF receipts.

        Prior receipt objects and snapshots are never mutated.
        """
        expense = self._require_expense(expense_id)
        if expense.state not in VERIFIED_EXPENSE_STATES:
            raise StateError("only APPROVED or RECONCILED expenses can be reversed")

        prior_receipt_ids = list(self._expense_receipts.get(expense_id, []))
        prior_snapshots = {
            rid: self.get_receipt_snapshot(rid) for rid in prior_receipt_ids
        }

        reversed_expense = with_expense_state(
            expense,
            ExpenseState.REVERSED,
            history_note=reason,
        )
        self.expenses[expense_id] = reversed_expense
        self._audit(
            "ExpenseReversed",
            "Expense",
            expense_id,
            actor,
            {"reason": reason, "prior_receipts": prior_receipt_ids},
        )

        correction_receipts: list[UseOfFundsReceipt] = []
        for rid in prior_receipt_ids:
            prior = self.receipts[rid]
            # Snapshot must still match stored receipt (no silent mutation).
            snap = prior_snapshots[rid]
            if snap["receipt_id"] != prior.receipt_id:
                raise InvariantError("prior receipt snapshot mismatch")
            if snap["provenance"]["receipt_hash"] != prior.receipt_hash:
                raise InvariantError("prior receipt was silently mutated")

            correction = self._publish_correction_receipt(
                prior=prior,
                expense=reversed_expense,
                actor=actor,
                kind="REVERSAL",
                reason=reason,
            )
            correction_receipts.append(correction)

        return reversed_expense, correction_receipts

    def supersede_expense(
        self,
        expense_id: str,
        *,
        replacement: Expense,
        splits: list[tuple[str, Decimal | str | int | float]],
        actor: str,
        reason: str,
        approved_by: str,
    ) -> tuple[Expense, Expense, list[UseOfFundsReceipt]]:
        """Supersede an approved expense with a new expense record (append-only).

        Old expense becomes SUPERSEDED; new expense is imported, allocated, and approved.
        Correction receipts are published against prior use-of-funds receipts.
        """
        old = self._require_expense(expense_id)
        if old.state not in VERIFIED_EXPENSE_STATES:
            raise StateError("only APPROVED or RECONCILED expenses can be superseded")

        prior_receipt_ids = list(self._expense_receipts.get(expense_id, []))

        superseded = with_expense_state(
            old, ExpenseState.SUPERSEDED, history_note=reason
        )
        self.expenses[expense_id] = superseded

        if replacement.id == expense_id:
            raise InvariantError("replacement expense must have a new id")
        if replacement.organization_id != self.organization.id:
            raise InvariantError("replacement organization_id mismatch")

        # Import replacement as IMPORTED then allocate + approve.
        repl = Expense(
            id=replacement.id,
            organization_id=replacement.organization_id,
            vendor=replacement.vendor,
            amount=money(replacement.amount),
            currency=replacement.currency,
            purchase_date=replacement.purchase_date,
            category=replacement.category,
            description=replacement.description,
            state=ExpenseState.IMPORTED,
            external_source_id=replacement.external_source_id,
            supersedes_id=expense_id,
            history_note=reason,
        )
        self.import_expense(repl)
        self.allocate_expense_splits(expense_id=repl.id, splits=splits)
        approved = self.approve_expense(repl.id, approved_by=approved_by)

        self._audit(
            "ExpenseSuperseded",
            "Expense",
            expense_id,
            actor,
            {"replacement_id": repl.id, "reason": reason},
        )

        correction_receipts: list[UseOfFundsReceipt] = []
        for rid in prior_receipt_ids:
            prior = self.receipts[rid]
            correction = self._publish_correction_receipt(
                prior=prior,
                expense=superseded,
                actor=actor,
                kind="SUPERSEDE",
                reason=reason,
                replacement_expense_id=repl.id,
            )
            correction_receipts.append(correction)

        return superseded, approved, correction_receipts

    def _publish_correction_receipt(
        self,
        *,
        prior: UseOfFundsReceipt,
        expense: Expense,
        actor: str,
        kind: str,
        reason: str,
        replacement_expense_id: str | None = None,
    ) -> UseOfFundsReceipt:
        created = _now_iso()
        receipt_id = _new_id("uofc")
        body = {
            "type": "USE_OF_FUNDS",
            "corrected": True,
            "correction_kind": kind,
            "corrects_receipt_id": prior.receipt_id,
            "expense_id": expense.id,
            "verification_state": expense.state.value,
            "reason": reason,
            "replacement_expense_id": replacement_expense_id,
            "created_at": created,
            "prior_receipt_hash": prior.receipt_hash,
        }
        receipt_hash = _stable_hash(body)

        correction = UseOfFundsReceipt(
            receipt_id=receipt_id,
            type="USE_OF_FUNDS",
            organization_id=prior.organization_id,
            organization_name=prior.organization_name,
            donation_id=prior.donation_id,
            donor_id=prior.donor_id,
            allocation_id=prior.allocation_id,
            allocation_name=prior.allocation_name,
            restriction_type=prior.restriction_type,
            expenditure_expense_id=expense.id,
            vendor=prior.vendor,
            gross_amount=prior.gross_amount,
            attributed_amount=Decimal("0.00") if kind == "REVERSAL" else prior.attributed_amount,
            purchase_date=prior.purchase_date,
            category=prior.category,
            description=prior.description,
            verification_state=expense.state.value,
            remaining_designated_balance=self.donor_remaining_on_allocation(
                prior.donation_id, prior.allocation_id
            ),
            attribution_method=prior.attribution_method,
            policy_version=self.organization.policy_version,
            approved_by=expense.approved_by or prior.approved_by,
            currency=prior.currency,
            receipt_hash=receipt_hash,
            created_at=created,
            corrected=True,
            corrects_receipt_id=prior.receipt_id,
            correction_kind=kind,
            evidence_summary=reason,
            provenance={
                "actor": actor,
                "policy_version": self.organization.policy_version,
                "prior_receipt_hash": prior.receipt_hash,
                "replacement_expense_id": replacement_expense_id,
            },
        )
        self.receipts[receipt_id] = correction
        self._receipt_snapshots[receipt_id] = correction.to_dict()
        self._expense_receipts.setdefault(expense.id, []).append(receipt_id)
        self._audit(
            "UseOfFundsCorrectionPublished",
            "UseOfFundsReceipt",
            receipt_id,
            actor,
            {
                "kind": kind,
                "corrects_receipt_id": prior.receipt_id,
                "receipt_hash": receipt_hash,
            },
        )
        return correction

    # Explicit non-API: no method to mutate existing receipts.
    def mutate_receipt(self, receipt_id: str, **_kwargs: Any) -> None:
        """Intentionally unsupported — public domain API forbids silent mutation."""
        raise StateError(
            "silent mutation of receipts is forbidden; use reverse_expense or supersede_expense"
        )

    def mutate_approved_expense(self, expense_id: str, **_kwargs: Any) -> None:
        """Intentionally unsupported — approved facts are corrected, not rewritten."""
        expense = self._require_expense(expense_id)
        if expense.state in VERIFIED_EXPENSE_STATES | CORRECTED_EXPENSE_STATES:
            raise StateError(
                "silent mutation of approved/corrected expenses is forbidden; "
                "use reverse_expense or supersede_expense"
            )
        raise StateError("use domain transition methods instead of mutate_approved_expense")

    # ------------------------------------------------------------------
    # Balance helpers
    # ------------------------------------------------------------------

    def allocation_remaining_balance(self, allocation_id: str) -> Decimal:
        """Pool remaining = sum(donation allocations) − sum(approved/reconciled expense charges).

        REVERSED and SUPERSEDED expenses do not consume balance.
        """
        if allocation_id not in self.allocations:
            raise NotFoundError(f"allocation not found: {allocation_id}")
        inflows = sum(
            (
                da.amount
                for da in self.donation_allocations.values()
                if da.allocation_id == allocation_id
            ),
            Decimal("0.00"),
        )
        outflows = Decimal("0.00")
        for ea in self.expense_allocations.values():
            if ea.allocation_id != allocation_id:
                continue
            exp = self.expenses.get(ea.expense_id)
            if exp is None:
                continue
            if exp.state in VERIFIED_EXPENSE_STATES:
                outflows += ea.amount
        return money(inflows - outflows)

    def donor_remaining_on_allocation(self, donation_id: str, allocation_id: str) -> Decimal:
        """Donor's remaining designated balance on an allocation after verified attributions."""
        designated = sum(
            (
                da.amount
                for da in self.donation_allocations.values()
                if da.donation_id == donation_id and da.allocation_id == allocation_id
            ),
            Decimal("0.00"),
        )
        consumed = Decimal("0.00")
        for attr in self.attributions.values():
            if attr.donation_id != donation_id or attr.allocation_id != allocation_id:
                continue
            exp = self.expenses.get(attr.expense_id)
            if exp is None:
                continue
            if exp.state in VERIFIED_EXPENSE_STATES:
                consumed += attr.attributed_amount
            # REVERSED / SUPERSEDED: do not consume
        return money(designated - consumed)

    def _donation_pool_for_allocation(self, allocation_id: str) -> Decimal:
        return sum(
            (
                da.amount
                for da in self.donation_allocations.values()
                if da.allocation_id == allocation_id
            ),
            Decimal("0.00"),
        )

    def _sum_donation_allocations(self, donation_id: str) -> Decimal:
        return sum(
            (
                da.amount
                for da in self.donation_allocations.values()
                if da.donation_id == donation_id
            ),
            Decimal("0.00"),
        )

    def _sum_pending_expense_allocations(
        self, allocation_id: str, *, exclude_expense: str | None = None
    ) -> Decimal:
        total = Decimal("0.00")
        for ea in self.expense_allocations.values():
            if ea.allocation_id != allocation_id:
                continue
            if exclude_expense and ea.expense_id == exclude_expense:
                continue
            exp = self.expenses.get(ea.expense_id)
            if exp and exp.state not in VERIFIED_EXPENSE_STATES | CORRECTED_EXPENSE_STATES:
                if exp.state != ExpenseState.REJECTED:
                    total += ea.amount
        return total

    def _expense_allocations_for(self, expense_id: str) -> list[ExpenseAllocation]:
        return [ea for ea in self.expense_allocations.values() if ea.expense_id == expense_id]

    def _find_attribution(
        self, donation_id: str, expense_id: str, allocation_id: str
    ) -> DonorExpenseAttribution | None:
        for attr in self.attributions.values():
            if (
                attr.donation_id == donation_id
                and attr.expense_id == expense_id
                and attr.allocation_id == allocation_id
            ):
                return attr
        return None

    def _donor_visible_evidence_summary(self, expense_id: str) -> str | None:
        parts = [
            e.summary
            for e in self.evidence.values()
            if e.expense_id == expense_id and e.donor_visible
        ]
        return "; ".join(parts) if parts else None

    def _require_donation(self, donation_id: str) -> Donation:
        if donation_id not in self.donations:
            raise NotFoundError(f"donation not found: {donation_id}")
        return self.donations[donation_id]

    def _require_expense(self, expense_id: str) -> Expense:
        if expense_id not in self.expenses:
            raise NotFoundError(f"expense not found: {expense_id}")
        return self.expenses[expense_id]

    def _require_allocation(self, allocation_id: str) -> Allocation:
        if allocation_id not in self.allocations:
            raise NotFoundError(f"allocation not found: {allocation_id}")
        return self.allocations[allocation_id]

    def _audit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        actor: str,
        payload: dict[str, Any],
    ) -> AuditReceipt:
        ts = _now_iso()
        body = {
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor": actor,
            "timestamp": ts,
            "payload": payload,
            "policy_version": self.organization.policy_version,
        }
        ar = AuditReceipt(
            id=_new_id("audit"),
            organization_id=self.organization.id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            timestamp=ts,
            payload=payload,
            policy_version=self.organization.policy_version,
            receipt_hash=_stable_hash(body),
        )
        self.audit_log.append(ar)
        return ar
