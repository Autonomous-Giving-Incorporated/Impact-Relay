"""Versioned tenant policy loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from impact_relay.policy import (
    PolicyError,
    default_policy,
    load_policy_document,
    load_tenant_policy,
    parse_tenant_policy,
    resolve_policy_path,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = ROOT / "policies" / "tenants" / "hacker-dojo.v1.0.yaml"


def test_resolve_hacker_dojo_policy() -> None:
    path = resolve_policy_path("org_hacker_dojo", "v1.0")
    assert path == POLICY_FILE
    assert path.is_file()


def test_load_yaml_policy() -> None:
    policy = load_tenant_policy("org_hacker_dojo", "v1.0")
    assert policy.version == "v1.0"
    assert policy.tenant_id == "org_hacker_dojo"
    assert policy.confidence.block_below == 0.75
    assert "invoice" in policy.evidence.sufficient_kinds
    assert policy.attribution.default_method == "DIRECT_RESTRICTED"
    assert policy.notifications.require_separate_send_approval is True
    assert policy.requires_human("approve_expense")
    assert policy.requires_human("send_notification")
    assert not policy.requires_human("import_normalized_expense")
    assert policy.source_path and policy.source_path.endswith("hacker-dojo.v1.0.yaml")


def test_policy_to_dict_roundtrip_fields() -> None:
    policy = load_tenant_policy("org_hacker_dojo", "v1.0")
    body = policy.to_dict()
    assert body["confidence"]["block_below"] == 0.75
    assert "send_notification" in body["authority"]["l3_command_types"]


def test_json_policy_load(tmp_path: Path) -> None:
    doc = {
        "version": "v1.1",
        "tenant_id": "org_other",
        "display_name": "Other",
        "confidence": {"block_below": 0.8, "recommend_high": 0.99},
        "evidence": {"sufficient_kinds": ["invoice"], "require_donor_visible": False},
        "attribution": {"default_method": "PRO_RATA_POOL"},
        "notifications": {"require_separate_send_approval": False},
        "authority": {"l3_command_types": ["approve_expense"]},
    }
    path = tmp_path / "other.v1.1.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    data = load_policy_document(path)
    policy = parse_tenant_policy(data, source_path=str(path))
    assert policy.confidence.block_below == 0.8
    assert policy.evidence.sufficient_kinds == ("invoice",)
    assert policy.notifications.require_separate_send_approval is False


def test_missing_policy_raises() -> None:
    with pytest.raises(PolicyError, match="no policy file"):
        load_tenant_policy("org_does_not_exist", "v9.9")


def test_default_policy_falls_back() -> None:
    p = default_policy("org_unknown_xyz", "v1.0")
    assert p.tenant_id == "org_unknown_xyz"
    assert p.confidence.block_below == 0.75


def test_classifier_uses_policy_threshold() -> None:
    from impact_relay.agents.base import AgentContext
    from impact_relay.agents.expense_workflow import AllocationClassifierAgent
    from impact_relay.agents.types import AgentCommand, AuthorityLevel, ValidationStatus

    policy = load_tenant_policy("org_hacker_dojo", "v1.0")
    ctx = AgentContext(
        tenant_id="org_hacker_dojo",
        policy_version=policy.version,
        policy=policy.to_dict(),
    )
    agent = AllocationClassifierAgent()
    prop = agent.evaluate(
        ctx,
        AgentCommand(
            command_type="classify_expense",
            tenant_id="org_hacker_dojo",
            payload={
                "expense_id": "e1",
                "allocation_id": "a1",
                "amount": "10",
                "confidence": 0.5,
            },
            required_authority=AuthorityLevel.L1_PROPOSE,
        ),
    )
    result = agent.validate(ctx, prop)
    assert result.status == ValidationStatus.NEEDS_INFORMATION
