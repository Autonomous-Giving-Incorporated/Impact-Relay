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
- Every.org aggregate and Notion public-evidence bridges (fixture-file normalizers with safety validation; no network fetchers yet);
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
- production email, push, and SMS credentials (fixture adapters shipped; APNs/FCM clients are protocol placeholders);
- production multi-tenant workflow DR / multi-region observability;
- live OIDC JWT validation wiring (library now ships a JWKS provider, `impact_relay.auth.jwt_oidc`; the host must point it at a real issuer or keep terminating auth at its gateway);
- execute live finance cohort and fill `docs/pilot/FINDINGS.md`;
- leadership sign-off on language, privacy, and operating runbooks.

Closed in v0.9.1 (previously the honest gaps between the language above and the code):

- `console_server` is now default-deny — a resolved principal is required for every `/api` route except health, identity headers are ignored unless `--trusted-proxy`, and the old fail-open behaviour is an explicit `--allow-unauthenticated-pilot` opt-in;
- the donor API fails closed when a donor-only principal has no `donor_id` claim;
- dual control is enforced rather than a no-op branch;
- Postgres runs in CI against a service container, and the SKIP LOCKED test is asserted not to skip;
- ruff and mypy gate CI; version metadata matches this roadmap.

Still open (needs credentials or live endpoints, not code):

- SMTP/Postmark and APNs/FCM client implementations behind the shipped protocols;
- HTTP fetchers for the Every.org and Notion bridges (fixture-file path works today).

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
- [ ] Integrate an authorized OBSERVED donation aggregate (dry-run path exists). *(ops: requires authorized live data)*
- [ ] Integrate one live accounting/expense source (fixture batch only today). *(ops: requires provider access; adapter code is agent work — see v0.9.1)*
- [ ] Enable email and app push in controlled cohorts (fixture adapters only). *(ops: credentials; adapter implementations are agent work — see v0.9.1)*
- [ ] Complete privacy, security, and finance review with leadership. *(human)*
- [ ] Run correction and provider-outage exercises with operators. *(human)*
- [ ] Execute live cohort and fill findings template. *(human)*
- [ ] Collect donor comprehension and notification-fatigue feedback. *(human)*

**Exit gate:** Hacker Dojo leadership signs off on financial accuracy, donor language, privacy, and operating runbooks.

> Remaining v0.9 items are ops/human-gated. Autonomous coding work should target v0.9.1 below.

## v0.9.1 — Hardening and Fidelity (agent-executable)

**Goal:** close every gap that pure library/CI/docs work can close, so that only credentials, live data, and human sign-off separate the pilot from v1.0. Every item here is verifiable offline by the test suite and CI — suitable for an autonomous coding loop. Order within each track is priority order.

### Track A — Security hardening (do first)

- [x] Default-deny `console_server` auth: require a resolved principal for **all** mutating routes (approve, seed) regardless of whether identity headers are present; add an explicit `--allow-unauthenticated-pilot` opt-in flag for the current behavior; reject header-only identity unless a `--trusted-proxy` mode is enabled. (`src/impact_relay/console_server.py:103-116`, `src/impact_relay/host/session.py:186`)
- [x] Correct HTTP semantics in `console_server`: 401 unauthenticated / 403 unauthorized / 404 unknown case / 500 internal, instead of blanket 400 with raw exception text; stop leaking exception messages; cap request body size; tighten CORS from `*`.
- [x] Negative-path tests in `tests/test_console_api.py`: unauthenticated approve rejected, wrong-role approve rejected, oversized body rejected, unknown case 404.
- [x] Fail-closed donor access: a donor-role principal whose claims lack `donor_id` must be denied, not waved through; decide and document behavior for `principal=None`. (`src/impact_relay/donor/api.py:53-58`, `src/impact_relay/auth/roles.py:44`) + tests.
- [x] Implement the soft separation-of-duties dual-control branch (currently a `pass`) or explicitly downgrade it to a documented advisory with a logged warning. (`src/impact_relay/auth/rbac.py:76-86`) + tests.
- [x] Fix silent `except ValueError: pass` in `console_server.resolve_principal` (hides auth misconfiguration); narrow the ~23 broad `except Exception` sites where a specific exception is knowable.

