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

- CI step `platform-conformance` runs `scripts/check_platform_conformance.py` in structural validation mode.
- The structural check fails fast if any required artifact is missing or if the manifest shape is invalid.
- Operators can run `python3 scripts/check_platform_conformance.py --run-commands` to execute the unique evidence commands declared in `docs/platform-conformance.yml`.
- Evidence command execution is deduplicated by exact command string and fails fast with owning check IDs in the error output.
- This keeps the default CI gate deterministic while enabling a stronger manual or future-CI verification mode.

## Change control

Any edit to:
- required artifacts,
- checks,
- evidence fields,
- or schema shape,

must be reviewed as a platform contract change and reflected in commit notes,
`docs/PLATFORM-CONFORMANCE.md`, and `docs/platform-conformance.yml` together.

## Autonomous Giving platform pin

Cross-suite platform canon is pinned at **Specs v1.0.0**:

- Release: https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Specs/releases/tag/v1.0.0
- Manifest: [`platform-spec/conformance.yml`](../platform-spec/conformance.yml)
- Notes: [`platform-spec/README.md`](../platform-spec/README.md)

This is distinct from the product inventory in `docs/platform-conformance.yml` (HD-IR / agent checks above).

## Allocation middleware (product direction)

Suite design for **transaction-light allocation middleware** (every.org → pots → human allocate → proof → packet):

- [docs/ALLOCATION-MIDDLEWARE.md](ALLOCATION-MIDDLEWARE.md) — Impact Relay’s proof/trail role  
- [Specs design](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Specs/blob/main/docs/superpowers/specs/2026-08-03-allocation-middleware-design.md)  

Middleware does not replace HD-IR checks; it consumes the same evidence discipline without requiring deep financial system integration.

