"""Notion public-evidence aggregate adapter (HD-IR-005).

Loads operator-exported public aggregates from Notion campaign research
(e.g. Public EvidencePack) and produces a Pages-safe public-evidence document.

Never accepts donor-level rows, emails, or itemized gifts.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from impact_relay.http_json import HTTPOpener, fetch_json_object

DEFAULT_NOTION_EVIDENCE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "notion_public_evidence_v1.json"
)

FORBIDDEN_KEYS = frozenset(
    {
        "donors",
        "donor",
        "emails",
        "email",
        "gifts",
        "transactions",
        "line_items",
        "lineItems",
        "phone",
        "phones",
        "address",
        "addresses",
        "names",
        "roster",
        "attendee_names",
        "attendeeNames",
    }
)


class NotionPublicError(ValueError):
    """Invalid or privacy-violating Notion public evidence input."""


def _assert_safe(payload: Any, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_KEYS:
                raise NotionPublicError(f"forbidden personal/itemized field at {path}.{key}")
            _assert_safe(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            _assert_safe(item, f"{path}[{idx}]")


def validate_notion_public_evidence(data: dict[str, Any]) -> dict[str, Any]:
    """Enforce the public-aggregate-only Notion evidence contract."""
    _assert_safe(data)
    privacy = data.get("privacy") or {}
    if privacy.get("piiAllowed") is not False:
        raise NotionPublicError("privacy.piiAllowed must be false")
    if privacy.get("donorNamesAllowed") is not False:
        raise NotionPublicError("privacy.donorNamesAllowed must be false")
    if privacy.get("individualAmountsAllowed") is not False:
        raise NotionPublicError("privacy.individualAmountsAllowed must be false")
    return data


def load_notion_public_evidence(path: Path | str | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else DEFAULT_NOTION_EVIDENCE
    with fixture_path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise NotionPublicError("Notion public evidence JSON root must be an object")
    return validate_notion_public_evidence(data)


def fetch_notion_public_evidence(
    url: str,
    *,
    bearer_token: str | None = None,
    timeout_seconds: float = 10.0,
    max_response_bytes: int = 1_048_576,
    opener: HTTPOpener | None = None,
) -> dict[str, Any]:
    """Fetch a pre-aggregated evidence document, then apply local privacy rules."""
    data = fetch_json_object(
        url,
        bearer_token=bearer_token,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        opener=opener,
    )
    return validate_notion_public_evidence(data)


def build_public_evidence_document(
    source: dict[str, Any] | None = None,
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Project Notion-exported public evidence into a Pages artifact."""
    raw = source if source is not None else load_notion_public_evidence()
    _assert_safe(raw)

    contributions = raw.get("form990Contributions") or []
    contribution_total = sum(int(row.get("contributions") or 0) for row in contributions)
    latest = contributions[-1] if contributions else None

    historical = raw.get("historicalCampaigns") or []
    targets = raw.get("campaignTargets") or {}
    community = raw.get("communitySurface") or {}
    meta = raw.get("meta") or {}

    return {
        "version": "1.0.0",
        "updatedAt": updated_at or date.today().isoformat(),
        "source": meta.get("source") or "notion_public_evidence",
        "sourcePage": meta.get("sourcePage"),
        "researchCutoff": meta.get("researchCutoff"),
        "authority": "public_aggregate_only",
        "claimLabels": meta.get("claimLabels") or ["OBSERVED"],
        "privacy": {
            "classification": "public_aggregate_only",
            "piiAllowed": False,
            "donorNamesAllowed": False,
            "individualAmountsAllowed": False,
            "contactDataAllowed": False,
        },
        "organization": raw.get("organization") or {},
        "campaignTargets": {
            "minimumTarget": targets.get("minimumTarget"),
            "stretchTarget": targets.get("stretchTarget"),
            "currency": targets.get("currency") or "USD",
            "eventDate": targets.get("eventDate"),
            "eventName": targets.get("eventName"),
            "liveRaisedState": targets.get("liveRaisedState") or "NOT_COMPUTABLE",
            "liveRaisedNote": targets.get("liveRaisedNote"),
        },
        "summary": {
            "form990ContributionYears": len(contributions),
            "form990ContributionsTotal": contribution_total,
            "latestFiscalYear": None if latest is None else latest.get("fiscalYear"),
            "latestFiscalYearContributions": None
            if latest is None
            else latest.get("contributions"),
            "historicalCampaignCount": len(historical),
            "meetupMembers": community.get("meetupMembers"),
        },
        "form990Contributions": contributions,
        "historicalCampaigns": historical,
        "communitySurface": community,
        "note": meta.get("note"),
    }


def write_public_evidence(path: Path | str, doc: dict[str, Any] | None = None) -> Path:
    out = Path(path)
    payload = doc if doc is not None else build_public_evidence_document()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def notion_campaign_targets_patch(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return impact-state campaign field patches from Notion targets only.

    Does not invent live raised totals. Notion marks live raised as NOT_COMPUTABLE.
    """
    targets = evidence.get("campaignTargets") or {}
    patch: dict[str, Any] = {}
    if targets.get("minimumTarget") is not None:
        patch["minimumTarget"] = float(targets["minimumTarget"])
    if targets.get("stretchTarget") is not None:
        patch["stretchTarget"] = float(targets["stretchTarget"])
    if targets.get("eventDate"):
        patch["eventDate"] = targets["eventDate"]
    if targets.get("eventName"):
        patch["name"] = f"{targets['eventName']} Campaign"
    return patch
