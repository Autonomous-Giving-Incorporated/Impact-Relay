"""HD-IR-006: privacy-safe public IMPACT outcome summaries.

Domain ImpactReceipt objects are donor-specific. Public Pages must never
show donor_id or donation_id. This module collapses verified impact
receipts to one public row per impact event.

`allocationId` is the suite join key shared with Fund-Intel decisions and
AGI public narrative contracts (see Autonomous-Giving-Incorporated
CONTRACT_GOVERNANCE). It is a public allocation identifier, not a donor id.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from impact_relay.domain.types import ImpactReceipt


def impact_receipt_to_event_row(receipt: ImpactReceipt) -> dict[str, Any]:
    """Project one domain IMPACT receipt into an event-level public row."""
    public_id = f"imp_{receipt.receipt_hash[:12]}"
    return {
        "publicId": public_id,
        "impactEventId": receipt.impact_event_id,
        "organizationName": receipt.organization_name,
        "programName": receipt.program_name,
        "allocationId": receipt.allocation_id,
        "allocationName": receipt.allocation_name,
        "eventType": receipt.event_type,
        "eventDate": receipt.event_date[:10] if receipt.event_date else receipt.event_date,
        "participantsPublic": int(receipt.participants),
        "evidenceState": receipt.evidence_state,
        "description": receipt.description,
        "attributionMethod": receipt.attribution_method,
        "receiptHash": receipt.receipt_hash,
        "createdAt": receipt.created_at,
    }


def build_public_impact_export(
    receipts: list[ImpactReceipt],
    *,
    source: str = "domain_impact_receipts",
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Build Pages document: one public outcome per impact event (no donor ids)."""
    by_event: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        row = impact_receipt_to_event_row(receipt)
        event_id = row["impactEventId"]
        # First receipt for an event wins for display fields; keep max participants.
        if event_id not in by_event:
            by_event[event_id] = row
        else:
            existing = by_event[event_id]
            existing["participantsPublic"] = max(
                existing["participantsPublic"], row["participantsPublic"]
            )

    outcomes = sorted(
        by_event.values(),
        key=lambda r: r.get("eventDate") or "",
        reverse=True,
    )

    blob = json.dumps(outcomes)
    for bad in ("donor_id", "donorId", "donation_id", "donationId", "approved_by"):
        if bad in blob:
            raise ValueError(f"public impact export contains forbidden residue: {bad}")

    total_participants = sum(int(o["participantsPublic"]) for o in outcomes)
    return {
        "version": "1.0.0",
        "updatedAt": updated_at or date.today().isoformat(),
        "source": source,
        "authority": "public_aggregate_only",
        "privacy": {
            "classification": "public_aggregate_only",
            "piiAllowed": False,
            "donorNamesAllowed": False,
            "individualDonorAttributionAllowed": False,
            "operatorIdentityAllowed": False,
        },
        "summary": {
            "outcomeCount": len(outcomes),
            "totalParticipantsPublic": total_participants,
        },
        "outcomes": outcomes,
    }


def write_public_impact(path: str, doc: dict[str, Any] | None = None) -> None:
    from pathlib import Path

    out = Path(path)
    payload = doc if doc is not None else build_public_impact_export([])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
