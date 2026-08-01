"""Happy-path receipt generation and append-only correction tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from impact_relay.domain.ledger import Ledger
from impact_relay.domain.types import (
    Allocation,
    AttributionMethod,
    Donation,
    Donor,
    Expense,
    ExpenseState,
    Organization,
    RestrictionType,
    StateError,
)
from impact_relay.pilot import run_pilot


def test_pilot_fixture_produces_verified_use_of_funds_receipt() -> None:
    ledger, receipts = run_pilot()
    assert len(receipts) == 1
    r = receipts[0]
    assert r.type == "USE_OF_FUNDS"
    assert r.allocation_name == "Community Hardware Fund"
    assert r.gross_amount == Decimal("842.17")
    assert r.attributed_amount == Decimal("842.17")
    assert r.purchase_date == "2026-08-18"
    assert r.category == "CLASSROOM_HARDWARE"
    assert r.description
    assert r.verification_state in {"APPROVED", "RECONCILED"}
    assert r.remaining_designated_balance == Decimal("157.83")  # 1000 - 842.17
    assert r.attribution_method == AttributionMethod.DIRECT_RESTRICTED.value
    assert r.receipt_id
    assert r.receipt_hash
    assert len(r.receipt_hash) == 64
    assert r.approved_by
    assert r.policy_version == "v1.0"
    # Snapshot immutability store
    snap = ledger.get_receipt_snapshot(r.receipt_id)
    assert snap["allocation"]["name"] == "Community Hardware Fund"
    assert snap["provenance"]["receipt_hash"] == r.receipt_hash


def test_pro_rata_pool_attribution() -> None:
    org = Organization(id="org_t", name="Test", policy_version="v1.0")
    led = Ledger(org)
    led.register_donor(Donor(id="d1", organization_id="org_t", display_name="A"))
    led.register_donor(Donor(id="d2", organization_id="org_t", display_name="B"))
    led.register_allocation(
        Allocation(
            id="a1",
            organization_id="org_t",
            name="Pool",
            purpose="p",
            restriction_type=RestrictionType.DONOR_RESTRICTED,
        )
    )
    for did, donor, amt in (
        ("don1", "d1", "100.00"),
        ("don2", "d2", "300.00"),
    ):
        led.import_donation(
            Donation(
                id=did,
                organization_id="org_t",
                donor_id=donor,
                amount=Decimal(amt),
                currency="USD",
                cleared=True,
                external_source_id=f"x-{did}",
                received_at="2026-01-01",
            )
        )
        led.assign_donation_allocation(
            donation_id=did, allocation_id="a1", amount=Decimal(amt)
        )
    led.import_expense(
        Expense(
            id="e1",
            organization_id="org_t",
            vendor="V",
            amount=Decimal("80.00"),
            currency="USD",
            purchase_date="2026-02-01",
            category="TOOLS",
            description="shared tools",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(expense_id="e1", allocation_id="a1", amount=Decimal("80.00"))
    led.approve_expense("e1", approved_by="finance")
    led.reconcile_expense("e1", actor="finance")

    a1 = led.attribute_donor_to_expense(
        donor_id="d1",
        donation_id="don1",
        expense_id="e1",
        allocation_id="a1",
        method=AttributionMethod.PRO_RATA_POOL,
    )
    # d1 is 100/400 = 25% of 80 = 20.00
    assert a1.attributed_amount == Decimal("20.00")
    r = led.publish_use_of_funds_receipt(
        expense_id="e1",
        donation_id="don1",
        allocation_id="a1",
        actor="finance",
        created_at="2026-02-02T00:00:00+00:00",
    )
    assert r.attribution_method == "PRO_RATA_POOL"
    assert r.attributed_amount == Decimal("20.00")
    assert r.verification_state == "RECONCILED"
    assert r.remaining_designated_balance == Decimal("80.00")  # 100 - 20


def test_reversal_publishes_correction_without_mutating_prior_receipt() -> None:
    ledger, receipts = run_pilot()
    prior = receipts[0]
    prior_id = prior.receipt_id
    prior_hash = prior.receipt_hash
    prior_snap = ledger.get_receipt_snapshot(prior_id)
    prior_attributed = prior.attributed_amount

    reversed_exp, corrections = ledger.reverse_expense(
        "exp_soldering_842",
        actor="finance.operator@hackersdojo.example",
        reason="Invoice voided by vendor",
    )
    assert reversed_exp.state == ExpenseState.REVERSED
    assert len(corrections) == 1
    corr = corrections[0]
    assert corr.corrected is True
    assert corr.correction_kind == "REVERSAL"
    assert corr.corrects_receipt_id == prior_id
    assert corr.verification_state == "REVERSED"
    assert corr.attributed_amount == Decimal("0.00")
    assert corr.receipt_id != prior_id
    assert corr.receipt_hash != prior_hash

    # Prior receipt object and snapshot unchanged.
    still = ledger.get_receipt(prior_id)
    assert still.receipt_hash == prior_hash
    assert still.attributed_amount == prior_attributed
    assert still.verification_state in {"APPROVED", "RECONCILED"}
    assert ledger.get_receipt_snapshot(prior_id) == prior_snap

    # Balance restored after reversal.
    assert ledger.allocation_remaining_balance("alloc_community_hardware") == Decimal(
        "1500.00"
    )
    assert ledger.donor_remaining_on_allocation(
        "don_1000_alice", "alloc_community_hardware"
    ) == Decimal("1000.00")


def test_supersede_creates_replacement_and_correction() -> None:
    ledger, receipts = run_pilot()
    prior = receipts[0]

    superseded, replacement, corrections = ledger.supersede_expense(
        "exp_soldering_842",
        replacement=Expense(
            id="exp_soldering_corrected",
            organization_id=ledger.organization.id,
            vendor="Example Vendor LLC",
            amount=Decimal("800.00"),
            currency="USD",
            purchase_date="2026-08-18",
            category="CLASSROOM_HARDWARE",
            description="Corrected soldering stations invoice",
            state=ExpenseState.IMPORTED,
            external_source_id="acct_exp_9001b",
        ),
        splits=[("alloc_community_hardware", Decimal("800.00"))],
        actor="finance.operator@hackersdojo.example",
        reason="Amount corrected after rebate",
        approved_by="finance.operator@hackersdojo.example",
    )
    assert superseded.state == ExpenseState.SUPERSEDED
    assert replacement.state == ExpenseState.APPROVED
    assert replacement.supersedes_id == "exp_soldering_842"
    assert len(corrections) == 1
    assert corrections[0].correction_kind == "SUPERSEDE"
    assert corrections[0].corrects_receipt_id == prior.receipt_id
    # Prior receipt still intact
    assert ledger.get_receipt(prior.receipt_id).receipt_hash == prior.receipt_hash


def test_cannot_reallocate_approved_expense() -> None:
    ledger, _ = run_pilot()
    with pytest.raises(StateError, match="approved|reconciled"):
        ledger.allocate_expense(
            expense_id="exp_soldering_842",
            allocation_id="alloc_community_hardware",
            amount=Decimal("842.17"),
        )


def test_receipt_hash_stable_for_fixed_created_at() -> None:
    _, r1 = run_pilot()
    _, r2 = run_pilot()
    # Fixture fixes created_at → same content hash for same economic facts
    assert r1[0].receipt_hash == r2[0].receipt_hash
    assert r1[0].allocation_name == r2[0].allocation_name
    # receipt_id is unique per publish
    assert r1[0].receipt_id != r2[0].receipt_id
