"""Privacy Sentinel — deterministic allowlist / denylist for public and donor outputs."""

from __future__ import annotations

from typing import Any

from impact_relay.agents.types import ValidationResult, ValidationStatus

# Keys that must never appear in public_aggregate_only exports.
PUBLIC_BANNED_KEYS: frozenset[str] = frozenset(
    {
        "donor_id",
        "donorId",
        "donor_ids",
        "donor_name",
        "donorName",
        "display_name",
        "displayName",
        "email",
        "emails",
        "phone",
        "phones",
        "address",
        "addresses",
        "donation_reference",
        "donationReference",
        "attendee_names",
        "attendeeNames",
        "approved_by",
        "approvedBy",
        "operator_email",
        "operatorEmail",
        "ssn",
        "tax_id",
        "taxId",
    }
)

# Substring markers that indicate personal residue in public blobs.
PUBLIC_BANNED_SUBSTRINGS: tuple[str, ...] = (
    "donor_alice",
    "Alice Patron",
    "finance.operator",
    "@hackersdojo.example",
)

# Required privacy flags for public documents.
REQUIRED_PUBLIC_PRIVACY: dict[str, Any] = {
    "classification": "public_aggregate_only",
    "piiAllowed": False,
    "donorNamesAllowed": False,
}


class PrivacySentinelError(ValueError):
    """Public or donor output failed privacy gates."""


def _walk_keys(payload: Any, path: str = "$") -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{path}.{key}"
            if key in PUBLIC_BANNED_KEYS:
                hits.append((child, key))
            hits.extend(_walk_keys(value, child))
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            hits.extend(_walk_keys(item, f"{path}[{idx}]"))
    return hits


def scan_public_payload(payload: Any) -> ValidationResult:
    """Validate a public export projection. Fail closed on banned keys/substrings."""
    reasons: list[str] = []
    for path, key in _walk_keys(payload):
        reasons.append(f"banned key {key!r} at {path}")

    blob = str(payload)
    for marker in PUBLIC_BANNED_SUBSTRINGS:
        if marker in blob:
            reasons.append(f"banned residue marker {marker!r}")

    if isinstance(payload, dict):
        privacy = payload.get("privacy") or {}
        if privacy:
            if privacy.get("classification") != "public_aggregate_only":
                reasons.append("privacy.classification must be public_aggregate_only")
            for flag in ("piiAllowed", "donorNamesAllowed"):
                if privacy.get(flag) is not False:
                    reasons.append(f"privacy.{flag} must be false")

    if reasons:
        return ValidationResult(status=ValidationStatus.REJECTED, reasons=reasons)
    return ValidationResult(status=ValidationStatus.ACCEPTED)


def assert_public_safe(payload: Any) -> None:
    result = scan_public_payload(payload)
    if not result.ok:
        raise PrivacySentinelError("; ".join(result.reasons))


def redacted_public_copy(payload: dict[str, Any]) -> dict[str, Any]:
    """Shallow-safe copy that drops banned top-level keys (does not deep-mutate source)."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in PUBLIC_BANNED_KEYS:
            continue
        if isinstance(value, dict):
            out[key] = redacted_public_copy(value)
        elif isinstance(value, list):
            out[key] = [
                redacted_public_copy(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            out[key] = value
    return out
