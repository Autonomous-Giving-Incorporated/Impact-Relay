"""HD-IR-004: domain impact digests + Every.org aggregate adapter."""

from __future__ import annotations

import json

import pytest

from impact_relay.digest import digests_from_workspace
from impact_relay.every_org import (
    every_org_to_reconcile_aggregate,
    load_every_org_as_reconcile_aggregate,
    load_every_org_summary,
)
from impact_relay.pilot import run_all_phases_pilot
from impact_relay.reconcile import ReconcileError, apply_aggregate_reconciliation, load_impact_state


def test_digests_from_domain_verified_events() -> None:
    platform, payload = run_all_phases_pilot()
    primary_id = payload["primary"]["organization_id"]
    ws = platform.get_workspace(primary_id)
    digests = digests_from_workspace(ws, source="test_domain")

    assert digests["privacy"]["attendeeNamesAllowed"] is False
    assert digests["summary"]["eventCount"] >= 1
    # Domain pilot CLASS_HELD with 18 participants
    assert digests["summary"]["totalAttendancePublic"] >= 18
    blob = json.dumps(digests)
    assert "donor_alice" not in blob
    assert "program.reviewer" not in blob
    assert any(e["class"] == "class_session" for e in digests["events"])


def test_digests_merge_domain_and_fixture() -> None:
    platform, payload = run_all_phases_pilot()
    ws = platform.get_workspace(payload["primary"]["organization_id"])
    from impact_relay.digest import load_events_fixture

    digests = digests_from_workspace(
        ws,
        source="domain+fixture",
        extra_events_doc=load_events_fixture(),
    )
    # Domain class + 3 fixture events
    assert digests["summary"]["eventCount"] >= 4


def test_every_org_adapter_normalizes_totals() -> None:
    aggregate = load_every_org_as_reconcile_aggregate()
    assert aggregate["raisedPublic"] == 12840
    assert aggregate["committedPublic"] == 2500
    assert aggregate["donorCountPublic"] == 37
    assert "every.org" in aggregate["source"]


def test_every_org_rejects_gift_lists() -> None:
    with pytest.raises(ReconcileError):
        every_org_to_reconcile_aggregate(
            {
                "processor": "every.org",
                "exportKind": "aggregate_summary",
                "totals": {"raised": 1, "donorCount": 1},
                "gifts": [{"amount": 1}],
            }
        )


def test_every_org_reconcile_into_impact_state() -> None:
    state = load_impact_state()
    aggregate = load_every_org_as_reconcile_aggregate()
    updated = apply_aggregate_reconciliation(state, aggregate)
    assert updated["campaign"]["raisedPublic"] == 12840
    assert updated["campaign"]["status"] == "active"
    assert updated["privacy"]["piiAllowed"] is False


def test_load_every_org_summary_smoke() -> None:
    doc = load_every_org_summary()
    assert doc["nonprofitSlug"] == "hacker-dojo"
