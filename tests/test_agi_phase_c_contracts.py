"""AGI Phase C: public-safe fixtures and vocabulary alignment.

Fixtures are contract examples. They must not claim a live cohort, OBSERVED
raised totals, or donor-level evidence. VERIFIED keeps its frozen meaning.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "agi_phase_c"
PUBLIC_IMPACT_FIXTURE = FIXTURE_DIR / "public_impact.json"
IMPACT_EVENTS_FIXTURE = FIXTURE_DIR / "impact_events.json"
LIVE_PUBLIC_IMPACT = ROOT / "data" / "public-impact.json"
PUBLIC_IMPACT_SCHEMA = ROOT / "schemas" / "public-impact.schema.json"
IMPACT_EVENT_SCHEMA = ROOT / "schemas" / "agi-impact-event.schema.json"

ALLOCATION_ID_RE = re.compile(r"^alloc_[a-z0-9_]+$")
CONTRACT_VERSION = "2026-08-02"
SHARED_ALLOCATION_ID = "alloc_community_hardware"

# AGI PublicVerificationStatus ↔ IR public evidenceState. DRAFT/SUBMITTED are
# not public-export states. VERIFIED meaning is frozen.
VERIFICATION_MAP = {
    "VERIFIED": "verified",
    "SUBMITTED": "pending",
    "REJECTED": "rejected",
}

AGI_EVENT_TYPES = frozenset(
    {
        "purchase_approved",
        "receipt_attached",
        "equipment_delivered",
        "program_held",
        "attendance_verified",
        "notification_delivered",
    }
)

EVENT_TYPE_MAP = {
    "CLASS_HELD": "program_held",
}

BANNED_RESIDUE = (
    "donor_alice",
    "Alice Patron",
    '"donor_id"',
    '"donorId"',
    '"donation_id"',
    '"donationId"',
    "donation_reference",
    "finance.operator",
    '"attendeeNames"',
    '"attendee_names"',
    "OBSERVED",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_impact_fixture_matches_published_schema_shape() -> None:
    doc = _load(PUBLIC_IMPACT_FIXTURE)
    schema = _load(PUBLIC_IMPACT_SCHEMA)
    required = schema["required"]
    for key in required:
        assert key in doc, f"missing public-impact field {key}"
    assert doc["authority"] == "public_aggregate_only"
    assert doc["source"] == "fixture:agi_phase_c"
    privacy = doc["privacy"]
    assert privacy["classification"] == "public_aggregate_only"
    assert privacy["piiAllowed"] is False
    assert privacy["donorNamesAllowed"] is False
    assert privacy["individualDonorAttributionAllowed"] is False
    assert privacy["operatorIdentityAllowed"] is False
    assert doc["summary"]["outcomeCount"] == len(doc["outcomes"])
    assert doc["summary"]["outcomeCount"] >= 1


def test_public_impact_fixture_has_verified_joinable_outcome() -> None:
    doc = _load(PUBLIC_IMPACT_FIXTURE)
    verified = [o for o in doc["outcomes"] if o.get("evidenceState") == "VERIFIED"]
    assert verified, "Phase C fixture must include one VERIFIED outcome"
    row = verified[0]
    for key in (
        "publicId",
        "impactEventId",
        "organizationName",
        "programName",
        "allocationId",
        "allocationName",
        "eventType",
        "eventDate",
        "participantsPublic",
        "evidenceState",
        "attributionMethod",
        "receiptHash",
        "createdAt",
    ):
        assert row.get(key) not in (None, ""), f"outcome missing {key}"
    assert ALLOCATION_ID_RE.match(row["allocationId"])
    assert row["allocationId"] == SHARED_ALLOCATION_ID
    assert row["eventType"] == "CLASS_HELD"
    assert EVENT_TYPE_MAP[row["eventType"]] == "program_held"
    assert row["evidenceState"] == "VERIFIED"
    assert VERIFICATION_MAP[row["evidenceState"]] == "verified"


def test_impact_event_fixture_matches_agi_contract() -> None:
    doc = _load(IMPACT_EVENTS_FIXTURE)
    schema = _load(IMPACT_EVENT_SCHEMA)
    assert doc["meta"]["contractVersion"] == CONTRACT_VERSION
    assert doc["meta"]["source"] == "fixture:agi_phase_c"
    assert doc["events"]
    required = schema["properties"]["events"]["items"]["required"]
    for event in doc["events"]:
        for key in required:
            assert event.get(key) not in (None, ""), f"event missing {key}"
        assert event["schemaVersion"] == CONTRACT_VERSION
        assert ALLOCATION_ID_RE.match(event["allocationId"])
        assert event["allocationId"] == SHARED_ALLOCATION_ID
        assert event["type"] in AGI_EVENT_TYPES
        assert event["verificationStatus"] in {"pending", "verified", "rejected"}
        ref = event.get("evidenceReference")
        if ref:
            assert "://" not in ref
            assert "http" not in ref.lower()


def test_phase_c_fixtures_are_public_safe() -> None:
    for path in (PUBLIC_IMPACT_FIXTURE, IMPACT_EVENTS_FIXTURE):
        blob = path.read_text(encoding="utf-8")
        for bad in BANNED_RESIDUE:
            assert bad not in blob, f"{path}: forbidden residue {bad}"


def test_live_public_impact_does_not_claim_observed_or_ready() -> None:
    doc = _load(LIVE_PUBLIC_IMPACT)
    blob = json.dumps(doc)
    assert "OBSERVED" not in blob
    assert "READY" not in blob
    assert "freeze" not in blob.lower()
    assert doc["authority"] == "public_aggregate_only"
    assert doc["source"] == "gated:public_shell"
    # Empty shell is honest: no live VERIFIED cohort is claimed here.
    assert doc["outcomes"] == []
    assert doc["summary"]["outcomeCount"] == 0


def test_schema_allocation_id_pattern_matches_agi() -> None:
    schema = _load(PUBLIC_IMPACT_SCHEMA)
    pattern = schema["properties"]["outcomes"]["items"]["properties"]["allocationId"]["pattern"]
    assert pattern == ALLOCATION_ID_RE.pattern
    assert ALLOCATION_ID_RE.match(SHARED_ALLOCATION_ID)
    assert not ALLOCATION_ID_RE.match("donor_alice")
    assert not ALLOCATION_ID_RE.match("READY")


def test_verified_meaning_is_not_relabeled() -> None:
    from impact_relay.domain.types import ImpactEventState

    assert ImpactEventState.VERIFIED.value == "VERIFIED"
    assert VERIFICATION_MAP["VERIFIED"] == "verified"
    # Mapping is display/join only; domain enum values stay uppercase.
    assert set(ImpactEventState) == {
        ImpactEventState.DRAFT,
        ImpactEventState.SUBMITTED,
        ImpactEventState.VERIFIED,
        ImpactEventState.REJECTED,
    }
