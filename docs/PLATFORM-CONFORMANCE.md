# Platform Conformance

## Purpose

This document defines the platform-level acceptance checks for repository readiness
and cross-links the required evidence for the SPEC-004 and SPEC-007 contracts.

Primary source of truth: `docs/platform-conformance.yml`.

## Scope and evidence contract

`docs/platform-conformance.yml` is a deterministic artifact with:

- a required check list,
- per-check evidence references (documents, tests, commands), and
- required evidence fields used for auditability.

CI validates that every required artifact path in that file exists.

## Current conformance inventory

| Check ID | Requirement | Evidence artifacts | Evidence fields |
|---|---|---|---|
| SPEC-004.01 | Domain model and aggregate boundaries | `docs/DOMAIN-MODEL.md`, `docs/HD-IR-001.md`, `docs/HD-IR-002.md`, `docs/HD-IR-004.md`, `docs/HD-IR-006.md` | `ledger aggregate`, `expense and attribution invariants`, `multi-tenant isolation`, `impact aggregate linkage`, `notification boundaries` |
| SPEC-004.02 | Domain invariants and money truth are regression-gated | `src/impact_relay/domain/ledger.py`, `tests/test_ledger_invariants.py` | `donation allocation caps`, `expense sum validation`, `restricted balance never negative`, `no silent mutation`, `single live receipt per triple` |
| SPEC-007.01 | Agent schema parity and versioned contracts | `src/impact_relay/agents/types.py`, `schemas/agents/*.schema.json`, `tests/test_agent_contract_schemas.py` | `AgentCommand`, `AgentProposal`, `ExecutionReceipt`, `ApprovalReceipt`, `AgentRunReceipt`, `ValidationResult` |
| SPEC-007.02 | L3 execution requires explicit human approval | `src/impact_relay/agents/authority.py`, `src/impact_relay/agents/base.py`, `tests/test_agent_contracts.py` | `requires_human_approval`, `tenant matching`, `approver identity guard`, `approval decision check` |
| SPEC-007.03 | Proposal execution safety and confidence gates | `src/impact_relay/agents/authority.py`, `src/impact_relay/agents/types.py`, `tests/test_agent_contracts.py` | `proposal expiry`, `confidence floor`, `contradiction rejection`, `agent propose ceilings` |
| SPEC-007.04 | End-to-end HD-IR-007 vertical slice contract | `src/impact_relay/agents/expense_workflow.py`, `src/impact_relay/agents/executor.py`, `tests/test_expense_approval_slice.py` | `simulation mode safe`, `idempotent import and dedupe`, `human approve/reject behavior`, `receipt lineage preserved`, `public-safe preview without donor ids` |
| SPEC-007.05 | Privacy sentinel for public-facing projections | `src/impact_relay/agents/privacy.py`, `tests/test_public_export.py`, `tests/test_digest_and_reconcile.py` | `public_aggregate_only`, `piiAllowed false`, `donorNamesAllowed false`, `attendeeNamesAllowed false` |

## Result protocol

- CI step `platform-conformance` runs `scripts/check_platform_conformance.py`.
- The check fails fast if any required artifact is missing.
- Optional follow-up expansion can enforce command execution checks if required later.

## Change control

Any edit to:
- required artifacts,
- checks,
- evidence fields,
- or schema shape,

must be reviewed as a platform contract change and reflected in commit notes,
`docs/PLATFORM-CONFORMANCE.md`, and `docs/platform-conformance.yml` together.
