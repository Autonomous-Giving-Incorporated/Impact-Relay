# Impact Relay TODO

This backlog translates the roadmap into an implementation sequence. Items are ordered by dependency and risk.

## P0 — Governance and contracts

- [ ] Define `AuthorityLevel`, `AgentCommand`, `AgentProposal`, `ValidationResult`, `ApprovalReceipt`, `ExecutionReceipt`, and `AgentRunReceipt`.
- [ ] Add JSON Schemas for every cross-boundary contract.
- [ ] Add policy-version and prompt-version fields to run receipts.
- [ ] Implement deterministic authority checks.
- [ ] Implement proposal expiration and idempotency keys.
- [ ] Add simulation mode that cannot mutate domain state.
- [ ] Prevent agent modules from importing ledger mutation APIs directly.
- [ ] Add Privacy Sentinel allowlist validation for public and donor outputs.
- [ ] Add cross-tenant command and projection tests.
- [ ] Add adversarial fixtures for unsupported claims, PII leakage, duplicate events, and contradictory evidence.

## P0 — First vertical slice

- [ ] Define normalized expense import contract.
- [ ] Implement fixture-backed Expense Intake Agent.
- [ ] Implement Allocation Classifier proposal output.
- [ ] Implement Evidence Validator states: `MISSING`, `PARTIAL`, `SUFFICIENT`, `CONTRADICTORY`, `EXPIRED`, `REDACTION_REQUIRED`.
- [ ] Build `FinanceReviewPacket` projection.
- [ ] Add authenticated approval command abstraction.
- [ ] Connect approved command to existing deterministic ledger.
- [ ] Generate canonical use-of-funds receipt.
- [ ] Create email preview from canonical receipt.
- [ ] Require separate send approval.
- [ ] Record fixture delivery receipt.
- [ ] Test replay, duplicate input, rejection, correction, and partial failure.

## P1 — Durable workflows

- [ ] Select Temporal or document the bounded PostgreSQL worker alternative.
- [ ] Implement expense-to-receipt workflow state machine.
- [ ] Add human approval pause/resume behavior.
- [ ] Add retry policy and dead-letter state.
- [ ] Add workflow replay tests.
- [ ] Add scheduled digest workflow.
- [ ] Add correction and retraction workflow.

## P1 — Storage and service boundaries

- [ ] Add PostgreSQL persistence design and migrations.
- [ ] Add repository interfaces for ledger, receipts, evidence, approvals, consent, and workflows.
- [ ] Add encrypted object storage interface for receipts and invoices.
- [ ] Add structured event outbox.
- [ ] Add OIDC identity boundary.
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

- [ ] Add `policies/tenants/hacker-dojo.yaml`.
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