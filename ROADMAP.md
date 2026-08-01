# Impact Relay Roadmap

Impact Relay is moving from a fixture-backed transparency prototype to a human-governed donor-impact platform. Milestones are capability gates, not calendar promises.

## Current baseline — library + pilot host path

Shipped:

- deterministic donation, allocation, expense, attribution, and receipt domain;
- append-only corrections and receipt lineage (ledger + correction workflows);
- donor read projections and authenticated donor experience API;
- program / funded-asset / impact receipt domain;
- fixture-backed notification adapters and consent/preference model;
- multi-tenant domain isolation + tenant registry / clone-from-Hacker-Dojo template;
- privacy-safe public Pages exports;
- Every.org aggregate and Notion public-evidence bridges;
- agent contracts (L0–L3), Privacy Sentinel, simulation executor (HD-IR-007);
- fixture expense → human approval → ledger → UOF vertical slice (HD-IR-007);
- durable workflow pilot path: memory MVP + SQLite/Postgres store + command log (K11/K17) + worker CLI;
- storage ports: SQL ledger entities, local FS + S3 object storage, outbox skeleton;
- RBAC roles, separation of duties, OIDC identity ports, Hacker-Dojo campaign role map;
- host façade (`impact_relay.host`), finance/donor console APIs, pilot `console_server`;
- Hacker-Dojo host screens + shadow/live-cohort runbooks (sibling repo);
- ops docs: threat model, incident response, runbooks, security checklist, findings template.

Open (ops / production):

- live accounting ingestion beyond fixture batch;
- production email, push, and SMS credentials (adapters exist);
- production multi-tenant workflow DR / multi-region observability;
- live OIDC JWT validation in host IdP SDK (library ports + fixture mapper shipped);
- execute live finance cohort and fill `docs/pilot/FINDINGS.md`;
- leadership sign-off on language, privacy, and operating runbooks.

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
- [x] Add approval / rejection gates via `ApprovalReceipt` (live host auth via Supabase bridge; library OIDC ports).
- [x] Record approval receipts on the run.
- [x] Add durable retry and blocked-case handling (MVP M1–M6 memory runtime, worker, ops CLI, façade default runtime).
- [x] Pilot durable path: ledger command log (K17), SQL WorkflowStore (SQLite / Postgres), worker entrypoint + restart runbook.
- [x] Correction workflow + L3 `reverse_expense` / `supersede_expense` (K15).
- [x] Scheduled digest workflow skeleton (assemble → privacy → optional ack).
- [x] Finance console API + pilot HTTP server; host UI in Hacker-Dojo app.

**Exit gate:** an imported expense can reach ledger approval only through an independently authenticated human decision. **Fixture + durable pilot + host console path met; production multi-tenant DR still deferred.**

## v0.7 — Donor Receipt Engine

**Goal:** make verified fund use visible to affected donors.

- [x] Add canonical use-of-funds receipt schema.
- [x] Add direct, pro-rata pool, FIFO pool, cohort, and no-individual-attribution policies (domain methods + policy pack).
- [x] Add donor-readable attribution explanations (`DonorExperienceAPI` / `ATTRIBUTION_EXPLANATIONS`).
- [x] Add receipt preview and publication approval (agent slice + L3 gates).
- [x] Add remaining designated-balance projection.
- [x] Add correction, reversal, and supersession **ledger + workflow** path.
- [x] Add evidence-safe donor attachments.
- [x] Add authenticated donor receipt API (`impact_relay.donor` + optional Principal).
- [x] Donor console API + host donor timeline/receipt screens (Hacker-Dojo).

**Exit gate:** a donor can see what approved funds were spent on, how attribution was calculated, and any later correction. **Library + host pilot path met; production notification delivery still host credentials.**

## v0.8 — Program and Impact Engine

**Goal:** connect expenditures to verified program activity and outcomes.

- [x] Add funded-asset, program, and program-occurrence models.
- [x] Link expenses to assets and programs.
- [x] Add activity evidence hierarchy.
- [x] Add program-verifier approval command path (role + domain verify flow).
- [x] Add canonical impact receipt schema.
- [x] Distinguish scheduled, completed, verified, and published activity (domain states).
- [x] Add cumulative asset-use and program metrics (donor balances / allocation remaining).
- [x] Add correction/retraction behavior for invalid impact events.

**Exit gate:** a verified class or program event can produce a linked impact receipt without unsupported causal claims. **Domain library met; richer staff verification UI remains host product work.**

## v0.9 — Hacker Dojo Pilot

**Goal:** operate the first end-to-end deployment with real organizational review.

- [x] Configure Hacker Dojo tenant policies (`policies/tenants/hacker-dojo.v1.0.yaml`).
- [x] Document authoritative donation/accounting assumptions and role map.
- [x] Deploy finance review console API + host screens.
- [x] Deploy donor timeline and receipt-detail screens.
- [x] Shadow-mode and live-cohort runbooks; MFA gate for privileged host roles.
- [ ] Integrate an authorized OBSERVED donation aggregate (dry-run path exists).
- [ ] Integrate one live accounting/expense source (fixture batch only today).
- [ ] Enable email and app push in controlled cohorts (fixture adapters only).
- [ ] Complete privacy, security, and finance review with leadership.
- [ ] Run correction and provider-outage exercises with operators.
- [ ] Execute live cohort and fill findings template.
- [ ] Collect donor comprehension and notification-fatigue feedback.

**Exit gate:** Hacker Dojo leadership signs off on financial accuracy, donor language, privacy, and operating runbooks.

## v1.0 — Production Release

**Goal:** production-grade Hacker Dojo deployment.

- [ ] Production durable workflow DR / multi-region (pilot local+SQL path already on main).
- [ ] Production observability, alerting, and audit explorer.
- [ ] Live OIDC JWT validation in host gateway (library ports + RBAC already shipped).
- [ ] Encrypted evidence storage and retention controls (object ports + SSE option exist).
- [ ] Production email and push delivery.
- [ ] Consent and preference center (model shipped; full UX deferred).
- [ ] SLA/SLO definitions and incident response (runbooks drafted; SLOs not signed).
- [ ] External security assessment.
- [ ] Data export and deletion workflows.

## v1.1 — Reusable Nonprofit Platform

**Goal:** support additional organizations without forking the product.

- [x] Tenant onboarding template clone from Hacker Dojo (`clone_tenant_from_hacker_dojo` / `open_host_session`).
- [ ] White-label donor presentation.
- [ ] Provider adapter SDK.
- [ ] Organization-specific retention, evidence, and notification policies (policy pack path exists; self-serve UX deferred).
- [ ] Multiple finance roles and approval chains (RBAC roles shipped; multi-step chains deferred).
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