### Track B — Tooling and CI

- [x] Add `ruff` (lint + format) and `mypy` configuration to `pyproject.toml` dev extras; fix resulting findings (codebase is already fully annotated — cost is low).
- [x] Add lint + typecheck jobs to `.github/workflows/validate-and-deploy.yml`.
- [x] Add a Postgres service container to CI and set `IMPACT_RELAY_DATABASE_URL` so the env-gated `SKIP LOCKED` test runs (`tests/test_workflow_sql_store.py:273`; credentials already in `docker-compose.postgres.yml`).
- [x] Align version metadata with the roadmap (`pyproject.toml` and `src/impact_relay/__init__.py`, currently `0.5.0`).

### Track C — Library completions (pure code; credentials remain ops)

- [x] JWKS-based `OidcIdentityProvider` implementing the existing port (`src/impact_relay/auth/oidc.py`), as an optional extra (e.g. PyJWT) — keeps the zero-runtime-dependency base intact.
- [ ] Real SMTP/Postmark email adapter and APNs/FCM clients behind the existing protocols in the notifications layer, env-configured, as optional extras; fixture adapters remain the test path.
- [ ] Optional HTTP fetchers for the Every.org aggregate and Notion public-evidence bridges, feeding the **existing** safety validators (`src/impact_relay/every_org.py`, `src/impact_relay/notion_public.py`) — the PII firewall stays deterministic and mandatory.
- [x] Add the missing cross-boundary JSON Schemas: `agent-command`, `execution-receipt`, `validation-result` (`schemas/agents/` has only 3 of ~6 contracts).

### Track D — Documentation fidelity

- [x] `AGENTS.md`: fix workflow-state order (evidence **before** classify, matching `src/impact_relay/workflows/machine.py`); correct the exception-state list (`DELIVERY_FAILED` doesn't exist; `SUPERSEDED`/`REVERSED` are expense states); replace the fictional `ApprovedProposal` executor snippet with the real `execute(command, *, approval, agent_name, proposal)` signature from `src/impact_relay/agents/base.py`. *(AGENTS.md changes require independent human review per its own change-control rule — propose via PR, do not self-merge.)*
- [x] `docs/architecture/DURABLE-WORKFLOWS.md`: update the testing-strategy table to real test filenames; `store_postgres.py` → `store_sql.py`; fix the stale cross-reference note about AGENTIC-SYSTEM.md.
- [x] `docs/architecture/AGENTIC-SYSTEM.md`: label the ExecutionReceipt/contract YAML and the "recommended production stack" (FastAPI/Pydantic/SQLAlchemy) as design-level/aspirational — the shipped package is stdlib-only, Python ≥3.11.
- [x] Add `docs/HD-IR-001.md` (or a pointer note in `docs/pilot-systems-of-record.md`) so the referenced first milestone exists.
- [x] Reconcile auth terminology in one place: Supabase is Hacker Dojo's actual host IdP (header bridge + `auth/role_map.py`); OIDC ports are the generic library boundary (`docs/HACKER-DOJO-INTEGRATION.md`).
- [x] README repo map: add `policy.py`, `digest.py`, `reconcile.py`, `public_impact.py`, `agents/executor.py`, `agents/ledger_binding.py`.
- [x] Small code-doc mismatches: `redacted_public_copy` docstring says "shallow" but recurses (`src/impact_relay/agents/privacy.py:104`); brittle blanket `?`→`%s` replacement in `src/impact_relay/workflows/store_sql.py:877-883`.

**Exit gate:** unauthenticated or under-privileged requests cannot mutate anything even in pilot mode; CI enforces lint, types, and the Postgres path; every doc claim matches shipped code. All verifiable by `pytest` + CI — no credentials or human review required except the AGENTS.md PR.

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
