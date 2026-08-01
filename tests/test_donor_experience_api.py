"""Donor experience API: receipts, timeline, balances, corrections, prefs."""

from __future__ import annotations

from decimal import Decimal

import pytest

from impact_relay.auth.principal import principal_from_fixture
from impact_relay.auth.roles import Role
from impact_relay.auth.rbac import AuthorizationError
from impact_relay.donor import DonorExperienceAPI, open_donor_api
from impact_relay.domain.types import (
    NotificationChannel,
    NotificationIntentStatus,
    NotificationMessageClass,
)
from impact_relay.domain.notifications import NotificationService
from impact_relay.domain.types import NotificationPreference
from impact_relay.notifications import FixtureEmailAdapter
from impact_relay.pilot import run_pilot
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID


def _api() -> tuple[DonorExperienceAPI, str, str]:
    ledger, receipts = run_pilot()
    ws = TenantWorkspace(ledger.organization, ledger=ledger)
    api = open_donor_api(ws)
    rid = receipts[0].receipt_id
    return api, receipts[0].donor_id, rid


def test_receipt_detail_has_explanation_and_balance() -> None:
    api, donor_id, rid = _api()
    detail = api.get_receipt(donor_id, rid)
    assert detail["receipt_id"] == rid
    assert "attribution_explanation" in detail
    assert "DIRECT" in detail["attribution"]["method"] or detail["attribution"]["method"]
    assert detail["remaining_designated_balance"] is not None
    assert "evidence_attachments" in detail
    assert "correction_history" in detail


def test_fund_timeline_and_balances() -> None:
    api, donor_id, _rid = _api()
    timeline = api.fund_timeline(donor_id)
    assert any(e["kind"] in ("DONATION_RECEIVED", "USE_OF_FUNDS") for e in timeline)
    balances = api.allocation_balances(donor_id)
    assert balances
    assert Decimal(balances[0]["remaining"]) >= 0


def test_correction_history_after_reverse() -> None:
    ledger, receipts = run_pilot()
    rid = receipts[0].receipt_id
    donor_id = receipts[0].donor_id
    ledger.reverse_expense(
        "exp_soldering_842",
        actor="finance.operator@hackersdojo.example",
        reason="void for test",
    )
    api = open_donor_api(TenantWorkspace(ledger.organization, ledger=ledger))
    hist = api.correction_history(donor_id, rid)
    assert hist
    assert any(h.get("correction_kind") == "REVERSAL" for h in hist)


def test_notification_preferences_and_quiet_hours() -> None:
    ledger, receipts = run_pilot()
    ws = TenantWorkspace(ledger.organization, ledger=ledger)
    api = open_donor_api(ws)
    donor_id = receipts[0].donor_id
    api.set_notification_preference(
        donor_id,
        channel="EMAIL",
        enabled=True,
        topics=["MONEY_USED", "CORRECTION"],
        quiet_hours_start="00:00",
        quiet_hours_end="23:59",
    )
    prefs = api.get_notification_preferences(donor_id)
    assert prefs and prefs[0]["quiet_hours_start"] == "00:00"

    # Consent required for delivery path
    from impact_relay.domain.types import ConsentRecord
    from impact_relay.agents.types import utc_now_iso

    ns = NotificationService(ws, adapters={NotificationChannel.EMAIL: FixtureEmailAdapter()})
    ns.record_consent(
        ConsentRecord(
            donor_id=donor_id,
            organization_id=ledger.organization.id,
            channel=NotificationChannel.EMAIL,
            granted=True,
            provenance="fixture",
            recorded_at=utc_now_iso(),
        )
    )
    # Re-set pref with quiet hours covering now
    ns.set_preference(
        NotificationPreference(
            donor_id=donor_id,
            organization_id=ledger.organization.id,
            channel=NotificationChannel.EMAIL,
            enabled=True,
            topics=("MONEY_USED", "CORRECTION"),
            quiet_hours_start="00:00",
            quiet_hours_end="23:59",
        )
    )
    intent = ns.evaluate_for_use_of_funds(receipts[0].receipt_id, deliver=True)
    assert intent.status == NotificationIntentStatus.DEFERRED_QUIET_HOURS


def test_staff_principal_can_read_donor() -> None:
    api, donor_id, rid = _api()
    staff = principal_from_fixture(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        email="auditor@hackersdojo.example",
        roles=[Role.AUDITOR],
    )
    detail = api.get_receipt(donor_id, rid, principal=staff)
    assert detail["receipt_id"] == rid


def test_donor_principal_wrong_id_denied() -> None:
    from impact_relay.auth.principal import Principal

    api, donor_id, rid = _api()
    base = principal_from_fixture(
        tenant_id=CANONICAL_PILOT_TENANT_ID,
        email="alice@example.com",
        roles=[Role.DONOR],
    )
    donor = Principal(
        subject=base.subject,
        tenant_id=base.tenant_id,
        email=base.email,
        roles=base.roles,
        raw_claims={"donor_id": "someone_else"},
    )
    with pytest.raises(AuthorizationError):
        api.get_receipt(donor_id, rid, principal=donor)
