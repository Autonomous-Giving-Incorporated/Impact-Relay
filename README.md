# Impact Relay

**Donation fund-use transparency and impact notification infrastructure.**

Impact Relay connects a donation to its approved allocation, connects that allocation to actual expenditures, and connects those expenditures to verified programs and outcomes. Donors receive clear, consent-aware receipts explaining both **what their money was used for** and **what that use subsequently enabled**.

> AI proposes. Deterministic services validate. Authorized humans approve. The ledger records. Receipts preserve lineage.

[Live public tracker](https://autogive.app/impact-relay/) · [GitHub Pages fallback](https://scrimshawlife-ctrl.github.io/Impact-Relay/)

Impact Relay is an AGI product. Autonomously Giving Incorporated is the customer-facing corporate brand; Zero State is credited only as the software builder.

**Suite UI/UX:** public surfaces must stay consistent with [AGI](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated) and [Fund Intel](https://github.com/scrimshawlife-ctrl/Fund-Intel) (shared identity, tokens, type, navigation, footer). See [docs/AGI-DESIGN-SYSTEM.md](docs/AGI-DESIGN-SYSTEM.md) and [design.md](design.md).

---

## Allocation middleware

Suite product: transaction-light **allocation middleware** (canonical **every.org**). Impact Relay’s role is **proof and trail**, not gift ingestion or approval.

**Status:** MVP packages (pots → allocate → lightweight proof/packet) ship in [Fund-Intel `services/allocation-middleware/`](https://github.com/scrimshawlife-ctrl/Fund-Intel/tree/main/services/allocation-middleware). This repo keeps full ledger, UOF/impact receipts, and public aggregate surfaces; optional deeper binding is a later integration.

See [docs/ALLOCATION-MIDDLEWARE.md](docs/ALLOCATION-MIDDLEWARE.md).

## Why Impact Relay

Most donation products stop at payment confirmation. Accounting systems know what was purchased, program systems know what occurred, and communication systems send updates—but donors rarely receive a trustworthy, attributable explanation of the complete chain.

Impact Relay produces two linked artifacts:

1. **Use-of-funds receipt** — what was purchased or paid for, the approved amount, allocation, attribution method, date, vendor, evidence, and remaining designated balance.
2. **Impact receipt** — what the approved expenditure or funded asset later enabled, such as a verified community class, equipment deployment, or program milestone.

### Example

```text
$1,000 donation
→ Community Hardware Fund
→ $720 robotics-kit purchase approved by finance
→ donor receives use-of-funds receipt
→ kits used in a verified community class
→ donor receives impact receipt
→ later refund produces a visible correction receipt
```

For pooled funds, Impact Relay explains that a donation **contributed to the fund** supporting an expenditure. It never claims that specific dollars purchased a specific item unless direct restricted attribution is verifiable.

---

## Product principles

- Financial truth is append-only after approval.
- Donation allocations cannot exceed cleared funds.
- Restricted allocation balances cannot become negative.
- Attribution is explicit, versioned, and reproducible.
- AI may collect evidence and propose actions; it may not approve financial claims.
- Use-of-funds and impact receipts remain distinct but linked.
- Published corrections preserve the original receipt and full lineage.
- Public exports contain no donor PII or individual gift records.
- Synthetic and fixture data can never be labeled `OBSERVED`.

See [ENGINEERING_PRINCIPLES.md](ENGINEERING_PRINCIPLES.md).

---

## Current maturity

**Package version:** `0.9.1` (capability gates through **v0.7 library + pilot host path** are implemented; live production ops remain open).

**Current state:** reusable multi-tenant Python library with durable SQLite/Postgres workflows, L0–L3 agent contracts, donor and finance console APIs, S3-capable object storage ports, and deterministic observability summaries, plus a Hacker Dojo host bridge (static screens + Supabase role mapping). Public Pages stay fixture/aggregate-only until authorized OBSERVED aggregates are applied. **Ops remaining:** execute live cohort and fill [FINDINGS](docs/pilot/FINDINGS.md); production IdP JWT validation and live notification credentials stay host-owned.

### Shipped capabilities

| Capability | Module / surface |
|---|---|
| Donation, allocation, expense, attribution ledger | `src/impact_relay/domain/ledger.py` |
| Append-only correction and receipt lineage | domain + `workflows/corrections.py` |
| Programs, funded assets, impact receipts | `src/impact_relay/domain/impact.py` |
| Donor balances, timeline, receipt detail API | `domain/donor_views.py` · `donor/` |
| Donor-scoped data export and notification-state deletion primitives | `privacy_ops.py` |
| Consent, preferences, fixture + SMTP/Postmark email + APNs/FCM push delivery | `domain/notifications.py` · `notifications/` |
| Multi-organization domain isolation | `domain/tenant.py` · `storage/tenants.py` |
| Agent contracts L0–L3, Privacy Sentinel, simulation | `src/impact_relay/agents/` |
| Expense intake → human approval → UOF slice | `agents/expense_workflow.py` · `accounting.py` · [HD-IR-007](docs/HD-IR-007.md) |
| Durable workflows (memory + SQLite/Postgres) | `workflows/` · [DURABLE-QUICKSTART](docs/DURABLE-QUICKSTART.md) |
| Ledger command log rehydrate (K11/K17) | `domain/ledger_log.py` · `storage/command_log.py` |
| Tenant registry, SQL ledger entities, outbox | `storage/` · [STORAGE](docs/architecture/STORAGE.md) |
| Object storage (local FS + S3/MinIO, SSE + retention purge controls) | `storage/objects.py` |
| RBAC roles, SoD, OIDC ports, HD role map | `auth/` |
| Host façade + finance/donor consoles | `host/` · `console_server.py` |
| Hacker Dojo canonical pilot / clone template | `storage/template.py` · [integration](docs/HACKER-DOJO-INTEGRATION.md) |
| Aggregate public tracker and privacy-safe exports | GitHub Pages + `data/` |
| Every.org aggregate and Notion public-evidence bridges | CLI adapters and runbooks |
| Operational health and metrics summaries | `observability.py` |
| Ops threat model, runbooks, pilot findings template | `docs/ops/` · `docs/pilot/` |

### Deferred / host-owned production capabilities

- live accounting provider credentials/authorized endpoint mapping (HTTPS JSON adapter boundary shipped; fixture batch remains default);
- production Every.org donation ingestion (aggregate dry-run path exists);
- production multi-region workflow DR and production alerting/SLO dashboards (pilot local+SQL path, object retention controls, and deterministic observability summaries shipped);
- live OIDC JWT validation inside the library (host IdP SDK validates; ports + fixture mapper shipped);
- production SMTP/Postmark/APNs/FCM credentials plus host donor-address/device-token resolvers; SMS production client remains open (fixture delivery remains default);
- human finance live-cohort execution and findings fill (runbooks ready);
- self-service multi-nonprofit onboarding UI and full privacy self-service UX (clone-from-Hacker-Dojo template API plus donor data export/deletion primitives shipped).

---

## Governed agentic architecture

Agents operate above the deterministic domain. They prepare evidence and proposals; they do not become an alternate ledger.

```text
Donation and accounting providers
        │
        ▼
Provider adapters
        │ normalized records
        ▼
Agent workflow layer  (+ durable WorkflowStore)
        │ proposals, evidence checks, review packets
        ▼
Human approval gates  (console API / host UI / CLI)
        │ approved commands + ApprovalReceipt
        ▼
Deterministic domain services
        │ ledger events and canonical receipts
        ▼
Donor projections, host APIs, notification adapters
```

### Initial agent topology

- Orchestrator
- Donation Intake
- Expense Intake
- Allocation Classifier
- Evidence Validator
- Finance Review
- Attribution
- Use-of-Funds Receipt
- Asset and Program Linkage
- Impact Verification
- Impact Receipt
- Consent and Preference
- Notification Composer
- Delivery
- Correction and Retraction
- Privacy Sentinel
- Audit and Provenance

Consequential actions require independently authenticated human approval. Full contracts and authority rules are defined in [AGENTS.md](AGENTS.md).

---

## First production workflow

HD-IR-007 ships the fixture-backed core of the vertical slice (through ledger commit + optional UOF publish). Durable pilot and host console extend the same path:

```text
fixture or accounting expense          ✅
→ allocation proposal                  ✅
→ evidence validation                  ✅
→ finance approval (ApprovalReceipt)   ✅ CLI / console / host UI
→ durable wait / worker advance        ✅
→ ledger commit + entity snapshot      ✅
→ donor attribution + UOF receipt      ✅
→ email preview                        ✅
→ independent send approval            ✅
→ fixture delivery receipt             ✅
```

```bash
# Demo the agent vertical slice
python -m impact_relay --expense-approval-slice
python -m impact_relay --expense-approval-slice --no-approve
python -m impact_relay --expense-approval-slice --simulate-agents
python -m impact_relay --expense-approval-slice --send-email

# Easy durable pilot (SQLite under --data-dir)
python -m impact_relay --durable seed
python -m impact_relay --durable list
python -m impact_relay --durable approve
python -m impact_relay --durable check
python -m impact_relay --durable status

# Synthetic shadow checklist (library path; not live-cohort sign-off)
python -m impact_relay --shadow-rehearsal --data-dir .impact-relay/shadow-rehearsal

# Validate a live Every.org aggregate without writing (path must not be under fixtures/)
python -m impact_relay --validate-every-org-aggregate ~/private/every_org_live.json
./scripts/apply_live_every_org_aggregate.sh --dry-run ~/private/every_org_live.json
```

See [docs/HD-IR-007.md](docs/HD-IR-007.md), [docs/DURABLE-QUICKSTART.md](docs/DURABLE-QUICKSTART.md), and [docs/EVERYORG-AGGREGATE-RUNBOOK.md](docs/EVERYORG-AGGREGATE-RUNBOOK.md).

---

## Host apps (Hacker Dojo canonical)

Impact Relay is a **library**. Hacker Dojo is the **canonical host** (UX, Supabase auth, campaign ops). Other nonprofits clone the same shape.

```bash
# Console API for host static pages
python -m impact_relay.console_server --data-dir .impact-relay/hacker-dojo --port 8787
```

```python
from impact_relay.host import open_hacker_dojo_session
from impact_relay.host.hacker_dojo import finance_approver_fixture

with open_hacker_dojo_session(".impact-relay/hacker-dojo") as session:
    session = session.with_principal(finance_approver_fixture())
    session.seed()
    waiting = session.list_waiting()
    if waiting["cases"]:
        session.approve(workflow_id=waiting["cases"][0]["workflow_id"])
```

Host screens live in the sibling [Hacker-Dojo](https://github.com/scrimshawlife-ctrl/Hacker-Dojo) repo (`finance-impact.html`, `donor-impact.html`, `workspace/impact-relay-bridge.js`). Full wiring: [docs/HACKER-DOJO-INTEGRATION.md](docs/HACKER-DOJO-INTEGRATION.md).

---

## Money invariants

The existing domain enforces the regression bar:

- donation allocations never exceed the cleared donation amount;
- approved expense allocations sum to the expense amount;
- restricted allocation remaining balance cannot go negative on approval;
- verified use-of-funds receipts originate only from approved or reconciled expenses;
- an attribution method is required and donor attribution cannot exceed the donation allocation;
- only one live use-of-funds receipt exists per donation, expense, and allocation tuple;
- corrections are append-only and prior receipts are never rewritten.

These rules outrank model output, operator convenience, and provider data.

---

## Public tracker and privacy boundary

The GitHub Pages surface publishes aggregate campaign progress, public use-of-funds receipts, public impact outcomes, and event digests. It does not store donor names, emails, phone numbers, addresses, private notes, or individual gift records.

| Allowed publicly | Prohibited publicly |
|---|---|
| Aggregate raised and committed amounts | Donor names |
| Aggregate donor count | Emails, phones, or addresses |
| Approved public expenditure summaries | Individual gift amounts |
| Public impact events | Private CRM or finance notes |
| Campaign milestones and processor deep links | Service credentials or raw invoices |

Canonical aggregate state is stored in `data/impact-state.json` and validated against `schemas/impact-state.schema.json` in CI. Pilot data directories (`.impact-relay/…`) are local/staging only and must not be committed with PII.

---

## Repository map

```text
Impact-Relay/
├── README.md
├── VISION.md · AGENTS.md · ENGINEERING_PRINCIPLES.md
├── ROADMAP.md · TODO.md · SECURITY.md
├── docs/
│   ├── DURABLE-QUICKSTART.md
│   ├── HACKER-DOJO-INTEGRATION.md
│   ├── EVERYORG-AGGREGATE-RUNBOOK.md
│   ├── HD-IR-001.md … HD-IR-007.md      # milestone notes
│   ├── architecture/
│   │   ├── AGENTIC-SYSTEM.md
│   │   ├── DURABLE-WORKFLOWS.md
│   │   └── STORAGE.md
│   ├── ops/                             # threat model, runbooks, checklist
│   └── pilot/                           # HD pilot + FINDINGS template
├── src/impact_relay/
│   ├── domain/                          # ledger, impact, notifications, tenant
│   ├── agents/                          # L0–L3 contracts, executor, privacy sentinel
│   ├── workflows/                       # durable runtime, worker, corrections
│   ├── storage/                         # SQL store, objects, tenants, template
│   ├── auth/                            # principal, RBAC, OIDC ports + JWKS, role map
│   ├── host/                            # session façade, finance/donor console
│   ├── donor/                           # donor experience API
│   ├── notifications/                   # delivery adapters
│   ├── console_server.py                # pilot HTTP API for host UIs
│   ├── pilot.py · cli.py · policy.py    # phases, CLI, versioned policy packs
│   ├── public_export.py · public_impact.py · digest.py · reconcile.py
│   └── every_org.py · notion_public.py  # aggregate + evidence bridges
├── policies/tenants/                    # e.g. hacker-dojo.v1.0.yaml
├── fixtures/ · schemas/ · data/
├── tests/ · scripts/
├── index.html · app.js · styles.css     # public Pages tracker
└── .github/workflows/
```

Architecture detail: [docs/architecture/AGENTIC-SYSTEM.md](docs/architecture/AGENTIC-SYSTEM.md), [DURABLE-WORKFLOWS.md](docs/architecture/DURABLE-WORKFLOWS.md), [STORAGE.md](docs/architecture/STORAGE.md).

---

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# optional: pip install -e ".[db]"   # Postgres (psycopg)
# optional: pip install -e ".[s3]"   # S3/MinIO object storage
pytest
```

Optional Postgres pilot stack: `docker compose -f docker-compose.postgres.yml up`.

### Production email adapters

The library ships standard-library SMTP and Postmark adapters. Fixture email remains the default; selecting a production backend never falls back to fixtures when configuration is invalid.

```bash
export IMPACT_RELAY_EMAIL_BACKEND=smtp
export IMPACT_RELAY_SMTP_HOST=smtp.example.org
export IMPACT_RELAY_SMTP_PORT=587
export IMPACT_RELAY_SMTP_FROM=impact@example.org
export IMPACT_RELAY_SMTP_USERNAME=mailer
export IMPACT_RELAY_SMTP_PASSWORD='from-your-secret-manager'
export IMPACT_RELAY_SMTP_TLS=starttls  # starttls | ssl | none
```

Postmark uses its transactional `/email` API without adding a runtime SDK dependency:

```bash
export IMPACT_RELAY_EMAIL_BACKEND=postmark
export IMPACT_RELAY_POSTMARK_SERVER_TOKEN='from-your-secret-manager'
export IMPACT_RELAY_POSTMARK_FROM=impact@example.org
export IMPACT_RELAY_POSTMARK_REPLY_TO=reply@example.org       # optional
export IMPACT_RELAY_POSTMARK_MESSAGE_STREAM=outbound          # optional
```

Recipient lookup is deliberately host-owned because donor contact data must stay outside this repository. Bind the adapter to a tenant workspace with a resolver after the host has authenticated and loaded its private contact record:

```python
from impact_relay.domain.types import NotificationChannel
from impact_relay.notifications import open_email_adapter
from impact_relay.workflows.durable import open_workspace

email = open_email_adapter(
    address_resolver=lambda intent: private_contacts.email_for(intent.donor_id)
)
durable = open_workspace(".impact-relay/hacker-dojo")
workspace = durable.binding.workspace(durable.tenant_id)
assert workspace is not None
workspace.configure_notification_adapters({NotificationChannel.EMAIL: email})
```

Production delivery requires an existing consent record and enabled preference. Bind the adapter during every worker-process startup; transport objects and recipient resolvers are intentionally not persisted. Only fixture adapters bootstrap synthetic consent for offline demos. Both production adapters send the already-approved `EmailPreview` subject and body and sanitize provider failures before durable recording. SMTP records its generated Message-ID; Postmark records the API `MessageID` and treats nonzero `ErrorCode` responses as permanent rejections.

## Pilot commands

Use-of-funds pilot:

```bash
python -m impact_relay
python -m impact_relay --fixture fixtures/pilot_hd_ir_001.json
```

All fixture-backed phases:

```bash
python -m impact_relay --all-phases
python -m impact_relay --all-phases --fixture fixtures/pilot_all_phases.json
```

Durable (default SQLite data dir):

```bash
python -m impact_relay --durable help
python -m impact_relay --durable seed --data-dir .impact-relay/hacker-dojo
python -m impact_relay --durable worker --once --data-dir .impact-relay/hacker-dojo
```

Local operator-session demo:

```bash
python -m impact_relay --workflow-ops seed \
  --workflow-session .impact-relay-workflow-session.json \
  --expense-batch fixtures/expense_intake_batch_v1.json
```

Operator sessions use a versioned JSON graph with a fixed class allowlist and a corruption-detection checksum. The checksum does not authenticate a session file. Legacy pickle sessions are intentionally rejected and must not be loaded or converted from untrusted sources. Production and restart-sensitive deployments should use the durable SQLite/Postgres path instead.

Library API:

```python
from impact_relay.pilot import run_pilot, run_all_phases_pilot

ledger, receipts = run_pilot()
platform, payload = run_all_phases_pilot()
```

## Public exports

```bash
# Privacy-safe public use-of-funds export
python -m impact_relay --write-public data/use-of-funds-public.json

# One-shot public Pages regeneration
python -m impact_relay --publish-pages

# Domain impact events to public digests
python -m impact_relay --all-phases --digests-from-domain \
  --merge-fixture-digests \
  --write-digests data/impact-digests-public.json

# Every.org-style aggregate summary
python -m impact_relay \
  --every-org-aggregate fixtures/every_org_aggregate_v1.json \
  --write-impact-state data/impact-state.json

# Notion public evidence
python -m impact_relay \
  --notion-public-evidence fixtures/notion_public_evidence_v1.json \
  --write-public-evidence data/public-evidence.json

# Optional operator-owned HTTPS aggregate bridges
IMPACT_RELAY_EVERY_ORG_AGGREGATE_URL=https://bridge.example/every-org \
IMPACT_RELAY_EVERY_ORG_AGGREGATE_TOKEN="$EVERY_ORG_BRIDGE_TOKEN" \
  python -m impact_relay --require-observed \
  --write-impact-state data/impact-state.json

IMPACT_RELAY_NOTION_PUBLIC_EVIDENCE_URL=https://bridge.example/notion-public \
IMPACT_RELAY_NOTION_PUBLIC_EVIDENCE_TOKEN="$NOTION_BRIDGE_TOKEN" \
  python -m impact_relay --write-public-evidence data/public-evidence.json
```

HTTP sources must be absolute HTTPS URLs returning a JSON object. Responses are capped at 1 MiB, bearer credentials stay in host configuration, transport errors are sanitized, and fetched documents pass the same mandatory aggregate-only privacy validators as local files. These are bridges for pre-aggregated documents, not direct donor, transaction, or Notion-row clients.

## Applying authorized live aggregates

Published totals remain `raisedSource: pilot_synthetic` and `PILOT` until finance provides an authorized aggregate file or HTTPS bridge response.

```bash
cp fixtures/templates/every_org_live_aggregate.template.json ~/private/every_org_live.json
# edit the private file with authorized aggregate totals only
./scripts/apply_live_every_org_aggregate.sh ~/private/every_org_live.json
```

The hard provenance gate rejects fixture or pilot sources when `--require-observed` is enabled.

---

## Roadmap

- **v0.5:** agent contracts, authority enforcement, policies, simulation, Privacy Sentinel — **done**
- **v0.6:** expense ingestion, evidence validation, human finance review, durable pilot path — **done (library)**
- **v0.7:** canonical donor use-of-funds receipts, correction workflows, donor API — **done (library)**
- **v0.8:** funded assets, program verification, impact receipts — **domain shipped; staff verification UI host-side**
- **v0.9:** controlled Hacker Dojo pilot (host screens + runbooks shipped; live cohort ops open)
- **v1.0:** production Hacker Dojo deployment
- **v1.1:** reusable multi-tenant nonprofit platform
- **v2.0:** general impact infrastructure

See [ROADMAP.md](ROADMAP.md) and [TODO.md](TODO.md).

---

## Security and contribution

Review [SECURITY.md](SECURITY.md) and [docs/ops/](docs/ops/) before changing donor, evidence, provider, or public-export boundaries. Agent, policy, attribution, evidence, receipt-schema, and notification-gate changes require independent review.

## License

Apache-2.0. See [LICENSE](LICENSE).
