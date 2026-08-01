"""Phases 2–6: donor reads, notifications, impact, multi-tenant, multi-stage pilot."""

from __future__ import annotations

from decimal import Decimal

import pytest

from impact_relay.domain.impact import ImpactService
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.notifications import NotificationService
from impact_relay.domain.tenant import Platform, TenantWorkspace
from impact_relay.domain.types import (
    Allocation,
    AssetLifecycle,
    AttributionMethod,
    ConsentRecord,
    Donation,
    Donor,
    Expense,
    ExpenseState,
    FundedAsset,
    ImpactEvent,
    ImpactEventState,
    NotificationChannel,
    NotificationIntentStatus,
    NotificationMessageClass,
    NotificationPreference,
    Organization,
    Program,
    RestrictionType,
    StateError,
    TenantIsolationError,
)
from impact_relay.pilot import run_all_phases_pilot, run_pilot


def _hd_workspace() -> TenantWorkspace:
    """Minimal HD-like workspace with verified UOF for alice."""
    org = Organization(id="org_hd", name="HD", policy_version="v1.0")
    ws = TenantWorkspace(org)
    led = ws.ledger
    led.register_donor(Donor(id="donor_alice", organization_id="org_hd", display_name="A"))
    led.register_allocation(
        Allocation(
            id="alloc_hw",
            organization_id="org_hd",
            name="Hardware Fund",
            purpose="tools",
            restriction_type=RestrictionType.DONOR_RESTRICTED,
        )
    )
    led.import_donation(
        Donation(
            id="don1",
            organization_id="org_hd",
            donor_id="donor_alice",
            amount=Decimal("1000.00"),
            currency="USD",
            cleared=True,
            external_source_id="x1",
            received_at="2026-07-01",
        )
    )
    led.assign_donation_allocation(
        donation_id="don1", allocation_id="alloc_hw", amount=Decimal("1000.00")
    )
    led.import_expense(
        Expense(
            id="exp1",
            organization_id="org_hd",
            vendor="V",
            amount=Decimal("842.17"),
            currency="USD",
            purchase_date="2026-08-18",
            category="CLASSROOM_HARDWARE",
            description="Soldering stations",
            state=ExpenseState.IMPORTED,
        )
    )
    led.allocate_expense(
        expense_id="exp1", allocation_id="alloc_hw", amount=Decimal("842.17")
    )
    led.approve_expense("exp1", approved_by="finance")
    led.reconcile_expense("exp1", actor="finance")
    led.attribute_donor_to_expense(
        donor_id="donor_alice",
        donation_id="don1",
        expense_id="exp1",
        allocation_id="alloc_hw",
        method=AttributionMethod.DIRECT_RESTRICTED,
        attributed_amount=Decimal("842.17"),
    )
    led.publish_use_of_funds_receipt(
        expense_id="exp1",
        donation_id="don1",
        allocation_id="alloc_hw",
        actor="finance",
        created_at="2026-08-20T12:00:00+00:00",
    )
    return ws


def test_phase2_donor_balances_timeline_and_receipt_detail() -> None:
    ws = _hd_workspace()
    reads = ws.donor_reads()
    balances = reads.allocation_balances("donor_alice")
    assert len(balances) == 1
    b = balances[0]
    assert b.allocation_name == "Hardware Fund"
    assert b.designated_total == Decimal("1000.00")
    assert b.used == Decimal("842.17")
    assert b.remaining == Decimal("157.83")
    assert b.pending_unreconciled == Decimal("0.00")

    timeline = reads.fund_timeline("donor_alice")
    kinds = {e.kind for e in timeline}
    assert "DONATION_RECEIVED" in kinds
    assert "ALLOCATION_ASSIGNED" in kinds
    assert "USE_OF_FUNDS" in kinds

    receipts = reads.list_receipts("donor_alice")
    assert len(receipts) == 1
    detail = reads.get_receipt_detail("donor_alice", receipts[0]["receipt_id"])
    assert detail["attribution"]["method"] == "DIRECT_RESTRICTED"
    assert detail["expenditure"]["verification_state"] in {"APPROVED", "RECONCILED"}
    assert Decimal(detail["remaining_designated_balance"]) == Decimal("157.83")


