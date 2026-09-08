"""AutoGive Synthetic Dataset v1 — Civic Forge compact ledger and public impact.

Civic Forge is a second tenant beside Hacker Dojo. These fixtures are
SYNTHETIC_ONLY. They must never claim OBSERVED or overwrite the live public shell.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from impact_relay.agents.executor import LedgerCommandExecutor
from impact_relay.agents.expense_workflow import EvidenceValidatorAgent
from impact_relay.agents.privacy import assert_public_safe
from impact_relay.agents.types import AgentCommand, AuthorityLevel, EvidenceSufficiency
from impact_relay.domain.impact import ImpactService
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.domain.types import (
    ExpenseState,
    ImpactEvent,
    ImpactEventState,
    InvariantError,
    Program,
    StateError,
)
from impact_relay.pilot import (
    DEFAULT_FIXTURE,
    DEFAULT_SYNTHETIC_V1_FIXTURE,
    build_ledger_from_fixture,
    load_fixture,
    run_pilot,
)
from impact_relay.policy import default_policy

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "synthetic_v1"
LEDGER_FIXTURE = FIXTURE_DIR / "civic_forge_ledger_v1.json"
PUBLIC_IMPACT_FIXTURE = FIXTURE_DIR / "public_impact.json"
LIVE_PUBLIC_IMPACT = ROOT / "data" / "public-impact.json"
PUBLIC_IMPACT_SCHEMA = ROOT / "schemas" / "public-impact.schema.json"

ALLOCATION_ID_RE = re.compile(r"^alloc_[a-z0-9_]+$")
STABLE_ALLOCATION_IDS = (
    "alloc_community_hardware",
    "alloc_access_scholarships",
    "alloc_facility_resilience",
    "alloc_community_programs",
)
CIVIC_FORGE = "org_synthetic_civic_forge"
FINANCE_ACTOR = "civicforge.finance@example.test"
BANNED_RESIDUE = (
    "donor_alice",
    "Alice Patron",
    '"donor_id"',
    '"donorId"',
    "donation_reference",
    "finance.operator",
    "@hackersdojo.example",
    '"attendeeNames"',
    '"attendee_names"',
    "OBSERVED",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_synthetic_fixture_path_is_wired() -> None:
    assert DEFAULT_SYNTHETIC_V1_FIXTURE == LEDGER_FIXTURE
    assert LEDGER_FIXTURE.is_file()
    assert PUBLIC_IMPACT_FIXTURE.is_file()


def test_happy_path_publishes_hardware_and_scholarship_uof() -> None:
    ledger, receipts = run_pilot(
        DEFAULT_SYNTHETIC_V1_FIXTURE,
        finance_actor=FINANCE_ACTOR,
    )
    assert ledger.organization.id == CIVIC_FORGE
    assert {r.expenditure_expense_id for r in receipts} == {
        "exp_syn_001",
        "exp_syn_002",
        "exp_syn_003",
    }
    assert all(r.allocation_id in STABLE_ALLOCATION_IDS for r in receipts)
    assert {r.allocation_id for r in receipts} == {
        "alloc_community_hardware",
        "alloc_access_scholarships",
    }
    assert ledger.expenses["exp_syn_001"].state == ExpenseState.RECONCILED
    assert ledger.expenses["exp_syn_002"].state == ExpenseState.RECONCILED
    assert ledger.expenses["exp_syn_003"].state == ExpenseState.RECONCILED
    assert ledger.allocation_remaining_balance("alloc_community_hardware") == Decimal("47860.00")
    assert ledger.allocation_remaining_balance("alloc_access_scholarships") == Decimal("55380.00")


def test_public_allocation_ids_are_stable() -> None:
    data = load_fixture(DEFAULT_SYNTHETIC_V1_FIXTURE)
    assert data["organization"]["id"] == CIVIC_FORGE
    ids = [row["id"] for row in data["allocations"]]
    assert ids == list(STABLE_ALLOCATION_IDS)
    for alloc_id in ids:
        assert ALLOCATION_ID_RE.match(alloc_id)


def test_agent_proposed_program_spend_is_not_auto_approved() -> None:
    ledger, _receipts = run_pilot(
        DEFAULT_SYNTHETIC_V1_FIXTURE,
        finance_actor=FINANCE_ACTOR,
    )
    held = ledger.expenses["exp_syn_006"]
    assert held.state == ExpenseState.APPROVAL_PENDING
    assert held.state not in (ExpenseState.APPROVED, ExpenseState.RECONCILED)
    splits = [ea for ea in ledger.expense_allocations.values() if ea.expense_id == "exp_syn_006"]
    assert len(splits) == 1
    assert splits[0].allocation_id == "alloc_community_programs"
    assert ledger.allocation_remaining_balance("alloc_community_programs") == Decimal("0.00")


def test_facility_approval_fails_without_cleared_gifts() -> None:
    ledger = build_ledger_from_fixture(load_fixture(DEFAULT_SYNTHETIC_V1_FIXTURE))
    assert ledger.allocation_remaining_balance("alloc_facility_resilience") == Decimal("0.00")
    with pytest.raises(InvariantError, match="restricted allocation balance would go negative"):
        ledger.approve_expense("exp_syn_004", approved_by=FINANCE_ACTOR)


def test_missing_evidence_blocks_validator() -> None:
    data = load_fixture(DEFAULT_SYNTHETIC_V1_FIXTURE)
    missing = next(exp for exp in data["expenses"] if exp["id"] == "exp_syn_008")
    assert missing["evidence"] == []
    agent = EvidenceValidatorAgent()
    assert agent.assess(missing["evidence"]) == EvidenceSufficiency.MISSING
    estimate = next(exp for exp in data["expenses"] if exp["id"] == "exp_syn_006")
    assert agent.assess(estimate["evidence"]) == EvidenceSufficiency.PARTIAL


def test_duplicate_invoice_external_id_is_skipped() -> None:
    ledger, _receipts = run_pilot(
        DEFAULT_SYNTHETIC_V1_FIXTURE,
        finance_actor=FINANCE_ACTOR,
    )
    before = len(ledger.expenses)
    edge = load_fixture(DEFAULT_SYNTHETIC_V1_FIXTURE)["edge"]["duplicate_invoice"]
    assert edge["external_source_id"] == "acct_exp_syn_001"
    assert edge["content_digest"] == "sha256:synthetic001"
    ex = LedgerCommandExecutor(ledger, simulation=False)
    result = ex.execute(
        AgentCommand(
            command_type="import_normalized_expense",
            tenant_id=CIVIC_FORGE,
            payload={
                "expense": {
                    "external_source_id": edge["external_source_id"],
                    "vendor": edge["vendor"],
                    "amount": edge["amount"],
                    "currency": "USD",
                    "purchase_date": "2026-08-19",
                    "category": "CLASSROOM_HARDWARE",
                    "description": "Duplicate invoice test",
                    "evidence": [],
                }
            },
            required_authority=AuthorityLevel.L2_REVERSIBLE,
        )
    )
    assert result.status == "SUCCEEDED"
    assert result.output_refs == ["exp_syn_001"]
    assert len(ledger.expenses) == before


def test_correction_lineage_does_not_mutate_prior_receipt() -> None:
    ledger, receipts = run_pilot(
        DEFAULT_SYNTHETIC_V1_FIXTURE,
        finance_actor=FINANCE_ACTOR,
    )
    prior = next(r for r in receipts if r.expenditure_expense_id == "exp_syn_001")
    prior_hash = prior.receipt_hash
    prior_snap = ledger.get_receipt_snapshot(prior.receipt_id)

    reversed_exp, corrections = ledger.reverse_expense(
        "exp_syn_001",
        actor=FINANCE_ACTOR,
        reason="Synthetic append-only correction (edge_009)",
    )
    assert reversed_exp.state == ExpenseState.REVERSED
    assert len(corrections) == 1
    corr = corrections[0]
    assert corr.corrected is True
    assert corr.correction_kind == "REVERSAL"
    assert corr.corrects_receipt_id == prior.receipt_id
    assert corr.receipt_hash != prior_hash
    still = ledger.get_receipt(prior.receipt_id)
    assert still.receipt_hash == prior_hash
    assert ledger.get_receipt_snapshot(prior.receipt_id) == prior_snap


def test_unverified_outcome_cannot_publish_impact() -> None:
    ledger, _receipts = run_pilot(
        DEFAULT_SYNTHETIC_V1_FIXTURE,
        finance_actor=FINANCE_ACTOR,
    )
    data = load_fixture(DEFAULT_SYNTHETIC_V1_FIXTURE)
    edge = data["edge"]["unverified_outcome"]
    assert edge["claim_label"] == "NOT_COMPUTABLE"
    assert edge["verification_status"] == "proposed"

    ws = TenantWorkspace(ledger.organization, ledger=ledger)
    impact = ImpactService(ws)
    impact.register_program(
        Program(
            id="prog_syn_003",
            organization_id=CIVIC_FORGE,
            name="Facility Continuity Program",
        )
    )
    impact.submit_impact_event(
        ImpactEvent(
            id="evt_syn_unverified_005",
            organization_id=CIVIC_FORGE,
            program_id="prog_syn_003",
            event_type="FACILITY_DOWNTIME",
            event_date="2026-08-19",
            participants=0,
            state=ImpactEventState.SUBMITTED,
            description="Synthetic unverified downtime claim",
        )
    )
    assert ws.impact_events["evt_syn_unverified_005"].state == ImpactEventState.SUBMITTED
    with pytest.raises(StateError, match="IMPACT receipt requires VERIFIED"):
        impact.publish_impact_receipts("evt_syn_unverified_005", actor=FINANCE_ACTOR)


def test_public_impact_fixture_is_public_safe_and_not_observed() -> None:
    doc = _load(PUBLIC_IMPACT_FIXTURE)
    schema = _load(PUBLIC_IMPACT_SCHEMA)
    for key in schema["required"]:
        assert key in doc
    assert doc["source"] == "fixture:autogive-synthetic-v1"
    assert doc["authority"] == "public_aggregate_only"
    privacy = doc["privacy"]
    assert privacy["classification"] == "public_aggregate_only"
    assert privacy["piiAllowed"] is False
    assert privacy["donorNamesAllowed"] is False
    assert privacy["individualDonorAttributionAllowed"] is False
    assert privacy["operatorIdentityAllowed"] is False
    assert doc["summary"]["outcomeCount"] == len(doc["outcomes"]) == 4
    assert doc["summary"]["totalParticipantsPublic"] == 46
    public_ids = {row["allocationId"] for row in doc["outcomes"]}
    assert public_ids <= set(STABLE_ALLOCATION_IDS)
    assert "alloc_community_programs" not in public_ids
    assert "out_syn_005" not in json.dumps(doc)
    assert "NOT_COMPUTABLE" not in json.dumps(doc)
    blob = PUBLIC_IMPACT_FIXTURE.read_text(encoding="utf-8")
    for bad in BANNED_RESIDUE:
        assert bad not in blob, f"forbidden residue {bad}"
    assert_public_safe(doc)


def test_live_public_impact_stays_gated_empty() -> None:
    doc = _load(LIVE_PUBLIC_IMPACT)
    assert doc["source"] == "gated:public_shell"
    assert doc["outcomes"] == []
    assert doc["summary"]["outcomeCount"] == 0
    assert "OBSERVED" not in json.dumps(doc)
    assert "Civic Forge" not in json.dumps(doc)


def test_hacker_dojo_pilot_is_unchanged() -> None:
    hd, receipts = run_pilot(DEFAULT_FIXTURE)
    assert hd.organization.id == "org_hacker_dojo"
    assert receipts[0].expenditure_expense_id == "exp_soldering_842"
    assert receipts[0].allocation_id == "alloc_community_hardware"
    civic = build_ledger_from_fixture(load_fixture(DEFAULT_SYNTHETIC_V1_FIXTURE))
    assert civic.organization.id == CIVIC_FORGE
    assert "exp_soldering_842" not in civic.expenses
    assert "donor_alice" not in civic.donors


def test_civic_forge_policy_defaults_without_signed_pack() -> None:
    policy = default_policy(CIVIC_FORGE)
    assert policy.tenant_id == CIVIC_FORGE
    assert policy.requires_human("approve_expense")
    assert policy.requires_human("publish_use_of_funds_receipt")
