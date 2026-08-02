"""Every cross-boundary agent contract has a JSON Schema that matches the dataclass.

These are the contracts that cross a trust boundary (agent → validator → human
approver → executor). A schema that silently drifts from its dataclass is worse
than no schema, so parity is asserted structurally: same field names, and every
field without a default is required.
"""

from __future__ import annotations

import json
from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    AgentRunReceipt,
    ApprovalReceipt,
    ExecutionReceipt,
    ValidationResult,
)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "agents"

CONTRACTS = [
    ("agent-command", AgentCommand),
    ("agent-proposal", AgentProposal),
    ("agent-run-receipt", AgentRunReceipt),
    ("approval-receipt", ApprovalReceipt),
    ("execution-receipt", ExecutionReceipt),
    ("validation-result", ValidationResult),
]


def _schema(slug: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{slug}.schema.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("slug", "cls"), CONTRACTS, ids=[c[0] for c in CONTRACTS])
def test_schema_fields_match_dataclass(slug: str, cls: type) -> None:
    schema = _schema(slug)
    declared = set(schema["properties"])
    actual = {f.name for f in fields(cls)}
    assert declared == actual, (
        f"{slug}.schema.json is out of sync with {cls.__name__}: "
        f"only in schema={sorted(declared - actual)} "
        f"only in dataclass={sorted(actual - declared)}"
    )


@pytest.mark.parametrize(("slug", "cls"), CONTRACTS, ids=[c[0] for c in CONTRACTS])
def test_schema_requires_every_field_without_a_default(slug: str, cls: type) -> None:
    schema = _schema(slug)
    required = set(schema.get("required", []))
    mandatory = {
        f.name
        for f in fields(cls)
        if f.default is MISSING and f.default_factory is MISSING  # type: ignore[misc]
    }
    missing = mandatory - required
    assert not missing, f"{slug}.schema.json must require {sorted(missing)}"
    assert required <= set(schema["properties"]), (
        f"{slug}.schema.json requires fields it does not declare: "
        f"{sorted(required - set(schema['properties']))}"
    )


@pytest.mark.parametrize(("slug", "_cls"), CONTRACTS, ids=[c[0] for c in CONTRACTS])
def test_schema_is_closed_and_identified(slug: str, _cls: type) -> None:
    """Cross-boundary contracts reject unknown fields and carry a stable $id."""
    schema = _schema(slug)
    assert schema["additionalProperties"] is False
    assert schema["$id"].endswith(f"/{slug}.schema.json")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_every_agents_schema_has_a_contract_test() -> None:
    """A new schema file must be registered here, not left unverified."""
    on_disk = {p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json")}
    covered = {slug for slug, _ in CONTRACTS}
    assert on_disk == covered, f"unregistered schemas: {sorted(on_disk ^ covered)}"
