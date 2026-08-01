# Impact Relay TODO

This backlog translates the roadmap into an implementation sequence. Items are ordered by dependency and risk.

## P0 — Governance and contracts

- [x] Define `AuthorityLevel`, `AgentCommand`, `AgentProposal`, `ValidationResult`, `ApprovalReceipt`, `ExecutionReceipt`, and `AgentRunReceipt`.
- [x] Add JSON Schemas for every cross-boundary contract.
- [x] Add policy-version and prompt-version fields to run receipts.
- [x] Implement deterministic authority checks.
- [x] Implement proposal expiration and idempotency keys.
- [x] Add simulation mode that cannot mutate domain state.
- [x] Prevent agent modules from importing ledger mutation APIs directly.
- [x] Add Privacy Sentinel allowlist validation for public and donor outputs.
- [x] Add cross-tenant command and projection tests.
- [x] Add adversarial fixtures for unsupported claims, PII leakage, duplicate events, and contradictory evidence.

## P0 — First vertical slice

- [x] Define normalized expense import contract.
- [x] Implement fixture-backed Expense Intake Agent.
- [x] Implement Allocation Classifier proposal output.
- [x] Implement Evidence Validator states: `MISSING`, `PARTIAL`, `SUFFICIENT`, `CONTRADICTORY`, `EXPIRED`, `REDACTION_REQUIRED`.
- [x] Build `FinanceReviewPacket` projection.
- [x] Add authenticated approval command abstraction (`ApprovalReceipt`).
- [x] Connect approved command to existing deterministic ledger.
- [x] Generate canonical use-of-funds receipt.
- [x] Create email preview from canonical receipt.
- [x] Require separate send approval.
- [x] Record fixture delivery receipt.
- [x] Test replay, duplicate input, rejection, and contradictory evidence (correction path uses existing ledger tests).

## P1 — Durable workflows

- [x] Select Temporal or document the bounded PostgreSQL worker alternative (PG worker for pilot; Temporal later — see DURABLE-WORKFLOWS.md).
- [x] Implement expense-to-receipt workflow state machine (MVP memory path M1–M6).
- [x] Add human approval pause/resume behavior.
- [x] Add retry policy and dead-letter state.
- [x] Add workflow replay / parity tests.
- [x] Add scheduled digest workflow (PR-L2 skeleton: assemble → privacy → optional ack).
- [x] Add correction and retraction workflow (PR-L1 reverse/supersede L3 + workflow).
- [x] Pilot P1: file ledger command log rehydrate + durable CLI (seed/list/approve/check).
- [x] Pilot P2: SQL WorkflowStore (SQLite default, Postgres + SKIP LOCKED optional).
- [x] Pilot P3: durable worker entrypoint (`--durable worker` / `python -m impact_relay.workflows.worker`) + restart runbook + K11 guard.
- [x] Docs alignment (PR-L3): evidence-before-classify; ROADMAP / DURABLE-WORKFLOWS status.

## P1 — Storage and service boundaries

- [x] Add multi-tenant storage design + SQLite migrate (Postgres DSN ready) — `docs/architecture/STORAGE.md`.
- [x] Tenant registry repository + Hacker Dojo canonical pilot / nonprofit template clone.
- [x] SQL `ledger_command_log` (K17 fold) alongside file log.
- [x] Object storage port (local FS pilot; S3 later) — tenant-scoped keys.
- [x] Structured event outbox skeleton.
- [x] Hacker-Dojo integration + template guide — `docs/HACKER-DOJO-INTEGRATION.md`.
- [x] Ledger entity SQL repo (`ledger_entity` / `ledger_meta`) — save/load + list expenses/receipts for host apps.
- [ ] Encrypted / S3-compatible object backend.
- [ ] OIDC identity boundary.
- [ ] Add RBAC roles: donor, finance reviewer, finance approver, program verifier, communications approver, auditor, tenant admin.
- [ ] Enforce separation of duties.

## P1 — Donor receipt experience

- [ ] Add use-of-funds receipt detail API.
- [ ] Add donor fund timeline API.
- [ ] Add remaining designated-balance projection.
- [ ] Add direct and pooled attribution explanations.
- [ ] Add receipt correction history.
- [ ] Add evidence-safe attachments.
- [ ] Add notification preference model.

## P1 — Program and impact linkage

- [ ] Add `FundedAsset`, `Program`, and `ProgramOccurrence` entities.
- [ ] Link expenses to funded assets.
- [ ] Link funded assets to programs.
- [ ] Define activity evidence hierarchy.
- [ ] Add program-verifier approval command.
- [ ] Add canonical impact receipt.
- [ ] Add cumulative usage projections.
- [ ] Add invalid-event retraction flow.

## P1 — Notifications

- [ ] Add consent policy engine.
- [ ] Add channel and cadence preferences.
- [ ] Add quiet-hour deferral.
- [ ] Add deduplication keys.
- [ ] Add email adapter.
- [ ] Add APNs/FCM adapter contract.
- [ ] Add delivery receipts and permanent-failure classification.
- [ ] Add unsubscribe and opt-out ingestion.

## P2 — Hacker Dojo pilot

- [x] Add `policies/tenants/hacker-dojo.v1.0.yaml` (canonical template for other nonprofits).
- [x] Document Hacker-Dojo app integration (canonical pilot; reusable for other nonprofits).
- [ ] Confirm authoritative donation and accounting systems.
- [ ] Map finance roles and approval chain.
- [ ] Define first restricted hardware/community-class allocation.
- [ ] Select first donor cohort.
- [ ] Build finance review console.
- [ ] Build donor timeline and receipt screen.
- [ ] Run synthetic dry run.
- [ ] Run finance-controlled shadow mode.
- [ ] Run limited live cohort.
- [ ] Document pilot findings and approval decision.

## P2 — Operations and security

- [ ] Threat model agent, finance, evidence, notification, and tenant boundaries.
- [ ] Add OpenTelemetry traces and structured logs.
- [ ] Add audit explorer.
- [ ] Add incident response runbook.
- [ ] Add provider outage and replay runbook.
- [ ] Add retention and deletion policy.
- [ ] Add backup and restoration test.
- [ ] Add security review checklist.

## Deferred

- SMS production delivery until explicit-consent and opt-out flows are validated.
- Multiple accounting providers until one pilot adapter is stable.
- Self-service nonprofit onboarding until Hacker Dojo reaches v1.0.
- Predictive donor scoring.
- Microservice decomposition.
- Autonomous financial approval.