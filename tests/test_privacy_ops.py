"""Donor data export and mutable notification-state erasure tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from impact_relay.agents.expense_workflow import run_expense_approval_slice
from impact_relay.agents.types import utc_now_iso
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    ConsentRecord,
    Donor,
    NotFoundError,
    NotificationChannel,
    NotificationIntentStatus,
    NotificationMessageClass,
    NotificationPreference,
    TenantIsolationError,
)
from impact_relay.pilot import build_ledger_from_fixture, load_fixture
from impact_relay.privacy_ops import (
    erase_donor_notification_state,
    export_donor_data,
    export_donor_data_json,
)

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "fixtures" / "expense_intake_batch_v1.json"


def _workspace_with_receipt() -> tuple[TenantWorkspace, str]:
    data = copy.deepcopy(load_fixture())
    data["expenses"] = []
    data["publish"] = []
    ledger = build_ledger_from_fixture(data)
    rows = json.loads(BATCH.read_text(encoding="utf-8"))["expenses"]
    result = run_expense_approval_slice(
        ledger,
        expense_rows=rows,
        human_approver_id="finance.approver@hackersdojo.example",
        approve=True,
        publish_specs=[
            {
                "donor_id": "donor_alice",
                "donation_id": "don_1000_alice",
                "allocation_id": "alloc_community_hardware",
                "attribution_method": "DIRECT_RESTRICTED",
                "attributed_amount": "720.00",
                "created_at": "2026-08-12T12:00:00+00:00",
            }
        ],
        send_email=False,
    )
    return TenantWorkspace(ledger.organization, ledger=ledger), result.receipts[0].receipt_id


def _grant_email(workspace: TenantWorkspace, donor_id: str) -> None:
    workspace.notifications().record_consent(
        ConsentRecord(
            donor_id=donor_id,
            organization_id=workspace.organization.id,
            channel=NotificationChannel.EMAIL,
            granted=True,
            provenance="host://consent/email",
            recorded_at=utc_now_iso(),
        )
    )
    workspace.notifications().set_preference(
        NotificationPreference(
            donor_id=donor_id,
            organization_id=workspace.organization.id,
            channel=NotificationChannel.EMAIL,
            enabled=True,
            topics=("MONEY_USED", "CORRECTION"),
        )
    )


def _deliver_email(workspace: TenantWorkspace, donor_id: str, receipt_id: str) -> None:
    _grant_email(workspace, donor_id)
    intent = workspace.notifications().evaluate_for_use_of_funds(
        receipt_id,
        channel=NotificationChannel.EMAIL,
        deliver=True,
        payload_patch={"email_subject": "Subject", "email_body_text": "Body"},
    )
    assert intent.status == NotificationIntentStatus.DELIVERED


def test_export_donor_data_includes_ledger_reads_and_notification_state() -> None:
    workspace, receipt_id = _workspace_with_receipt()
    _deliver_email(workspace, "donor_alice", receipt_id)

    exported = export_donor_data(workspace, "donor_alice")

    assert exported["export_kind"] == "donor_data_portable_export"
    assert exported["organization"]["id"] == workspace.organization.id
    assert exported["donor"] == {
        "id": "donor_alice",
        "organization_id": workspace.organization.id,
        "display_name": "Alice Patron",
    }
    assert [d["id"] for d in exported["ledger"]["donations"]] == ["don_1000_alice"]
    assert exported["ledger"]["use_of_funds_receipts"][0]["receipt_id"] == receipt_id
    assert exported["donor_experience"]["dashboard"]["donor_id"] == "donor_alice"
    assert exported["donor_experience"]["timeline"]
    assert exported["notifications"]["consents"][0]["channel"] == "EMAIL"
    assert exported["notifications"]["preferences"][0]["enabled"] is True
    assert exported["notifications"]["intents"][0]["status"] == "DELIVERED"
    assert exported["notifications"]["deliveries"][0]["provider"] == "email_fixture"

    encoded = export_donor_data_json(workspace, "donor_alice")
    assert json.loads(encoded)["donor"]["id"] == "donor_alice"


def test_export_donor_data_rejects_unknown_or_cross_tenant_donor() -> None:
    workspace, _receipt_id = _workspace_with_receipt()
    with pytest.raises(NotFoundError, match="donor not found"):
        export_donor_data(workspace, "missing_donor")

    workspace.ledger.donors["intruder"] = Donor(
        id="intruder",
        organization_id="org_other",
        display_name="Intruder",
    )
    with pytest.raises(TenantIsolationError, match="cross-tenant"):
        export_donor_data(workspace, "intruder")


def test_erase_donor_notification_state_removes_mutable_state_but_preserves_ledger() -> None:
    workspace, receipt_id = _workspace_with_receipt()
    _deliver_email(workspace, "donor_alice", receipt_id)
    before_counts = {
        "donors": len(workspace.ledger.donors),
        "donations": len(workspace.ledger.donations),
        "receipts": len(workspace.ledger.receipts),
        "attributions": len(workspace.ledger.attributions),
    }

    receipt = erase_donor_notification_state(
        workspace,
        "donor_alice",
        actor="privacy.officer@example.org",
        provenance="host://privacy/delete-request/123",
        revoked_at="2026-08-20T12:00:00+00:00",
    )

    assert receipt.to_dict() == {
        "donor_id": "donor_alice",
        "organization_id": workspace.organization.id,
        "erased_at": "2026-08-20T12:00:00+00:00",
        "revoked_consents": 1,
        "removed_preferences": 1,
        "removed_intents": 1,
        "removed_deliveries": 1,
        "immutable_ledger_preserved": True,
    }
    assert not workspace.preferences
    assert not workspace.intents
    assert not workspace.intents_by_dedup
    assert not workspace.deliveries
    revoked = workspace.consents[("donor_alice", NotificationChannel.EMAIL.value)]
    assert revoked.granted is False
    assert "privacy_erasure=true" in revoked.provenance
    assert {
        "donors": len(workspace.ledger.donors),
        "donations": len(workspace.ledger.donations),
        "receipts": len(workspace.ledger.receipts),
        "attributions": len(workspace.ledger.attributions),
    } == before_counts


def test_erase_donor_notification_state_can_retain_history_as_superseded() -> None:
    workspace, receipt_id = _workspace_with_receipt()
    _deliver_email(workspace, "donor_alice", receipt_id)

    receipt = erase_donor_notification_state(
        workspace,
        "donor_alice",
        actor="privacy.officer@example.org",
        provenance="host://privacy/opt-out/124",
        erase_history=False,
    )

    assert receipt.removed_intents == 0
    assert receipt.removed_deliveries == 0
    assert len(workspace.deliveries) == 1
    intent = next(iter(workspace.intents.values()))
    assert intent.status == NotificationIntentStatus.SUPERSEDED
    assert (
        workspace.intents_by_dedup[intent.dedup_key].status == NotificationIntentStatus.SUPERSEDED
    )
    assert not workspace.preferences
    assert workspace.consents[("donor_alice", NotificationChannel.EMAIL.value)].granted is False


def test_erase_donor_notification_state_requires_actor_and_provenance() -> None:
    workspace, _receipt_id = _workspace_with_receipt()
    with pytest.raises(ValueError, match="actor"):
        erase_donor_notification_state(workspace, "donor_alice", actor="", provenance="host://p")
    with pytest.raises(ValueError, match="provenance"):
        erase_donor_notification_state(
            workspace, "donor_alice", actor="privacy@example.org", provenance=""
        )
    with pytest.raises(NotFoundError):
        erase_donor_notification_state(
            workspace,
            "missing_donor",
            actor="privacy@example.org",
            provenance="host://p",
        )


def test_privacy_ops_do_not_touch_other_donor_notification_state() -> None:
    workspace, receipt_id = _workspace_with_receipt()
    _deliver_email(workspace, "donor_alice", receipt_id)
    workspace.ledger.register_donor(
        Donor(id="donor_other", organization_id=workspace.organization.id, display_name="Other")
    )
    workspace.notifications().record_consent(
        ConsentRecord(
            donor_id="donor_other",
            organization_id=workspace.organization.id,
            channel=NotificationChannel.EMAIL,
            granted=True,
            provenance="host://consent/email",
            recorded_at=utc_now_iso(),
        )
    )
    workspace.notifications().evaluate_intent(
        donor_id="donor_other",
        channel=NotificationChannel.EMAIL,
        message_class=NotificationMessageClass.DIGEST,
        source_type="DIGEST",
        source_id="digest_1",
        payload={"summary": "digest"},
        deliver=True,
    )

    erase_donor_notification_state(
        workspace,
        "donor_alice",
        actor="privacy.officer@example.org",
        provenance="host://privacy/delete-request/123",
    )

    assert ("donor_other", NotificationChannel.EMAIL.value) in workspace.consents
    assert any(intent.donor_id == "donor_other" for intent in workspace.intents.values())
    assert any(delivery.donor_id == "donor_other" for delivery in workspace.deliveries.values())