def test_phase2_read_does_not_mutate_receipts() -> None:
    ws = _hd_workspace()
    rid = next(iter(ws.ledger.receipts))
    before = ws.ledger.get_receipt_snapshot(rid)
    ws.donor_reads().donor_dashboard("donor_alice")
    assert ws.ledger.get_receipt_snapshot(rid) == before


def test_phase4_impact_publish_requires_verification() -> None:
    ws = _hd_workspace()
    impact = ws.impact()
    impact.register_program(
        Program(
            id="prog1",
            organization_id="org_hd",
            name="Electronics",
            active=True,
        )
    )
    impact.register_funded_asset(
        FundedAsset(
            id="asset1",
            organization_id="org_hd",
            name="Stations",
            expense_id="exp1",
            allocation_id="alloc_hw",
            lifecycle=AssetLifecycle.DEPLOYED,
        )
    )
    impact.submit_impact_event(
        ImpactEvent(
            id="iev1",
            organization_id="org_hd",
            program_id="prog1",
            event_type="CLASS_HELD",
            event_date="2026-09-02",
            participants=18,
            state=ImpactEventState.SUBMITTED,
            funded_asset_ids=("asset1",),
            expense_ids=("exp1",),
            description="class",
        )
    )
    with pytest.raises(StateError, match="VERIFIED"):
        impact.publish_impact_receipts("iev1", actor="reviewer")

    impact.verify_impact_event("iev1", verified_by="reviewer")
    receipts = impact.publish_impact_receipts(
        "iev1", actor="reviewer", created_at="2026-09-02T18:00:00+00:00"
    )
    assert len(receipts) == 1
    assert receipts[0].type == "IMPACT"
    assert receipts[0].participants == 18
    assert receipts[0].evidence_state == "VERIFIED"
    assert receipts[0].receipt_hash

    # Timeline includes impact
    timeline = ws.donor_reads().fund_timeline("donor_alice")
    assert any(e.kind == "IMPACT" for e in timeline)


def test_phase3_consent_blocks_and_dedup() -> None:
    ws = _hd_workspace()
    notify = ws.notifications()
    rid = next(r.receipt_id for r in ws.ledger.receipts.values() if not r.corrected)

    # No consent → blocked
    blocked = notify.evaluate_for_use_of_funds(rid, channel=NotificationChannel.EMAIL)
    assert blocked.status == NotificationIntentStatus.BLOCKED_NO_CONSENT

    # Same dedup key returns same intent (no second)
    again = notify.evaluate_for_use_of_funds(rid, channel=NotificationChannel.EMAIL)
    assert again.id == blocked.id
    assert sum(1 for i in ws.intents.values()) == 1

    # Grant consent + preference → deliver
    notify.record_consent(
        ConsentRecord(
            donor_id="donor_alice",
            organization_id="org_hd",
            channel=NotificationChannel.EMAIL,
            granted=True,
            provenance="test",
            recorded_at="2026-07-01T00:00:00+00:00",
        )
    )
    notify.set_preference(
        NotificationPreference(
            donor_id="donor_alice",
            organization_id="org_hd",
            channel=NotificationChannel.EMAIL,
            enabled=True,
            topics=(NotificationMessageClass.MONEY_USED.value,),
            cadence="immediate",
        )
    )
    # Different channel gets new intent path; same source with email still deduped
    email_same = notify.evaluate_for_use_of_funds(rid, channel=NotificationChannel.EMAIL)
    assert email_same.id == blocked.id  # still blocked status frozen at first create

    # PUSH path: consent + pref → delivered
    notify.record_consent(
        ConsentRecord(
            donor_id="donor_alice",
            organization_id="org_hd",
            channel=NotificationChannel.PUSH,
            granted=True,
            provenance="test",
            recorded_at="2026-07-01T00:00:00+00:00",
        )
    )
    notify.set_preference(
        NotificationPreference(
            donor_id="donor_alice",
            organization_id="org_hd",
            channel=NotificationChannel.PUSH,
            enabled=True,
            topics=(NotificationMessageClass.MONEY_USED.value,),
        )
    )
    push = notify.evaluate_for_use_of_funds(rid, channel=NotificationChannel.PUSH)
    assert push.status == NotificationIntentStatus.DELIVERED
    assert any(d.intent_id == push.id and d.success for d in ws.deliveries.values())

    # Dedup: second PUSH evaluate returns same
    push2 = notify.evaluate_for_use_of_funds(rid, channel=NotificationChannel.PUSH)
    assert push2.id == push.id
    push_intents = [
        i
        for i in ws.intents.values()
        if i.channel == NotificationChannel.PUSH and i.source_id == rid
    ]
    assert len(push_intents) == 1


