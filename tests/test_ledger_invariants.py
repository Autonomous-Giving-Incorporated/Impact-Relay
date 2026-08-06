"""Invariant and negative-path tests against the shipped Ledger API."""

from __future__ import annotations

from decimal import Decimal

import pytest

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.types import (
    Allocation,
    AttributionError,
    AttributionMethod,
    Donation,
    Donor,
    Expense,
    ExpenseState,
    InvariantError,
    Organization,
    RestrictionType,
    StateError,
)


def _ledger() -> Ledger:
    org = Organization(id="org_t", name="Test Org", policy_version="v1.0")
    led = Ledger(org)
    led.register_donor(Donor(id="d1", organization_id="org_t", display_name="D1"))
    led.register_allocation(
        Allocation(
            id="a1",
            organization_id="org_t",
            name="Fund A",
            purpose="test",
            restriction_type=RestrictionType.DONOR_RESTRICTED,
        )
    )
    led.import_donation(
        Donation(
            id="don1",
            organization_id="org_t",
            donor_id="d1",
            amount=Decimal("100.00"),
            currency="USD",
            cleared=True,
            external_source_id="ext1",
            received_at="2026-01-01",
        )
    )
    led.assign_donation_allocation(donation_id="don1", allocation_id="a1", amount=Decimal("100.00"))
    return led


def test_allocation_cannot_exceed_cleared_donation() -> None:
    led = _ledger()
    with pytest.raises(InvariantError, match="exceed cleared"):
        led.assign_donation_allocation(
            donation_id="don1", allocation_id="a1", amount=Decimal("0.01")
        )


def test_cannot_allocate_uncleared_donation() -> None:
    org = Organization(id="org_t", name="Test Org")
    led = Ledger(org)
    led.register_donor(Donor(id="d1", organization_id="org_t", display_name="D1"))
    led.register_allocation(
        Allocation(
            id="a1",
            organization_id="org_t",
            name="Fund A",
            purpose="test",
            restriction_type=RestrictionType.UNRESTRICTED,
        )
    )
    led.import_donation(
        Donation(
            id="don_pending",
            organization_id="org_t",
            donor_id="d1",
            amount=Decimal("50.00"),
            currency="USD",
            cleared=False,
            external_source_id="ext2",
            received_at="2026-01-02",
        )
    )
    with pytest.raises(StateError, match="uncleared"):
        led.assign_donation_allocation(
            donation_id="don_pending", allocation_id="a1", amount=Decimal("50.00")
        )


