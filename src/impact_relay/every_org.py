"""Every.org aggregate-only donation summary adapter.

Live Every.org APIs that return personal gift detail are out of scope.
Operators (or a future secure job) reduce processor data to an aggregate
summary *before* it enters this repository. This module normalizes that
summary into the HD-IR-003 reconcile input shape.

Never accepts donor lists, emails, or itemized transactions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from impact_relay.reconcile import ReconcileError, _assert_aggregate_safe

DEFAULT_EVERY_ORG_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "every_org_aggregate_v1.json"
)

FORBIDDEN_EVERY_ORG_KEYS = frozenset(
    {
        "donors",
        "donor",
        "gifts",
        "transactions",
        "charges",
        "payments",
        "emails",
        "email",
        "names",
        "line_items",
        "lineItems",
        "phone",
        "phones",
        "address",
        "addresses",
        "receipts",  # personal gift receipts, not public UOF
    }
)


def _assert_every_org_safe(payload: Any, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_EVERY_ORG_KEYS:
                raise ReconcileError(
                    f"Every.org summary forbids personal/itemized field at {path}.{key}"
                )
            _assert_every_org_safe(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            if isinstance(item, (dict, list)):
                raise ReconcileError(
                    f"nested structures not allowed in Every.org aggregate at {path}[{idx}]"
                )


def load_every_org_summary(path: Path | str | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else DEFAULT_EVERY_ORG_FIXTURE
    with fixture_path.open(encoding="utf-8") as f:
        data = json.load(f)
    _assert_every_org_safe(data)
    if data.get("exportKind") not in (None, "aggregate_summary", "public_totals"):
        raise ReconcileError("exportKind must be aggregate_summary or public_totals")
    if data.get("processor") not in (None, "every.org", "Every.org"):
        raise ReconcileError("processor must be every.org for this adapter")
    return data


def every_org_to_reconcile_aggregate(summary: dict[str, Any]) -> dict[str, Any]:
    """Map an Every.org-style aggregate summary into reconcile_file input."""
    _assert_every_org_safe(summary)
    totals = summary.get("totals") or {}
    if not totals and all(k in summary for k in ("raisedPublic", "committedPublic", "donorCountPublic")):
        # Already in reconcile shape.
        aggregate = {
            "source": summary.get("source") or "every.org/aggregate",
            "reconciledAt": summary.get("reconciledAt") or summary.get("exportedAt"),
            "status": summary.get("status") or summary.get("campaignStatus") or "active",
            "raisedPublic": summary["raisedPublic"],
            "committedPublic": summary["committedPublic"],
            "donorCountPublic": summary["donorCountPublic"],
            "note": summary.get("note") or "Every.org aggregate summary",
        }
    else:
        raised = totals.get("raised", totals.get("raisedUsd", totals.get("amountRaised")))
        committed = totals.get("committed", totals.get("pledged", 0))
        donors = totals.get("donorCount", totals.get("uniqueDonors", totals.get("donorsCount")))
        if raised is None or donors is None:
            raise ReconcileError("Every.org summary missing totals.raised and totals.donorCount")
        slug = summary.get("nonprofitSlug") or summary.get("slug") or "unknown"
        default_source = f"every.org/aggregate:{slug}"
        # Prefer explicit source (fixtures should use fixture://… so raised provenance stays PILOT)
        aggregate = {
            "source": summary.get("source") or default_source,
            "reconciledAt": summary.get("exportedAt") or summary.get("reconciledAt"),
            "status": summary.get("campaignStatus") or summary.get("status") or "active",
            "raisedPublic": float(raised),
            "committedPublic": float(committed or 0),
            "donorCountPublic": int(donors),
            "note": summary.get("note")
            or f"Aggregate-only Every.org summary for nonprofit slug {slug}.",
        }

    if summary.get("claimLevel") or summary.get("claimLabel"):
        aggregate["claimLevel"] = summary.get("claimLevel") or summary.get("claimLabel")

    _assert_aggregate_safe(aggregate)
    return aggregate


def load_every_org_as_reconcile_aggregate(path: Path | str | None = None) -> dict[str, Any]:
    return every_org_to_reconcile_aggregate(load_every_org_summary(path))
