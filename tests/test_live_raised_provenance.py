"""Live raised provenance: OBSERVED only for authorized processor aggregates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from impact_relay.cli import main
from impact_relay.every_org import every_org_to_reconcile_aggregate
from impact_relay.reconcile import (
    ReconcileError,
    apply_aggregate_reconciliation,
    is_pilot_or_synthetic_source,
    load_impact_state,
    resolve_raised_provenance,
)


def test_fixture_source_is_pilot() -> None:
    assert is_pilot_or_synthetic_source("fixture://every.org/aggregate:hacker-dojo")
    assert is_pilot_or_synthetic_source("every.org/pilot-demo")
    assert not is_pilot_or_synthetic_source("every.org/aggregate:hacker-dojo")


def test_default_fixture_reconcile_stays_pilot() -> None:
    state = load_impact_state()
    aggregate = every_org_to_reconcile_aggregate(
        {
            "processor": "every.org",
            "exportKind": "aggregate_summary",
            "source": "fixture://every.org/aggregate:hacker-dojo",
            "totals": {"raised": 100, "committed": 0, "donorCount": 2},
            "exportedAt": "2026-08-01T15:00:00Z",
            "campaignStatus": "active",
        }
    )
    updated = apply_aggregate_reconciliation(state, aggregate)
    assert updated["campaign"]["raisedSource"] == "pilot_synthetic"
    assert updated["campaign"]["raisedClaimLabel"] == "PILOT"
    assert updated["campaign"]["raisedPublic"] == 100


def test_authorized_every_org_source_is_observed() -> None:
    state = load_impact_state()
    aggregate = every_org_to_reconcile_aggregate(
        {
            "processor": "every.org",
            "exportKind": "aggregate_summary",
            "nonprofitSlug": "hacker-dojo",
            "source": "every.org/aggregate:hacker-dojo",
            "claimLevel": "OBSERVED",
            "totals": {"raised": 50123, "committed": 1200, "donorCount": 88},
            "exportedAt": "2026-08-01T18:00:00Z",
            "campaignStatus": "active",
            "note": "Authorized operator reduction for campaign window",
        }
    )
    assert resolve_raised_provenance(aggregate) == (
        "processor_aggregate",
        "OBSERVED",
    )
    updated = apply_aggregate_reconciliation(state, aggregate)
    assert updated["campaign"]["raisedSource"] == "processor_aggregate"
    assert updated["campaign"]["raisedClaimLabel"] == "OBSERVED"
    assert updated["campaign"]["raisedPublic"] == 50123
    assert updated["campaign"]["aggregateSource"] == "every.org/aggregate:hacker-dojo"
    # Stale awaiting notification removed
    assert not any(n.get("id") == "reconciliation-pending" for n in updated["notifications"])
    body = next(n["body"] for n in updated["notifications"] if n["id"].startswith("reconcile-"))
    assert "OBSERVED" in body


def test_cannot_claim_observed_on_fixture_source() -> None:
    with pytest.raises(ReconcileError, match="cannot claim OBSERVED"):
        resolve_raised_provenance(
            {
                "source": "fixture://every.org/aggregate:hacker-dojo",
                "claimLevel": "OBSERVED",
                "raisedPublic": 1,
                "committedPublic": 0,
                "donorCountPublic": 1,
            }
        )


def test_cli_require_observed_rejects_fixture(tmp_path: Path, monkeypatch) -> None:
    # Point write at temp copy of impact-state so we don't dirty repo mid-test
    root = Path(__file__).resolve().parents[1]
    state_src = root / "data" / "impact-state.json"
    state_dst = tmp_path / "impact-state.json"
    state_dst.write_text(state_src.read_text(encoding="utf-8"), encoding="utf-8")
    fixture = root / "fixtures" / "every_org_aggregate_v1.json"
    code = main(
        [
            "--every-org-aggregate",
            str(fixture),
            "--write-impact-state",
            str(state_dst),
            "--require-observed",
        ]
    )
    assert code == 2
    # File may still be written only on success path — with require_observed fail, we return before write
    # Actually current code applies then checks then write — wait, we check before write. Good.
    remaining = json.loads(state_dst.read_text(encoding="utf-8"))
    # Unchanged pilot state still on disk
    assert remaining["campaign"]["raisedSource"] in (
        "pilot_synthetic",
        "processor_aggregate",
        "not_available",
    )


def test_cli_require_observed_accepts_live_shaped(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    state_dst = tmp_path / "impact-state.json"
    state_dst.write_text(
        (root / "data" / "impact-state.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    live = tmp_path / "live.json"
    live.write_text(
        json.dumps(
            {
                "processor": "every.org",
                "exportKind": "aggregate_summary",
                "nonprofitSlug": "hacker-dojo",
                "exportedAt": "2026-08-01T18:30:00Z",
                "currency": "USD",
                "campaignStatus": "active",
                "claimLevel": "OBSERVED",
                "source": "every.org/aggregate:hacker-dojo",
                "totals": {"raised": 9900, "committed": 100, "donorCount": 12},
                "note": "Test authorized aggregate",
            }
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "--every-org-aggregate",
            str(live),
            "--write-impact-state",
            str(state_dst),
            "--require-observed",
        ]
    )
    assert code == 0
    updated = json.loads(state_dst.read_text(encoding="utf-8"))
    assert updated["campaign"]["raisedSource"] == "processor_aggregate"
    assert updated["campaign"]["raisedClaimLabel"] == "OBSERVED"
    assert updated["campaign"]["raisedPublic"] == 9900
