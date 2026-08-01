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
- [x] Auto-save entity snapshot after durable seed / approve / worker (host-app query path).
- [x] S3-compatible object backend (`S3ObjectStorage` + SSE; MinIO endpoint supported).
- [x] OIDC identity boundary (ports + fixture mapper; host validates real JWTs).
- [x] Add RBAC roles: donor, finance reviewer, finance approver, program verifier, communications approver, auditor, tenant admin.
- [x] Enforce separation of duties (hard: no self-approve; agent principals rejected).

## P1 — Donor receipt experience

- [x] Add use-of-funds receipt detail API (`impact_relay.donor.DonorExperienceAPI`).
- [x] Add donor fund timeline API.
- [x] Add remaining designated-balance projection (allocation balances + receipt field).
- [x] Add direct and pooled attribution explanations.
- [x] Add receipt correction history.
- [x] Add evidence-safe attachments (donor_visible only + object_key).
- [x] Add notification preference model (topics, cadence, quiet hours).

## P1 — Program and impact linkage

- [x] Add `FundedAsset`, `Program`, and `ProgramOccurrence` entities (types + impact service).
- [x] Link expenses to funded assets (`FundedAsset.expense_id`).
- [x] Link funded assets to programs (via impact events / receipts).
- [x] Define activity evidence hierarchy (impact evidence states).
- [x] Add program-verifier approval command path (role + impact verify flow in domain).
- [x] Add canonical impact receipt.
- [x] Add cumulative usage projections (donor balances / allocation remaining).
- [x] Add invalid-event retraction flow (correction/reverse patterns; impact reject).

## P1 — Notifications

- [x] Add consent policy engine.
- [x] Add channel and cadence preferences.
- [x] Add quiet-hour deferral (`DEFERRED_QUIET_HOURS`).
- [x] Add deduplication keys.
- [x] Add email adapter (fixture + `EmailAdapter` protocol).
- [x] Add APNs/FCM adapter contract (placeholders + fixture push).
- [x] Add delivery receipts and permanent-failure classification.
- [x] Add unsubscribe and opt-out ingestion (preference enabled=False / consent revoke).

## P2 — Hacker Dojo pilot

- [x] Add `policies/tenants/hacker-dojo.v1.0.yaml` (canonical template for other nonprofits).
- [x] Document Hacker-Dojo app integration (canonical pilot; reusable for other nonprofits).
- [x] Host adapter façade (`impact_relay.host`) for Hacker-Dojo app + other nonprofit clones.
- [x] Confirm authoritative donation and accounting systems (documented assumptions in pilot doc).
- [x] Map finance roles and approval chain (`docs/pilot/HACKER-DOJO-PILOT.md` + RBAC).
- [x] Define first restricted hardware/community-class allocation (fixture Community Hardware Fund).
- [x] Select first donor cohort (fixture donors alice/bob; staff dry-run path).
- [x] Finance review console **API** (`FinanceConsole` + `console_server`); host UI pages in Hacker-Dojo app.
- [x] Donor timeline/receipt **API** (`DonorConsole` + donor routes); host UI pages in Hacker-Dojo app.
- [x] Run synthetic dry run (host session + `--all-phases`; see pilot doc).
- [ ] Run finance-controlled shadow mode (ops process).
- [ ] Run limited live cohort (ops process).
- [ ] Document pilot findings and approval decision (ops process).

## P2 — Operations and security

- [x] Threat model agent, finance, evidence, notification, and tenant boundaries.
- [x] Add structured logs for workflows (worker tick metrics); OTel reserved for v1.0.
- [x] Add audit explorer primitives (command log + entity list + events via stores).
- [x] Add incident response runbook.
- [x] Add provider outage and replay runbook.
- [x] Add retention and deletion policy (runbook).
- [x] Add backup and restoration test (rehydrate + snapshot tests).
- [x] Add security review checklist.

## Deferred

- SMS production delivery until explicit-consent and opt-out flows are validated.
- Multiple accounting providers until one pilot adapter is stable.
- Self-service nonprofit onboarding until Hacker Dojo reaches v1.0.
- Predictive donor scoring.
- Microservice decomposition.
- Autonomous financial approval.
- Host UI consoles (finance review / donor screens) — built in Hacker-Dojo app.
- Live OIDC JWT validation (host IdP SDK) and live Postmark/APNs credentials.
