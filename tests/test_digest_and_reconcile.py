"""HD-IR-003 digest and aggregate reconciliation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from impact_relay.digest import (
    DigestError,
    build_public_digests,
    load_events_fixture,
    write_public_digests,
)
from impact_relay.reconcile import (
    ReconcileError,
    apply_aggregate_reconciliation,
    load_aggregate_fixture,
    load_impact_state,
)


def _state_with_pilot_milestones() -> dict:
    """Public data/impact-state.json is intentionally empty (auth-gated HD feed).

    Reconcile milestone tests use a synthetic pilot ladder independent of that file.
    """
    state = load_impact_state()
    state = {
        **state,
        "campaign": {
            **state.get("campaign", {}),
            "name": "Pilot ladder (test)",
            "minimumTarget": 420000,
        },
        "milestones": [
            {
                "id": "stabilize-ops",
                "label": "Stabilize operations",
                "threshold": 420000,
                "state": "open",
            },
            {
                "id": "stretch-program",
                "label": "Stretch program",
                "threshold": 2000000,
                "state": "open",
            },
        ],
        "notifications": [],
    }
    return state


def test_digests_build_from_pilot_fixture() -> None:
    digests = build_public_digests()
    assert digests["summary"]["eventCount"] == 3
    assert digests["summary"]["totalAttendancePublic"] == 48 + 22 + 61
    assert digests["privacy"]["attendeeNamesAllowed"] is False
    titles = {e["title"] for e in digests["events"]}
    assert "Hardware Lab Open Night" in titles


def test_digests_reject_attendee_names() -> None:
    bad = {
        "events": [
            {
                "title": "Bad Event",
                "class": "workshop",
                "occurredOn": "2026-07-01",
                "attendeeCountPublic": 2,
                "impactSummary": "Should fail",
                "attendeeNames": ["A", "B"],
            }
        ]
    }
    with pytest.raises(DigestError):
        build_public_digests(bad)


def test_write_public_digests(tmp_path: Path) -> None:
    out = tmp_path / "digests.json"
    write_public_digests(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["authority"] == "public_aggregate_only"
    assert data["summary"]["eventCount"] >= 1


def test_reconcile_updates_aggregates_and_milestones() -> None:
    state = _state_with_pilot_milestones()
    aggregate = load_aggregate_fixture()
    updated = apply_aggregate_reconciliation(state, aggregate)

    assert updated["campaign"]["raisedPublic"] == 12840
    assert updated["campaign"]["committedPublic"] == 2500
    assert updated["campaign"]["donorCountPublic"] == 37
    assert updated["campaign"]["status"] == "active"
    assert updated["campaign"]["lastReconciledAt"]
    assert updated["privacy"]["piiAllowed"] is False

    # 12840 is below first milestone threshold 420000 → still open
    assert updated["milestones"], "pilot ladder must be present for this test"
    assert all(m["state"] == "open" for m in updated["milestones"])
    assert any(n["id"].startswith("reconcile-") for n in updated["notifications"])


def test_reconcile_marks_reached_milestones() -> None:
    state = _state_with_pilot_milestones()
    aggregate = {
        "source": "test",
        "raisedPublic": 500000,
        "committedPublic": 0,
        "donorCountPublic": 10,
        "status": "active",
        "reconciledAt": "2026-08-01T16:00:00Z",
        "note": "Synthetic above-minimum test",
    }
    updated = apply_aggregate_reconciliation(state, aggregate)
    reached = [m for m in updated["milestones"] if m["state"] == "reached"]
    assert any(m["id"] == "stabilize-ops" for m in reached)
    assert all(m["id"] != "stretch-program" or m["state"] == "open" for m in updated["milestones"])


def test_reconcile_rejects_donor_lists() -> None:
    with pytest.raises(ReconcileError):
        apply_aggregate_reconciliation(
            load_impact_state(),
            {
                "raisedPublic": 1,
                "committedPublic": 0,
                "donorCountPublic": 1,
                "donors": [{"name": "Nope"}],
            },
        )


def test_load_events_fixture_smoke() -> None:
    doc = load_events_fixture()
    assert "events" in doc
