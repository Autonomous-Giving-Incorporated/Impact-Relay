"""v0.5 agent contract, authority, simulation, and privacy tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from impact_relay.agents.authority import (
    AuthorityError,
    assert_execution_authorized,
    requires_human_approval,
)
from impact_relay.agents.base import AgentContext, CommandExecutor
from impact_relay.agents.privacy import (
    PrivacySentinelError,
    assert_public_safe,
    scan_public_payload,
)
from impact_relay.agents.types import (
    AgentCommand,
    AgentProposal,
    ApprovalReceipt,
    AuthorityLevel,
    ValidationStatus,
    stable_hash,
    to_jsonable,
    utc_now_iso,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "agents"


def test_l3_command_requires_human_authority() -> None:
    cmd = AgentCommand(
        command_type="approve_expense",
        tenant_id="org_hacker_dojo",
        payload={"expense_id": "exp_1"},
    )
    assert cmd.required_authority == AuthorityLevel.L3_HUMAN_APPROVAL
    assert requires_human_approval(cmd)


def test_execution_without_approval_fails() -> None:
    cmd = AgentCommand(
        command_type="approve_expense",
        tenant_id="org_hacker_dojo",
        payload={"expense_id": "exp_1"},
    )
    with pytest.raises(AuthorityError, match="requires human"):
        assert_execution_authorized(cmd, None)


def test_agent_cannot_approve_own_proposal() -> None:
    cmd = AgentCommand(
        command_type="approve_expense",
        tenant_id="org_hacker_dojo",
        payload={"expense_id": "exp_1"},
    )
    approval = ApprovalReceipt(
        approval_id="appr_1",
        tenant_id="org_hacker_dojo",
        proposal_id="prop_1",
        command_idempotency_key=cmd.idempotency_key,
        decision="APPROVE",
        approver_id="finance.operator@example.org",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
    )
    # Matching approval works
    assert_execution_authorized(cmd, approval, agent_name="finance_review")

    with pytest.raises(AuthorityError, match="cannot approve its own"):
        assert_execution_authorized(cmd, approval, agent_name="finance.operator@example.org")


def test_agent_identity_rejected_as_approver() -> None:
    cmd = AgentCommand(
        command_type="publish_use_of_funds_receipt",
        tenant_id="org_x",
        payload={},
    )
    with pytest.raises(AuthorityError, match="human operator"):
        assert_execution_authorized(
            cmd,
            ApprovalReceipt(
                approval_id="a",
                tenant_id="org_x",
                proposal_id="p",
                command_idempotency_key=cmd.idempotency_key,
                decision="APPROVE",
                approver_id="agent:finance_review",
                approver_role="agent",
                approved_at=utc_now_iso(),
            ),
        )


def test_simulation_executor_does_not_dispatch() -> None:
    class Exploding(CommandExecutor):
        def _dispatch(self, command: AgentCommand):
            raise AssertionError("dispatch must not run in simulation")

    ex = Exploding(simulation=True)
    cmd = AgentCommand(
        command_type="import_normalized_expense",
        tenant_id="org_x",
        payload={"expense": {"external_source_id": "e1"}},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
    )
    receipt = ex.execute(cmd)
    assert receipt.status == "SIMULATED"
    assert receipt.simulated is True


def test_idempotency_skips_duplicate() -> None:
    class Ok(CommandExecutor):
        def _dispatch(self, command: AgentCommand):
            return ["x"], {"ok": True}

    ex = Ok(simulation=False)
    cmd = AgentCommand(
        command_type="import_normalized_expense",
        tenant_id="org_x",
        payload={"expense": {"external_source_id": "e1"}},
        required_authority=AuthorityLevel.L2_REVERSIBLE,
        idempotency_key="fixed-key",
    )
    r1 = ex.execute(cmd)
    r2 = ex.execute(cmd)
    assert r1.status == "SUCCEEDED"
    assert r2.status == "SKIPPED"


def test_privacy_sentinel_blocks_donor_keys() -> None:
    bad = {
        "privacy": {
            "classification": "public_aggregate_only",
            "piiAllowed": False,
            "donorNamesAllowed": False,
        },
        "donor_id": "donor_alice",
    }
    result = scan_public_payload(bad)
    assert result.status == ValidationStatus.REJECTED
    with pytest.raises(PrivacySentinelError):
        assert_public_safe(bad)


def test_privacy_sentinel_accepts_clean_public() -> None:
    good = {
        "privacy": {
            "classification": "public_aggregate_only",
            "piiAllowed": False,
            "donorNamesAllowed": False,
        },
        "receipts": [{"receiptId": "pub_abc", "grossAmount": "10.00"}],
    }
    assert scan_public_payload(good).ok


def test_proposal_json_schema_shape() -> None:
    """Lightweight required-field check against committed schema (no jsonschema dep)."""
    schema = json.loads((SCHEMA_DIR / "agent-proposal.schema.json").read_text())
    required = set(schema["required"])
    proposal = AgentProposal(
        proposal_id="prop_1",
        tenant_id="org_hacker_dojo",
        agent_name="expense_intake",
        agent_version="0.5.0",
        policy_version="v1.0",
        prompt_version=None,
        input_refs=["batch"],
        input_hash=stable_hash({"a": 1}),
        proposed_commands=[
            AgentCommand(
                command_type="import_normalized_expense",
                tenant_id="org_hacker_dojo",
                payload={},
                required_authority=AuthorityLevel.L2_REVERSIBLE,
            )
        ],
        evidence_refs=[],
        confidence=0.99,
        warnings=[],
        contradictions=[],
        required_authority=AuthorityLevel.L2_REVERSIBLE,
        expires_at="2099-01-01T00:00:00+00:00",
        idempotency_key="k1",
    )
    body = to_jsonable(proposal)
    assert required.issubset(body.keys())
    assert body["required_authority"] == "L2"


def test_cross_tenant_approval_rejected() -> None:
    cmd = AgentCommand(
        command_type="approve_expense",
        tenant_id="org_a",
        payload={"expense_id": "e"},
    )
    approval = ApprovalReceipt(
        approval_id="appr",
        tenant_id="org_b",
        proposal_id="p",
        command_idempotency_key=cmd.idempotency_key,
        decision="APPROVE",
        approver_id="human@example.org",
        approver_role="finance_approver",
        approved_at=utc_now_iso(),
    )
    with pytest.raises(AuthorityError, match="tenant_id"):
        assert_execution_authorized(cmd, approval)


def test_agent_context_defaults() -> None:
    ctx = AgentContext(tenant_id="org_x")
    assert ctx.policy_version == "v1.0"
    assert ctx.facts == {}
