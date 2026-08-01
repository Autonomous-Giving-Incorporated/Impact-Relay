"""HD-IR-003 public aggregate reconciliation pipeline.

Applies *aggregate-only* donation processor summaries into impact-state.json.
Never accepts donor names, emails, or itemized gifts.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_AGGREGATE_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "reconcile_aggregate_v1.json"
)
DEFAULT_IMPACT_STATE = (
    Path(__file__).resolve().parents[2] / "data" / "impact-state.json"
)

FORBIDDEN_AGGREGATE_KEYS = frozenset(
    {
        "donors",
        "donor",
        "emails",
        "email",
        "names",
        "gifts",
        "transactions",
        "items",
        "line_items",
        "lineItems",
        "phone",
        "phones",
        "address",
        "addresses",
    }
)


class ReconcileError(ValueError):
    """Invalid aggregate reconciliation input."""


def is_pilot_or_synthetic_source(source: str | None) -> bool:
    """True when the aggregate source must not be labeled OBSERVED / processor_aggregate."""
    s = (source or "").strip().lower()
    if not s:
        return True
    markers = (
        "fixture://",
        "fixture/",
        "synthetic",
        "pilot",
        "demo",
        "example",
        "template",
        "not live",
        "not_live",
    )
    return any(m in s for m in markers)


def resolve_raised_provenance(
    aggregate: dict[str, Any],
) -> tuple[str, str]:
    """Return (raisedSource, raisedClaimLabel) for an aggregate payload.

    OBSERVED / processor_aggregate only when source is operator-authorized and
    does not look like a pilot/fixture. Optional aggregate.claimLevel may be
    OBSERVED | PILOT | NOT_COMPUTABLE; OBSERVED is rejected for fixture sources.
    """
    source = str(aggregate.get("source") or "")
    claim = str(aggregate.get("claimLevel") or aggregate.get("claimLabel") or "").upper()
    pilot = is_pilot_or_synthetic_source(source)

    if claim in ("OBSERVED", "PROCESSOR", "PROCESSOR_AGGREGATE"):
        if pilot:
            raise ReconcileError(
                "cannot claim OBSERVED/processor_aggregate for pilot/fixture/synthetic source: "
                f"{source!r}"
            )
        return "processor_aggregate", "OBSERVED"

    if claim in ("PILOT", "SYNTHETIC"):
        return "pilot_synthetic", "PILOT"

    if claim in ("NOT_COMPUTABLE", "UNAVAILABLE", "NOT_AVAILABLE"):
        return "not_available", "NOT_COMPUTABLE"

    if pilot:
        return "pilot_synthetic", "PILOT"
    return "processor_aggregate", "OBSERVED"


def _assert_aggregate_safe(payload: Any, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_AGGREGATE_KEYS:
                raise ReconcileError(f"forbidden personal/itemized field at {path}.{key}")
            _assert_aggregate_safe(value, f"{path}.{key}")
    elif isinstance(payload, list):
        # Aggregate docs may only use scalar arrays (none expected today).
        for idx, item in enumerate(payload):
            if isinstance(item, (dict, list)):
                raise ReconcileError(
                    f"nested structures not allowed in aggregate input at {path}[{idx}]"
                )


def load_aggregate_fixture(path: Path | str | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else DEFAULT_AGGREGATE_FIXTURE
    with fixture_path.open(encoding="utf-8") as f:
        data = json.load(f)
    _assert_aggregate_safe(data)
    for required in ("raisedPublic", "committedPublic", "donorCountPublic"):
        if required not in data:
            raise ReconcileError(f"missing required aggregate field: {required}")
    if data["raisedPublic"] < 0 or data["committedPublic"] < 0:
        raise ReconcileError("raised/committed cannot be negative")
    if int(data["donorCountPublic"]) < 0:
        raise ReconcileError("donorCountPublic cannot be negative")
    return data


def load_impact_state(path: Path | str | None = None) -> dict[str, Any]:
    state_path = Path(path) if path else DEFAULT_IMPACT_STATE
    with state_path.open(encoding="utf-8") as f:
        return json.load(f)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def apply_aggregate_reconciliation(
    impact_state: dict[str, Any],
    aggregate: dict[str, Any],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Return a new impact-state document with aggregates and notification applied."""
    _assert_aggregate_safe(aggregate)
    state = copy.deepcopy(impact_state)
    campaign = state.setdefault("campaign", {})

    raised = float(aggregate["raisedPublic"])
    committed = float(aggregate["committedPublic"])
    donors = int(aggregate["donorCountPublic"])
    status = aggregate.get("status") or "active"
    reconciled_at = aggregate.get("reconciledAt") or as_of or _iso_now()

    campaign["raisedPublic"] = raised
    campaign["committedPublic"] = committed
    campaign["donorCountPublic"] = donors
    campaign["lastReconciledAt"] = reconciled_at
    campaign["status"] = status
    raised_source, raised_label = resolve_raised_provenance(aggregate)
    campaign["raisedSource"] = raised_source
    campaign["raisedClaimLabel"] = raised_label
    campaign["aggregateSource"] = str(aggregate.get("source") or "")

    for milestone in state.get("milestones", []):
        threshold = float(milestone.get("threshold") or 0)
        if raised >= threshold:
            milestone["state"] = "reached"
        elif milestone.get("state") == "reached":
            # Do not silently demote without explicit policy; keep reached if still met.
            milestone["state"] = "reached" if raised >= threshold else "open"
        else:
            milestone["state"] = "open"

    notifications = state.setdefault("notifications", [])
    note = aggregate.get("note") or "Public aggregate totals reconciled from authorized summary."
    source = aggregate.get("source") or "aggregate_reconciliation"
    severity = "success" if raised_source == "processor_aggregate" else "warning"
    title = (
        "Live processor aggregates published"
        if raised_source == "processor_aggregate"
        else "Pilot aggregates updated (not live processor cash)"
        if raised_source == "pilot_synthetic"
        else "Campaign raised not available"
    )
    notification = {
        "id": f"reconcile-{reconciled_at[:10]}",
        "severity": severity,
        "title": title,
        "body": (
            f"{note} Source: {source}. Claim: {raised_label} ({raised_source}). "
            f"Raised ${raised:,.0f}; committed ${committed:,.0f}; "
            f"public donor count {donors}."
        ),
        "publishedAt": reconciled_at if "T" in str(reconciled_at) else f"{reconciled_at}T00:00:00Z",
    }
    # Replace same-day reconcile notification if re-run.
    notifications[:] = [n for n in notifications if n.get("id") != notification["id"]]
    # Drop stale "awaiting live reconciliation" once any aggregate reconcile ran.
    notifications[:] = [
        n for n in notifications if n.get("id") != "reconciliation-pending"
    ]
    notifications.append(notification)

    state["updatedAt"] = date.today().isoformat()
    state["authority"] = "public_aggregate_only"
    privacy = state.setdefault("privacy", {})
    privacy["classification"] = "public_aggregate_only"
    privacy["piiAllowed"] = False
    privacy["donorNamesAllowed"] = False
    privacy["individualAmountsAllowed"] = False
    privacy["contactDataAllowed"] = False
    return state


def write_impact_state(path: Path | str, state: dict[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return out


def reconcile_file(
    aggregate_path: Path | str | None = None,
    impact_state_path: Path | str | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Load aggregate + impact state, apply reconciliation, optionally write back."""
    aggregate = load_aggregate_fixture(aggregate_path)
    state_path = Path(impact_state_path) if impact_state_path else DEFAULT_IMPACT_STATE
    current = load_impact_state(state_path)
    updated = apply_aggregate_reconciliation(current, aggregate)
    if write:
        write_impact_state(state_path, updated)
    return updated
