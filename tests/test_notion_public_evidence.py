"""HD-IR-005 Notion public evidence tests."""

from __future__ import annotations

import json

import pytest

from impact_relay.notion_public import (
    NotionPublicError,
    build_public_evidence_document,
    load_notion_public_evidence,
    notion_campaign_targets_patch,
)


def test_load_notion_public_evidence() -> None:
    raw = load_notion_public_evidence()
    assert raw["meta"]["source"].startswith("notion:")
    assert len(raw["form990Contributions"]) == 6
    assert raw["historicalCampaigns"][0]["raisedApproximate"] == 250000


def test_build_public_evidence_document() -> None:
    doc = build_public_evidence_document()
    assert doc["privacy"]["piiAllowed"] is False
    assert doc["summary"]["form990ContributionYears"] == 6
    assert doc["summary"]["form990ContributionsTotal"] == (
        99776 + 52128 + 95668 + 34333 + 84724 + 66232
    )
    assert doc["summary"]["latestFiscalYearContributions"] == 66232
    assert doc["campaignTargets"]["liveRaisedState"] == "NOT_COMPUTABLE"
    blob = json.dumps(doc)
    assert "donor_alice" not in blob
    assert "@" not in blob  # no emails


def test_rejects_donor_lists() -> None:
    bad = load_notion_public_evidence()
    bad["donors"] = [{"name": "Nope"}]
    with pytest.raises(NotionPublicError):
        build_public_evidence_document(bad)


def test_campaign_targets_patch_does_not_invent_raised() -> None:
    doc = build_public_evidence_document()
    patch = notion_campaign_targets_patch(doc)
    assert patch["minimumTarget"] == 420000
    assert patch["stretchTarget"] == 2000000
    assert "raisedPublic" not in patch
