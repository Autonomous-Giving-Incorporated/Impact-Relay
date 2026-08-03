"""Donor-scoped privacy operations.

These helpers cover the library-owned part of data export and deletion workflows.
Financial ledger facts remain immutable for audit and nonprofit accounting duties;
mutable notification preferences/consents and delivery/intention contact state can
be revoked or erased for a donor.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    ConsentRecord,
    NotFoundError,
    NotificationIntentStatus,
    TenantIsolationError,
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value") and not isinstance(value, type):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _dataclass_dict(value: Any) -> dict[str, Any]:
    return _jsonable(asdict(value))


def _assert_donor(ws: TenantWorkspace, donor_id: str) -> None:
    donor = ws.ledger.donors.get(donor_id)
    if donor is None:
        raise NotFoundError(f"donor not found: {donor_id}")
    if donor.organization_id != ws.organization.id:
        raise TenantIsolationError(f"cross-tenant donor access denied: {donor_id}")


@dataclass(frozen=True)
class DonorNotificationEraseReceipt:
    donor_id: str
    organization_id: str
    erased_at: str
    revoked_consents: int
    removed_preferences: int
    removed_intents: int
    removed_deliveries: int
    immutable_ledger_preserved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_dict(self)


def export_donor_data(workspace: TenantWorkspace, donor_id: str) -> dict[str, Any]:
    """Build a donor-scoped portable export from immutable and mutable stores."""

    _assert_donor(workspace, donor_id)
    ledger = workspace.ledger
    reads = workspace.donor_reads()

    donor = ledger.donors[donor_id]
    donations = [d for d in ledger.donations.values() if d.donor_id == donor_id]
    donation_ids = {d.id for d in donations}
    donation_allocations = [
        da for da in ledger.donation_allocations.values() if da.donation_id in donation_ids
    ]
    attributions = [a for a in ledger.attributions.values() if a.donor_id == donor_id]
    receipts = [r for r in ledger.receipts.values() if r.donor_id == donor_id]
    impact_receipts = [r for r in workspace.impact_receipts.values() if r.donor_id == donor_id]
    consents = [c for (did, _channel), c in workspace.consents.items() if did == donor_id]
    preferences = [p for (did, _channel), p in workspace.preferences.items() if did == donor_id]
    intents = [i for i in workspace.intents.values() if i.donor_id == donor_id]
    intent_ids = {i.id for i in intents}
    deliveries = [
        d
        for d in workspace.deliveries.values()
        if d.donor_id == donor_id or d.intent_id in intent_ids
    ]

    return {
        "export_kind": "donor_data_portable_export",
        "schema_version": "v1.0",
        "organization": {
            "id": workspace.organization.id,
            "name": workspace.organization.name,
            "policy_version": workspace.organization.policy_version,
        },
        "donor": _dataclass_dict(donor),
        "ledger": {
            "donations": [_dataclass_dict(d) for d in sorted(donations, key=lambda d: d.id)],
            "donation_allocations": [
                _dataclass_dict(da) for da in sorted(donation_allocations, key=lambda da: da.id)
            ],
            "attributions": [_dataclass_dict(a) for a in sorted(attributions, key=lambda a: a.id)],
            "use_of_funds_receipts": [
                r.to_dict() for r in sorted(receipts, key=lambda r: r.receipt_id)
            ],
            "impact_receipts": [
                r.to_dict() for r in sorted(impact_receipts, key=lambda r: r.receipt_id)
            ],
        },
        "donor_experience": {
            "dashboard": reads.donor_dashboard(donor_id),
            "timeline": [event.to_dict() for event in reads.fund_timeline(donor_id)],
            "allocation_balances": [b.to_dict() for b in reads.allocation_balances(donor_id)],
        },
        "notifications": {
            "consents": [
                _dataclass_dict(c) for c in sorted(consents, key=lambda c: c.channel.value)
            ],
            "preferences": [
                _dataclass_dict(p) for p in sorted(preferences, key=lambda p: p.channel.value)
            ],
            "intents": [_dataclass_dict(i) for i in sorted(intents, key=lambda i: i.id)],
            "deliveries": [_dataclass_dict(d) for d in sorted(deliveries, key=lambda d: d.id)],
        },
        "exported_at": _now_iso(),
    }


def export_donor_data_json(workspace: TenantWorkspace, donor_id: str) -> str:
    """Build a deterministic JSON representation of ``export_donor_data``."""

    return json.dumps(export_donor_data(workspace, donor_id), sort_keys=True, separators=(",", ":"))


def erase_donor_notification_state(
    workspace: TenantWorkspace,
    donor_id: str,
    *,
    actor: str,
    provenance: str,
    erase_history: bool = True,
    revoked_at: str | None = None,
) -> DonorNotificationEraseReceipt:
    """Revoke consent and remove donor mutable notification state.

    Ledger donations, receipts, attribution, and audit facts are preserved. When
    ``erase_history`` is false, historic intent/delivery rows are retained but
    matching intents are marked ``SUPERSEDED`` and consents are stored as revoked.
    """

    _assert_donor(workspace, donor_id)
    if not actor.strip():
        raise ValueError("actor is required")
    if not provenance.strip():
        raise ValueError("provenance is required")

    at = revoked_at or _now_iso()
    consent_keys = [key for key in workspace.consents if key[0] == donor_id]
    preference_keys = [key for key in workspace.preferences if key[0] == donor_id]
    intent_ids = [
        intent_id for intent_id, intent in workspace.intents.items() if intent.donor_id == donor_id
    ]
    intent_id_set = set(intent_ids)
    delivery_ids = [
        delivery_id
        for delivery_id, delivery in workspace.deliveries.items()
        if delivery.donor_id == donor_id or delivery.intent_id in intent_id_set
    ]

    channels = {
        workspace.consents[key].channel for key in consent_keys if key in workspace.consents
    } | {
        workspace.preferences[key].channel
        for key in preference_keys
        if key in workspace.preferences
    }

    removed_preferences = len(preference_keys)
    for key in preference_keys:
        workspace.preferences.pop(key, None)

    revoked_consents = len(channels)
    if erase_history:
        for key in consent_keys:
            workspace.consents.pop(key, None)
    for channel in channels:
        workspace.consents[(donor_id, channel.value)] = ConsentRecord(
            donor_id=donor_id,
            organization_id=workspace.organization.id,
            channel=channel,
            granted=False,
            provenance=f"{provenance}; actor={actor}; privacy_erasure=true",
            recorded_at=at,
        )

    removed_intents = len(intent_ids)
    removed_deliveries = len(delivery_ids)
    if erase_history:
        for delivery_id in delivery_ids:
            workspace.deliveries.pop(delivery_id, None)
        for intent_id in intent_ids:
            intent = workspace.intents.pop(intent_id, None)
            if intent is not None:
                workspace.intents_by_dedup.pop(intent.dedup_key, None)
    else:
        for intent_id in intent_ids:
            intent = workspace.intents.get(intent_id)
            if intent is not None:
                updated = replace(intent, status=NotificationIntentStatus.SUPERSEDED)
                workspace.intents[intent_id] = updated
                workspace.intents_by_dedup[updated.dedup_key] = updated
        removed_intents = 0
        removed_deliveries = 0

    return DonorNotificationEraseReceipt(
        donor_id=donor_id,
        organization_id=workspace.organization.id,
        erased_at=at,
        revoked_consents=revoked_consents,
        removed_preferences=removed_preferences,
        removed_intents=removed_intents,
        removed_deliveries=removed_deliveries,
    )