def test_expense_allocations_must_sum_to_expense_amount_on_approve() -> None:
    led = _ledger()
    led.import_expense(
        Expense(
            id="e1",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("40.00"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="tools",
            state=ExpenseState.IMPORTED,
        )
    )
    # Manually plant a bad split by using allocate then mutating store is not possible;
    # allocate_expense_splits enforces sum. Force bad state via partial allocate + approve.
    led.allocate_expense(expense_id="e1", allocation_id="a1", amount=Decimal("40.00"))
    # Tamper: replace with under-allocation to prove approve enforces invariant on shipped path.
    ea_id = next(iter(led.expense_allocations))
    from impact_relay.domain.types import ExpenseAllocation

    bad = ExpenseAllocation(id=ea_id, expense_id="e1", allocation_id="a1", amount=Decimal("10.00"))
    led.expense_allocations[ea_id] = bad
    with pytest.raises(InvariantError, match="must equal expense amount"):
        led.approve_expense("e1", approved_by="finance")


def test_restricted_balance_cannot_go_negative_on_approve() -> None:
    led = _ledger()
    led.import_expense(
        Expense(
            id="e_big",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("100.01"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="overspend",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(expense_id="e_big", allocation_id="a1", amount=Decimal("100.01"))
    with pytest.raises(InvariantError, match="would go negative"):
        led.approve_expense("e_big", approved_by="finance")


def test_verified_receipt_blocked_for_draft_and_pending() -> None:
    led = _ledger()
    for state, eid in (
        (ExpenseState.DRAFT, "e_draft"),
        (ExpenseState.IMPORTED, "e_imp"),
        (ExpenseState.APPROVAL_PENDING, "e_pend"),
    ):
        led.import_expense(
            Expense(
                id=eid,
                organization_id="org_t",
                vendor="V",
                amount=Decimal("10.00"),
                currency="USD",
                purchase_date="2026-02-01",
                category="TOOLS",
                description="x",
                state=ExpenseState.DRAFT if state == ExpenseState.DRAFT else ExpenseState.IMPORTED,
            )
        )
        if state != ExpenseState.DRAFT:
            led.allocate_expense(expense_id=eid, allocation_id="a1", amount=Decimal("10.00"))
        # APPROVAL_PENDING after allocate; DRAFT stays draft without allocate.
        if state == ExpenseState.APPROVAL_PENDING:
            assert led.expenses[eid].state == ExpenseState.APPROVAL_PENDING
        with pytest.raises(StateError, match="APPROVED or RECONCILED"):
            # Attribution without method would also fail; test state gate first with a
            # planted attribution only if we could — publish checks state before needing
            # valid attr if we call publish; it checks state first.
            led.publish_use_of_funds_receipt(
                expense_id=eid,
                donation_id="don1",
                allocation_id="a1",
                actor="finance",
            )


def test_attribution_none_rejected() -> None:
    led = _ledger()
    led.import_expense(
        Expense(
            id="e1",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("10.00"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="x",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(expense_id="e1", allocation_id="a1", amount=Decimal("10.00"))
    with pytest.raises(AttributionError, match=r"disallowed|phantom"):
        led.attribute_donor_to_expense(
            donor_id="d1",
            donation_id="don1",
            expense_id="e1",
            allocation_id="a1",
            method=AttributionMethod.NONE,
        )


def test_receipt_requires_attribution_record() -> None:
    led = _ledger()
    led.import_expense(
        Expense(
            id="e1",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("10.00"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="x",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(expense_id="e1", allocation_id="a1", amount=Decimal("10.00"))
    led.approve_expense("e1", approved_by="finance")
    with pytest.raises(AttributionError, match="no attribution"):
        led.publish_use_of_funds_receipt(
            expense_id="e1",
            donation_id="don1",
            allocation_id="a1",
            actor="finance",
        )


def test_silent_receipt_mutation_forbidden() -> None:
    led = _ledger()
    with pytest.raises(StateError, match="silent mutation"):
        led.mutate_receipt("any")


def test_silent_approved_expense_mutation_forbidden() -> None:
    led = _ledger()
    led.import_expense(
        Expense(
            id="e1",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("10.00"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="x",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(expense_id="e1", allocation_id="a1", amount=Decimal("10.00"))
    led.approve_expense("e1", approved_by="finance")
    with pytest.raises(StateError, match=r"silent mutation|forbidden"):
        led.mutate_approved_expense("e1", amount=Decimal("1.00"))


def test_donor_attribution_cannot_exceed_donation_allocation_across_expenses() -> None:
    """Two DIRECT_RESTRICTED attrs of 60+60 on a 100 donation must fail at second attr.

    Fund has capacity from a second donor so expense approvals succeed; the failure
    is the donor-level invariant via the public Ledger API.
    """
    org = Organization(id="org_t", name="Test Org", policy_version="v1.0")
    led = Ledger(org)
    led.register_donor(Donor(id="d1", organization_id="org_t", display_name="Primary"))
    led.register_donor(Donor(id="d2", organization_id="org_t", display_name="Pool filler"))
    led.register_allocation(
        Allocation(
            id="a1",
            organization_id="org_t",
            name="Fund A",
            purpose="test",
            restriction_type=RestrictionType.DONOR_RESTRICTED,
        )
    )
    led.import_donation(
        Donation(
            id="don_primary",
            organization_id="org_t",
            donor_id="d1",
            amount=Decimal("100.00"),
            currency="USD",
            cleared=True,
            external_source_id="p1",
            received_at="2026-01-01",
        )
    )
    led.assign_donation_allocation(
        donation_id="don_primary", allocation_id="a1", amount=Decimal("100.00")
    )
    led.import_donation(
        Donation(
            id="don_filler",
            organization_id="org_t",
            donor_id="d2",
            amount=Decimal("100.00"),
            currency="USD",
            cleared=True,
            external_source_id="p2",
            received_at="2026-01-01",
        )
    )
    led.assign_donation_allocation(
        donation_id="don_filler", allocation_id="a1", amount=Decimal("100.00")
    )

    for eid, amt in (("e1", "60.00"), ("e2", "60.00")):
        led.import_expense(
            Expense(
                id=eid,
                organization_id="org_t",
                vendor="V",
                amount=Decimal(amt),
                currency="USD",
                purchase_date="2026-02-01",
                category="TOOLS",
                description=eid,
                state=ExpenseState.IMPORTED,
            )
        )
        led.allocate_expense(expense_id=eid, allocation_id="a1", amount=Decimal(amt))
        led.approve_expense(eid, approved_by="finance")

    led.attribute_donor_to_expense(
        donor_id="d1",
        donation_id="don_primary",
        expense_id="e1",
        allocation_id="a1",
        method=AttributionMethod.DIRECT_RESTRICTED,
        attributed_amount=Decimal("60.00"),
    )
    r1 = led.publish_use_of_funds_receipt(
        expense_id="e1",
        donation_id="don_primary",
        allocation_id="a1",
        actor="finance",
    )
    assert r1.remaining_designated_balance == Decimal("40.00")
    assert r1.remaining_designated_balance >= Decimal("0.00")

    with pytest.raises(InvariantError, match="exceed donation allocation"):
        led.attribute_donor_to_expense(
            donor_id="d1",
            donation_id="don_primary",
            expense_id="e2",
            allocation_id="a1",
            method=AttributionMethod.DIRECT_RESTRICTED,
            attributed_amount=Decimal("60.00"),
        )

    # No second receipt; donor remaining never goes negative via public path.
    assert led.donor_remaining_on_allocation("don_primary", "a1") == Decimal("40.00")
    live = [r for r in led.receipts.values() if not r.corrected and r.donation_id == "don_primary"]
    assert len(live) == 1
    assert live[0].receipt_id == r1.receipt_id
    assert all(r.remaining_designated_balance >= Decimal("0.00") for r in live)


def test_same_expense_reattribute_replaces_prior_amount() -> None:
    """Re-attribute on the same expense+donation+allocation replaces, not stacks."""
    led = _ledger()
    led.import_expense(
        Expense(
            id="e1",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("40.00"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="x",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(expense_id="e1", allocation_id="a1", amount=Decimal("40.00"))
    led.approve_expense("e1", approved_by="finance")
    led.attribute_donor_to_expense(
        donor_id="d1",
        donation_id="don1",
        expense_id="e1",
        allocation_id="a1",
        method=AttributionMethod.DIRECT_RESTRICTED,
        attributed_amount=Decimal("25.00"),
    )
    replaced = led.attribute_donor_to_expense(
        donor_id="d1",
        donation_id="don1",
        expense_id="e1",
        allocation_id="a1",
        method=AttributionMethod.DIRECT_RESTRICTED,
        attributed_amount=Decimal("40.00"),
    )
    assert replaced.attributed_amount == Decimal("40.00")
    receipt = led.publish_use_of_funds_receipt(
        expense_id="e1",
        donation_id="don1",
        allocation_id="a1",
        actor="finance",
    )
    # If amounts stacked (25+40), remaining would be 35; replace leaves 60.
    assert receipt.attributed_amount == Decimal("40.00")
    assert receipt.remaining_designated_balance == Decimal("60.00")
    assert receipt.remaining_designated_balance >= Decimal("0.00")


def test_double_publish_same_triple_rejected() -> None:
    led = _ledger()
    led.import_expense(
        Expense(
            id="e1",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("10.00"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="x",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(expense_id="e1", allocation_id="a1", amount=Decimal("10.00"))
    led.approve_expense("e1", approved_by="finance")
    led.attribute_donor_to_expense(
        donor_id="d1",
        donation_id="don1",
        expense_id="e1",
        allocation_id="a1",
        method=AttributionMethod.DIRECT_RESTRICTED,
        attributed_amount=Decimal("10.00"),
    )
    first = led.publish_use_of_funds_receipt(
        expense_id="e1",
        donation_id="don1",
        allocation_id="a1",
        actor="finance",
        created_at="2026-02-02T00:00:00+00:00",
    )
    with pytest.raises(StateError, match="already published"):
        led.publish_use_of_funds_receipt(
            expense_id="e1",
            donation_id="don1",
            allocation_id="a1",
            actor="finance",
            created_at="2026-02-02T00:00:00+00:00",
        )
    live = [r for r in led.receipts.values() if not r.corrected]
    assert len(live) == 1
    assert live[0].receipt_id == first.receipt_id
    assert live[0].receipt_hash == first.receipt_hash
