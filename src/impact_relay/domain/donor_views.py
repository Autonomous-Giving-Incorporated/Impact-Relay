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
        self._require_donor(donor_id)
        if receipt_id in self.ledger.receipts:
            r = self.ledger.receipts[receipt_id]
            if r.donor_id != donor_id:
                raise NotFoundError(f"receipt not found: {receipt_id}")
            return r.to_dict()
        if receipt_id in self.ws.impact_receipts:
            ir = self.ws.impact_receipts[receipt_id]
            if ir.donor_id != donor_id:
                raise NotFoundError(f"receipt not found: {receipt_id}")
            return ir.to_dict()
        raise NotFoundError(f"receipt not found: {receipt_id}")

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
        }
