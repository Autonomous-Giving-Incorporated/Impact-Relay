"""HD-IR-006 public IMPACT outcome export tests."""

from __future__ import annotations

import json

from impact_relay.pilot import run_all_phases_pilot
from impact_relay.public_impact import build_public_impact_export


def test_public_impact_strips_donor_identity() -> None:
    platform, payload = run_all_phases_pilot()
    ws = platform.get_workspace(payload["primary"]["organization_id"])
    receipts = list(ws.impact_receipts.values())
    assert receipts
    doc = build_public_impact_export(receipts)
    blob = json.dumps(doc)
    assert "donor_id" not in blob
    assert "donation_id" not in blob
    assert "donor_alice" not in blob
    assert doc["privacy"]["individualDonorAttributionAllowed"] is False
    assert doc["summary"]["outcomeCount"] >= 1
    assert doc["outcomes"][0]["participantsPublic"] == 18
    assert doc["outcomes"][0]["programName"]


def test_public_impact_dedupes_by_event() -> None:
    platform, payload = run_all_phases_pilot()
    ws = platform.get_workspace(payload["primary"]["organization_id"])
    receipts = list(ws.impact_receipts.values())
    # Simulate two donor-level receipts for same event
    if len(receipts) == 1:
        from dataclasses import replace

        twin = replace(receipts[0], receipt_id="dup", receipt_hash="bb" * 32)
        receipts = [receipts[0], twin]
    doc = build_public_impact_export(receipts)
    event_ids = [o["impactEventId"] for o in doc["outcomes"]]
    assert len(event_ids) == len(set(event_ids))
