"""Phase 2 — donor-scoped read projections over ledger (+ impact) state.

Read-only: never mutates approved financial facts.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from impact_relay.domain.types import (
    AllocationBalanceView,
    CORRECTED_EXPENSE_STATES,
    ExpenseState,
    NotFoundError,
    TimelineEvent,
    VERIFIED_EXPENSE_STATES,
    money,
)

if TYPE_CHECKING:
    from impact_relay.domain.tenant import TenantWorkspace


class DonorReadService:
    def __init__(self, workspace: TenantWorkspace) -> None:
        self.ws = workspace
        self.ledger = workspace.ledger

    def _require_donor(self, donor_id: str) -> None:
        donor = self.ledger.donors.get(donor_id)
        if donor is None:
            raise NotFoundError(f"donor not found: {donor_id}")
        if donor.organization_id != self.ledger.organization.id:
            raise NotFoundError(f"donor not found: {donor_id}")

    def allocation_balances(self, donor_id: str) -> list[AllocationBalanceView]:
        self._require_donor(donor_id)
        # Map allocation_id -> designated from this donor's donations
        designated: dict[str, Decimal] = {}
        for don in self.ledger.donations.values():
            if don.donor_id != donor_id:
                continue
            for da in self.ledger.donation_allocations.values():
                if da.donation_id != don.id:
                    continue
                designated[da.allocation_id] = designated.get(
                    da.allocation_id, Decimal("0.00")
                ) + da.amount

        views: list[AllocationBalanceView] = []
        for allocation_id, total in sorted(designated.items()):
            alloc = self.ledger.allocations[allocation_id]
            used = Decimal("0.00")
            pending = Decimal("0.00")
            for attr in self.ledger.attributions.values():
                if attr.donor_id != donor_id or attr.allocation_id != allocation_id:
                    continue
                exp = self.ledger.expenses.get(attr.expense_id)
                if exp is None:
                    continue
                if exp.state in VERIFIED_EXPENSE_STATES:
                    used += attr.attributed_amount
                elif exp.state in CORRECTED_EXPENSE_STATES or exp.state == ExpenseState.REJECTED:
                    continue
                else:
                    pending += attr.attributed_amount
            remaining = money(total - used)
            views.append(
                AllocationBalanceView(
                    allocation_id=allocation_id,
                    allocation_name=alloc.name,
                    restriction_type=alloc.restriction_type.value,
                    designated_total=money(total),
                    used=money(used),
                    remaining=remaining,
                    pending_unreconciled=money(pending),
                )
            )
        return views

    def fund_timeline(self, donor_id: str) -> list[TimelineEvent]:
        self._require_donor(donor_id)
        events: list[TimelineEvent] = []

        for don in self.ledger.donations.values():
            if don.donor_id != donor_id:
                continue
            events.append(
                TimelineEvent(
                    at=don.received_at,
                    kind="DONATION_RECEIVED",
                    summary=f"Donation {don.id} received ({don.amount} {don.currency})",
                    refs={"donation_id": don.id, "amount": str(don.amount)},
                )
            )
            for da in self.ledger.donation_allocations.values():
                if da.donation_id != don.id:
                    continue
                alloc = self.ledger.allocations[da.allocation_id]
                events.append(
                    TimelineEvent(
                        at=don.received_at,
                        kind="ALLOCATION_ASSIGNED",
                        summary=f"Assigned {da.amount} to {alloc.name}",
                        refs={
                            "donation_id": don.id,
                            "allocation_id": da.allocation_id,
                            "amount": str(da.amount),
                        },
                    )
                )

        for r in self.ledger.receipts.values():
            if r.donor_id != donor_id:
                continue
            if r.corrected:
                events.append(
                    TimelineEvent(
                        at=r.created_at,
                        kind="CORRECTION",
                        summary=f"Correction ({r.correction_kind}) for prior receipt",
                        refs={
                            "receipt_id": r.receipt_id,
                            "corrects_receipt_id": r.corrects_receipt_id,
                            "kind": r.correction_kind,
                        },
                    )
                )
            else:
                events.append(
                    TimelineEvent(
                        at=r.created_at or r.purchase_date,
                        kind="USE_OF_FUNDS",
                        summary=(
                            f"Purchase: {r.description} "
                            f"({r.attributed_amount} {r.currency})"
                        ),
                        refs={
                            "receipt_id": r.receipt_id,
                            "expense_id": r.expenditure_expense_id,
                            "allocation_id": r.allocation_id,
                            "verification_state": r.verification_state,
                        },
                    )
                )

        for ir in self.ws.impact_receipts.values():
            if ir.donor_id != donor_id:
                continue
            events.append(
                TimelineEvent(
                    at=ir.created_at or ir.event_date,
                    kind="IMPACT",
                    summary=(
                        f"Impact: {ir.program_name} — {ir.event_type} "
                        f"({ir.participants} participants)"
                    ),
                    refs={
                        "receipt_id": ir.receipt_id,
                        "impact_event_id": ir.impact_event_id,
                        "program_id": ir.program_id,
                    },
                )
            )

        events.sort(key=lambda e: e.at)
        return events

    def list_receipts(self, donor_id: str) -> list[dict[str, Any]]:
        self._require_donor(donor_id)
        out: list[dict[str, Any]] = []
        for r in self.ledger.receipts.values():
            if r.donor_id == donor_id:
                out.append(r.to_dict())
        for ir in self.ws.impact_receipts.values():
            if ir.donor_id == donor_id:
                out.append(ir.to_dict())
        out.sort(key=lambda d: d.get("provenance", {}).get("created_at", ""))
        return out

    def get_receipt_detail(self, donor_id: str, receipt_id: str) -> dict[str, Any]:
        """Full donor-facing UOF (or impact) receipt with explanations + lineage."""
        self._require_donor(donor_id)
        if receipt_id in self.ledger.receipts:
            r = self.ledger.receipts[receipt_id]
            if r.donor_id != donor_id:
                raise NotFoundError(f"receipt not found: {receipt_id}")
            detail = r.to_dict()
            detail["attribution_explanation"] = attribution_explanation(
                r.attribution_method
            )
            detail["remaining_designated_balance"] = str(r.remaining_designated_balance)
            detail["correction_history"] = self.correction_history(donor_id, receipt_id)
            detail["evidence_attachments"] = self.evidence_safe_attachments(
                donor_id, receipt_id
            )
            detail["balances_for_allocation"] = [
                b.to_dict()
                for b in self.allocation_balances(donor_id)
                if b.allocation_id == r.allocation_id
            ]
            return detail
        if receipt_id in self.ws.impact_receipts:
            ir = self.ws.impact_receipts[receipt_id]
            if ir.donor_id != donor_id:
                raise NotFoundError(f"receipt not found: {receipt_id}")
            detail = ir.to_dict()
            detail["attribution_explanation"] = attribution_explanation(
                ir.attribution_method
            )
            detail["correction_history"] = []
            detail["evidence_attachments"] = []
            return detail
        raise NotFoundError(f"receipt not found: {receipt_id}")

    def correction_history(self, donor_id: str, receipt_id: str) -> list[dict[str, Any]]:
        """Chain of correction receipts that correct this receipt (or are prior)."""
        self._require_donor(donor_id)
        chain: list[dict[str, Any]] = []
        # Corrections that point at this receipt
        for r in self.ledger.receipts.values():
            if r.donor_id != donor_id:
                continue
            if r.corrects_receipt_id == receipt_id or (
                r.corrected and r.receipt_id == receipt_id
            ):
                chain.append(
                    {
                        "receipt_id": r.receipt_id,
                        "correction_kind": r.correction_kind,
                        "corrects_receipt_id": r.corrects_receipt_id,
                        "attributed_amount": str(r.attributed_amount),
                        "created_at": r.created_at,
                        "verification_state": r.verification_state,
                        "receipt_hash": r.receipt_hash,
                    }
                )
        # If this is itself a correction, include the prior receipt pointer
        root = self.ledger.receipts.get(receipt_id)
        if root and root.corrects_receipt_id:
            prior = self.ledger.receipts.get(root.corrects_receipt_id)
            if prior and prior.donor_id == donor_id:
                chain.insert(
                    0,
                    {
                        "receipt_id": prior.receipt_id,
                        "correction_kind": None,
                        "corrects_receipt_id": None,
                        "attributed_amount": str(prior.attributed_amount),
                        "created_at": prior.created_at,
                        "verification_state": prior.verification_state,
                        "receipt_hash": prior.receipt_hash,
                        "role": "original",
                    },
                )
        chain.sort(key=lambda d: d.get("created_at") or "")
        return chain

    def evidence_safe_attachments(
        self, donor_id: str, receipt_id: str
    ) -> list[dict[str, Any]]:
        """Donor-visible evidence refs only — no internal paths or non-visible items."""
        self._require_donor(donor_id)
        r = self.ledger.receipts.get(receipt_id)
        if r is None or r.donor_id != donor_id:
            return []
        out: list[dict[str, Any]] = []
        for ev in self.ledger.evidence.values():
            if ev.expense_id != r.expenditure_expense_id:
                continue
            if not ev.donor_visible:
                continue
            out.append(
                {
                    "id": ev.id,
                    "kind": ev.kind,
                    "summary": ev.summary,
                    "donor_visible": True,
                    # Host may resolve object storage key: evidence/{id}
                    "object_key": f"evidence/{ev.id}",
                }
            )
        if r.evidence_summary and not out:
            out.append(
                {
                    "id": None,
                    "kind": "summary",
                    "summary": r.evidence_summary,
                    "donor_visible": True,
                    "object_key": None,
                }
            )
        return out

    def donor_dashboard(self, donor_id: str) -> dict[str, Any]:
        """Composite Phase 2 read model."""
        self._require_donor(donor_id)
        balances = self.allocation_balances(donor_id)
        return {
            "organization_id": self.ledger.organization.id,
            "donor_id": donor_id,
            "allocations": [b.to_dict() for b in balances],
            "timeline": [e.to_dict() for e in self.fund_timeline(donor_id)],
            "receipts": self.list_receipts(donor_id),
            "attribution_methods_explained": ATTRIBUTION_EXPLANATIONS,
        }


# Human-readable attribution copy (v0.7 donor experience)
ATTRIBUTION_EXPLANATIONS: dict[str, str] = {
    "DIRECT_RESTRICTED": (
        "Your gift was restricted to this fund and this purchase used that designation "
        "directly."
    ),
    "PRO_RATA_POOL": (
        "Your gift shared a pool with other donors. The amount shown is your proportional "
        "share of the pool used for this purchase."
    ),
    "FIFO_ALLOCATION": (
        "Gifts to this fund are used first-in, first-out. This purchase drew from the "
        "oldest remaining designated balance, including yours as applicable."
    ),
    "COHORT_ALLOCATION": (
        "Your gift was part of a cohort that jointly funded this activity. The amount "
        "reflects the cohort allocation rules."
    ),
    "ASSET_SPONSORSHIP": (
        "Your gift is linked to a funded asset (equipment or facility). This receipt "
        "shows use associated with that asset."
    ),
    "EXPENSE_BACKED": (
        "This amount is backed by a verified expense recorded in the organization ledger."
    ),
    "MANUAL_APPROVED": (
        "Finance staff approved a manual attribution under organization policy."
    ),
    "NONE": "No individual donor attribution applies to this item.",
}


def attribution_explanation(method: str) -> str:
    return ATTRIBUTION_EXPLANATIONS.get(
        method,
        f"Attributed using method {method} under organization policy.",
    )
