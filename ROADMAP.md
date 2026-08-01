# Impact Relay Roadmap

Impact Relay is moving from a fixture-backed transparency prototype to a human-governed donor-impact platform. Milestones are capability gates, not calendar promises.

## Current baseline — v0.5

Shipped:

- deterministic donation, allocation, expense, attribution, and receipt domain;
- append-only corrections and receipt lineage;
- donor read projections;
- fixture-backed notification and impact services;
- multi-tenant domain isolation;
- privacy-safe public Pages exports;
- Every.org aggregate and Notion public-evidence bridges;
- **agent contracts (L0–L3), Privacy Sentinel, simulation executor** (HD-IR-007);
- **fixture expense → human approval → ledger → UOF vertical slice** (HD-IR-007);
- live Every.org OBSERVED dry-run validation + operator script.

Deferred:

- live accounting ingestion;
- production email, push, and SMS delivery;
- production multi-tenant DR / observability for workflows (pilot durable path **shipped**: memory MVP + SQLite/Postgres store + command log + worker CLI);
- authenticated finance console;
- native Hacker Dojo donor experience;
- human finance pilot sign-off.

## v0.5 — Agent Framework and Governance

**Goal:** establish bounded agent contracts without changing financial authority.

- [x] Add agent command, proposal, validation, approval, execution, and run-receipt models.
- [x] Add L0–L3 authority enforcement.
- [x] Add versioned policy loading (`policies/tenants/`, `impact_relay.policy`).
- [x] Separate proposal evaluation from command execution.
- [x] Add workflow state-machine contracts.
- [x] Add agent simulation/dry-run mode.
- [x] Add confidence, contradiction, and expiration behavior.
- [x] Add deterministic Privacy Sentinel gates.
- [x] Add adversarial agent test fixtures (PII, cross-tenant, self-approval).

**Exit gate:** no agent can directly approve an expense, publish a receipt, or deliver a notification. **Met in HD-IR-007.**

## v0.6 — Financial Review Engine

**Goal:** implement one complete expense-to-ledger human approval workflow.

- [x] Add normalized expense-provider adapter contract (fixture batch).
- [x] Add expense deduplication and evidence attachment.
- [x] Add allocation-classification proposals.
- [x] Add evidence sufficiency and redaction assessment.
- [x] Build finance review packets.
- [x] Add approval / rejection gates via `ApprovalReceipt` (authN UI still deferred).
- [x] Record approval receipts on the run.
- [x] Add durable retry and blocked-case handling (MVP M1–M6 memory runtime, worker, ops CLI, façade default runtime).

**Exit gate:** an imported expense can reach ledger approval only through an independently authenticated human decision. **Fixture + memory workflow path met; live OIDC and PG pilot still deferred.**

## v0.7 — Donor Receipt Engine

**Goal:** make verified fund use visible to affected donors.

- [ ] Add canonical use-of-funds receipt schema.
- [ ] Add direct, pro-rata pool, FIFO pool, cohort, and no-individual-attribution policies.
- [ ] Add donor-readable attribution explanations.
- [ ] Add receipt preview and publication approval.
- [ ] Add remaining designated-balance projection.
- [ ] Add correction, reversal, and supersession communication.
- [ ] Add evidence-safe donor attachments.
- [ ] Add authenticated donor receipt API.

**Exit gate:** a donor can see what approved funds were spent on, how attribution was calculated, and any later correction.

## v0.8 — Program and Impact Engine

**Goal:** connect expenditures to verified program activity and outcomes.

- [ ] Add funded-asset, program, and program-occurrence models.
- [ ] Link expenses to assets and programs.
- [ ] Add activity evidence hierarchy.
- [ ] Add staff verification workflow.
- [ ] Add canonical impact receipt schema.
- [ ] Distinguish scheduled, completed, verified, and published activity.
- [ ] Add cumulative asset-use and program metrics.
- [ ] Add correction/retraction behavior for invalid impact events.

**Exit gate:** a verified class or program event can produce a linked impact receipt without unsupported causal claims.

## v0.9 — Hacker Dojo Pilot

**Goal:** operate the first end-to-end deployment with real organizational review.

- [ ] Configure Hacker Dojo tenant policies.
- [ ] Integrate an authorized donation aggregate or provider feed.
- [ ] Integrate one accounting/expense source.
- [ ] Deploy finance review console.
- [ ] Deploy donor timeline and receipt-detail screens.
- [ ] Enable email and app push in controlled cohorts.
- [ ] Complete privacy, security, and finance review.
- [ ] Run correction and provider-outage exercises.
- [ ] Collect donor comprehension and notification-fatigue feedback.

**Exit gate:** Hacker Dojo leadership signs off on financial accuracy, donor language, privacy, and operating runbooks.

## v1.0 — Production Release

**Goal:** production-grade Hacker Dojo deployment.

- [ ] Durable workflow runtime and disaster recovery.
- [ ] Production observability, alerting, and audit explorer.
- [ ] OIDC, RBAC, and separation of duties.
- [ ] Encrypted evidence storage and retention controls.
- [ ] Production email and push delivery.
- [ ] Consent and preference center.
- [ ] SLA/SLO definitions and incident response.
- [ ] External security assessment.
- [ ] Data export and deletion workflows.

## v1.1 — Reusable Nonprofit Platform

**Goal:** support additional organizations without forking the product.

- [ ] Tenant onboarding and policy packs.
- [ ] White-label donor presentation.
- [ ] Provider adapter SDK.
- [ ] Organization-specific retention, evidence, and notification policies.
- [ ] Multiple finance roles and approval chains.
- [ ] Grant and restricted-fund templates.
- [ ] Tenant-level export and archival.

## v2.0 — General Impact Infrastructure

**Goal:** become reusable donor-impact middleware across nonprofits and civic organizations.

Candidate capabilities:

- multi-entity and fiscal-sponsor structures;
- grant deliverable tracking;
- beneficiary privacy controls;
- public transparency portals;
- donor API and webhooks;
- verified outcome taxonomies;
- cross-program portfolio reporting;
- standards-based accounting and CRM integrations.

## Non-goals before v1.0

- autonomous expense approval;
- autonomous attribution-policy selection;
- unrestricted natural-language mutation of the ledger;
- blockchain or tokenization;
- generalized predictive donor scoring;
- public exposure of donor-level financial records;
- microservice decomposition without demonstrated scaling need.