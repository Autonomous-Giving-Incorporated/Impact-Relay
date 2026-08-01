"""HD-IR-003 impact-event digests (public-safe class summaries).

Digests describe program/event outcomes with aggregate counts only.
No attendee names, emails, or individual registrations are permitted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_EVENTS_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "impact_events_pilot.json"
)

FORBIDDEN_EVENT_KEYS = frozenset(
    {
        "attendee_names",
        "attendeeNames",
        "emails",
        "email",
        "phone",
        "phones",
        "registrants",
        "roster",
        "members",
        "donors",
    }
)

ALLOWED_CLASSES = frozenset(
    {
        "community_event",
        "workshop",
        "class_session",
        "open_lab",
        "fundraiser",
        "stewardship",
        "other",
    }
)


class DigestError(ValueError):
    """Invalid or privacy-violating digest input."""


def _stable_digest_id(event: dict[str, Any]) -> str:
    base = {
        "title": event.get("title"),
        "occurredOn": event.get("occurredOn"),
        "class": event.get("class"),
        "attendeeCountPublic": event.get("attendeeCountPublic"),
        "impactSummary": event.get("impactSummary"),
    }
    canonical = json.dumps(base, sort_keys=True, separators=(",", ":"))
    return "evt_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _assert_no_forbidden(payload: Any, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_EVENT_KEYS:
                raise DigestError(f"forbidden personal field at {path}.{key}")
            _assert_no_forbidden(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            _assert_no_forbidden(item, f"{path}[{idx}]")


def load_events_fixture(path: Path | str | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else DEFAULT_EVENTS_FIXTURE
    with fixture_path.open(encoding="utf-8") as f:
        data = json.load(f)
    _assert_no_forbidden(data)
    return data


def event_to_public(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize one event into a public digest row."""
    _assert_no_forbidden(event)
    event_class = event.get("class") or "other"
    if event_class not in ALLOWED_CLASSES:
        raise DigestError(f"unsupported event class: {event_class}")

    count = event.get("attendeeCountPublic")
    if count is None:
        raise DigestError("attendeeCountPublic is required")
    if not isinstance(count, int) or count < 0:
        raise DigestError("attendeeCountPublic must be a non-negative integer")

    title = (event.get("title") or "").strip()
    summary = (event.get("impactSummary") or "").strip()
    occurred = event.get("occurredOn")
    if not title or not summary or not occurred:
        raise DigestError("title, occurredOn, and impactSummary are required")

    return {
        "eventId": event.get("id") or _stable_digest_id(event),
        "title": title,
        "class": event_class,
        "occurredOn": occurred,
        "attendeeCountPublic": count,
        "impactSummary": summary,
        "linkedAllocationName": event.get("linkedAllocationName"),
        "locationLabel": event.get("locationLabel") or "public_aggregate",
    }


def build_public_digests(
    events_doc: dict[str, Any] | None = None,
    *,
    source: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Build the public Pages digests document."""
    doc = events_doc if events_doc is not None else load_events_fixture()
    events = [event_to_public(e) for e in doc.get("events", [])]
    events.sort(key=lambda e: e["occurredOn"], reverse=True)

    total_attendance = sum(e["attendeeCountPublic"] for e in events)
    by_class: dict[str, int] = {}
    for event in events:
        by_class[event["class"]] = by_class.get(event["class"], 0) + 1

    return {
        "version": "1.0.0",
        "updatedAt": updated_at or date.today().isoformat(),
        "source": source or doc.get("meta", {}).get("source", "hd_ir_003_events_pilot"),
        "authority": "public_aggregate_only",
        "privacy": {
            "classification": "public_aggregate_only",
            "piiAllowed": False,
            "attendeeNamesAllowed": False,
            "contactDataAllowed": False,
        },
        "summary": {
            "eventCount": len(events),
            "totalAttendancePublic": total_attendance,
            "classCounts": by_class,
        },
        "events": events,
    }


def write_public_digests(path: Path | str, digests: dict[str, Any] | None = None) -> Path:
    out = Path(path)
    payload = digests if digests is not None else build_public_digests()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out
