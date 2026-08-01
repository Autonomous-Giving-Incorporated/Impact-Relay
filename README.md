# Impact Relay

**Donation fund-use transparency and impact notification infrastructure.**

Impact Relay connects a donation to its approved allocation, connects that allocation to actual expenditures, and connects those expenditures to verified programs and outcomes. Donors receive clear, consent-aware receipts explaining both **what their money was used for** and **what that use subsequently enabled**.

> AI proposes. Deterministic services validate. Authorized humans approve. The ledger records. Receipts preserve lineage.

[Live public tracker](https://scrimshawlife-ctrl.github.io/Impact-Relay/) · [Vision](VISION.md) · [Agent contract](AGENTS.md) · [Architecture](docs/architecture/AGENTIC-SYSTEM.md) · [Roadmap](ROADMAP.md) · [Execution backlog](TODO.md)

---

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

**Version:** `0.4.0`

**Current state:** fixture-backed product capabilities with privacy-safe public projections. Live accounting ingestion, production notification delivery, authenticated finance workflows, and native Hacker Dojo application screens remain pending.

### Shipped capabilities

| Capability | Module / surface |
|---|---|
| Donation, allocation, expense, and attribution ledger | `src/impact_relay/domain/ledger.py` |
| Append-only correction and receipt lineage | `src/impact_relay/domain/ledger.py` |
| Donor balances, fund timeline, and receipt detail | `src/impact_relay/domain/donor_views.py` |
| Consent, policy deduplication, and fixture delivery adapters | `src/impact_relay/domain/notifications.py` |
| Programs, impact events, and impact receipts | `src/impact_relay/domain/impact.py` |
| Multi-organization domain isolation | `src/impact_relay/domain/tenant.py` |
| Pilot runners and fixture loaders | `src/impact_relay/pilot.py` |
| Aggregate public tracker and privacy-safe exports | GitHub Pages + `data/` |
| Every.org aggregate and Notion public-evidence bridges | CLI adapters and runbooks |

### Deferred production capabilities

- live accounting provider adapter;
- production Every.org donation ingestion;
- durable workflow runtime;
- authenticated finance review and approval console;
- email, push, and SMS provider delivery;
- Hacker Dojo donor timeline and receipt screens;
- human finance cohort validation;
- reusable nonprofit onboarding.

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
Agent workflow layer
        │ proposals, evidence checks, review packets
        ▼
Human approval gates
        │ approved commands
        ▼
Deterministic domain services
        │ ledger events and canonical receipts
        ▼
Donor projections and notification adapters
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

The next engineering campaign implements one complete vertical slice:

```text
fixture or accounting expense
→ allocation proposal
→ evidence validation
→ finance approval
→ ledger commit
→ donor attribution
→ use-of-funds receipt
→ email preview
→ independent send approval
→ fixture delivery receipt
```

No autonomous impact inference, SMS delivery, generalized onboarding, or multiple accounting providers should be introduced until this slice passes adversarial and finance-review testing.

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

Canonical aggregate state is stored in `data/impact-state.json` and validated against `schemas/impact-state.schema.json` in CI.

---

## Repository map

```text
Impact-Relay/
├── README.md
├── VISION.md
├── AGENTS.md
├── ENGINEERING_PRINCIPLES.md
├── ROADMAP.md
├── TODO.md
├── SECURITY.md
├── docs/
│   ├── architecture/
│   │   └── AGENTIC-SYSTEM.md
│   ├── HD-IR-003.md
│   ├── HD-IR-004.md
│   ├── HD-IR-005-notion-public-evidence.md
│   ├── HD-IR-006.md
│   ├── EVERYORG-AGGREGATE-RUNBOOK.md
│   └── pilot-systems-of-record.md
├── src/impact_relay/
│   ├── domain/
│   ├── public_export.py
│   ├── pilot.py
│   └── cli.py
├── fixtures/
├── schemas/
├── data/
├── tests/
├── index.html
├── app.js
├── styles.css
└── .github/workflows/
```

The target agentic repository shape is specified in [docs/architecture/AGENTIC-SYSTEM.md](docs/architecture/AGENTIC-SYSTEM.md).

---

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

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
```

## Applying authorized live aggregates

Published totals remain `raisedSource: pilot_synthetic` and `PILOT` until finance provides an authorized aggregate file.

```bash
cp fixtures/templates/every_org_live_aggregate.template.json ~/private/every_org_live.json
# edit the private file with authorized aggregate totals only
./scripts/apply_live_every_org_aggregate.sh ~/private/every_org_live.json
```

The hard provenance gate rejects fixture or pilot sources when `--require-observed` is enabled.

---

## Roadmap

- **v0.5:** agent contracts, authority enforcement, policies, simulation, Privacy Sentinel.
- **v0.6:** expense ingestion, evidence validation, and human finance review.
- **v0.7:** canonical donor use-of-funds receipts and correction history.
- **v0.8:** funded assets, program verification, and impact receipts.
- **v0.9:** controlled Hacker Dojo pilot.
- **v1.0:** production Hacker Dojo deployment.
- **v1.1:** reusable multi-tenant nonprofit platform.
- **v2.0:** general impact infrastructure.

See [ROADMAP.md](ROADMAP.md) and [TODO.md](TODO.md).

---

## Security and contribution

Review [SECURITY.md](SECURITY.md) before changing donor, evidence, provider, or public-export boundaries. Agent, policy, attribution, evidence, receipt-schema, and notification-gate changes require independent review.

## License

Apache-2.0. See [LICENSE](LICENSE).