def test_phase3_correction_intent_after_reversal() -> None:
    ws = _hd_workspace()
    notify = ws.notifications()
    notify.record_consent(
        ConsentRecord(
            donor_id="donor_alice",
            organization_id="org_hd",
            channel=NotificationChannel.EMAIL,
            granted=True,
            provenance="test",
            recorded_at="2026-07-01T00:00:00+00:00",
        )
    )
    prior = next(r for r in ws.ledger.receipts.values() if not r.corrected)
    prior_hash = prior.receipt_hash
    _rev, corrs = ws.ledger.reverse_expense("exp1", actor="finance", reason="void")
    assert corrs
    corr = corrs[0]
    assert ws.ledger.get_receipt(prior.receipt_id).receipt_hash == prior_hash
    intent = notify.evaluate_for_use_of_funds(
        corr.receipt_id, channel=NotificationChannel.EMAIL
    )
    assert intent.message_class == NotificationMessageClass.CORRECTION
    assert intent.source_type == "CORRECTION"
    assert intent.status == NotificationIntentStatus.DELIVERED


def test_multi_tenant_isolation() -> None:
    platform = Platform()
    a = platform.register_organization(Organization(id="org_a", name="A"))
    b = platform.register_organization(Organization(id="org_b", name="B"))
    a.ledger.register_donor(
        Donor(id="donor_a", organization_id="org_a", display_name="A")
    )
    b.ledger.register_donor(
        Donor(id="donor_b", organization_id="org_b", display_name="B")
    )
    # Cross-tenant read denied
    with pytest.raises(TenantIsolationError):
        platform.donor_dashboard("org_b", "donor_a")
    with pytest.raises(TenantIsolationError):
        platform.donor_dashboard("org_a", "donor_b")
    # Donor a does not exist on org b ledger
    with pytest.raises(Exception):
        b.donor_reads().allocation_balances("donor_a")


def test_all_phases_pilot_fixture_happy_path() -> None:
    platform, payload = run_all_phases_pilot()
    primary = payload["primary"]
    assert primary["use_of_funds_receipts"]
    uof = primary["use_of_funds_receipts"][0]
    assert uof["allocation"]["name"]
    assert uof["expenditure"]["verification_state"] in {"APPROVED", "RECONCILED"}
    assert Decimal(uof["remaining_designated_balance"]) >= 0
    assert uof["attribution"]["method"]
    assert uof["receipt_id"]
    assert uof["provenance"]["receipt_hash"]

    assert primary["impact_receipts"]
    imp = primary["impact_receipts"][0]
    assert imp["type"] == "IMPACT"
    assert imp["impact"]["evidence_state"] == "VERIFIED"
    assert imp["provenance"]["receipt_hash"]

    assert primary["notification_intents"]
    assert any(
        i["status"] in {"DELIVERED", "BLOCKED_NO_CONSENT", "BLOCKED_PREFERENCE"}
        for i in primary["notification_intents"]
    )
    # Alice consented → at least one delivery success expected for UOF/impact email
    assert any(d["success"] for d in primary["notification_deliveries"])

    dash = primary["donor_dashboard_alice"]
    assert dash is not None
    assert dash["allocations"]
    assert any(e["kind"] == "USE_OF_FUNDS" for e in dash["timeline"])
    assert any(e["kind"] == "IMPACT" for e in dash["timeline"])

    # Two orgs isolated
    assert set(payload["organizations"]) == {
        "org_hacker_dojo",
        "org_other_makerspace",
    }
    with pytest.raises(TenantIsolationError):
        platform.donor_dashboard("org_other_makerspace", "donor_alice")


def test_hd_ir_001_still_works_via_run_pilot() -> None:
    ledger, receipts = run_pilot()
    assert len(receipts) == 1
    assert receipts[0].remaining_designated_balance == Decimal("157.83")


def test_cli_all_phases(capsys) -> None:
    from impact_relay.cli import main

    code = main(["--all-phases"])
    assert code == 0
    out = capsys.readouterr().out
    import json

    payload = json.loads(out)
    assert payload["primary"]["use_of_funds_receipts"]
    assert payload["primary"]["impact_receipts"]
    assert payload["primary"]["notification_intents"]
