# Impact Relay

Donation fund-use transparency and impact notification platform.

This repository has related surfaces:

1. **Public tracker (GitHub Pages)** — aggregate campaign progress, use-of-funds receipts, and event digests (no donor PII).
2. **Domain core (Python)** — HD-IR-001 ledger + Phases 2–6 fixture-backed product capabilities (donor reads, notifications, impact, multi-tenant pilot).
3. **HD-IR-003 Pages bridge** — aggregate reconciliation into `impact-state.json` + public digests export.
4. **HD-IR-004** — domain ImpactService digests + Every.org aggregate adapter + `--publish-pages`.
5. **HD-IR-005** — Notion Public EvidencePack aggregates (Form 990 + 2012 campaign) on Pages.
6. **HD-IR-006** — public IMPACT outcomes (no donor ids) + raised provenance + Every.org runbook.

Live public site:

https://scrimshawlife-ctrl.github.io/Impact-Relay/

---

## Public tracker

Publishes **aggregate campaign progress only**. It does not store donor names, emails, individual gift amounts, private notes, or contact lists.

### What it does

- shows public raised / committed / donor-count aggregates
- tracks funding milestones and impact statements
- publishes a notification feed for campaign events
- links to the donation processor (Every.org) without handling card data
- validates the public data contract in CI before deploy

### Repository map (public)

```text
index.html                         Public tracker UI
styles.css                         Visual system
app.js                             Client renderer
data/impact-state.json             Canonical public aggregate state
schemas/impact-state.schema.json   JSON Schema contract
SECURITY.md                        Data boundary
.github/workflows/                 Validate + GitHub Pages deploy
```

### Local preview

```bash
python3 -m http.server 8080
```

Open `http://localhost:8080`.

### Validate public state

```bash
npx --yes \
  --package ajv-cli@5 \
  --package ajv-formats@3 \
  ajv validate \
  --spec=draft2020 \
  -c ajv-formats \
  -s schemas/impact-state.schema.json \
  -d data/impact-state.json
```

### Updating totals

1. Reconcile an authorized donation export outside this repo.
2. Update only aggregate fields in `data/impact-state.json`.
3. Never commit donor names, emails, or itemized gifts.
4. Open a PR; CI must pass schema validation before Pages deploy.

### Privacy rules

| Allowed | Prohibited |
|---|---|
| Aggregate raised amount | Donor names |
| Aggregate committed amount | Emails / phones / addresses |
| Public donor count | Individual gift amounts |
| Milestone copy | Private notes / CRM fields |
| Processor deep-link | Service credentials |

---

## Domain core (HD-IR-001 + Phases 2–6)

**Status:** fixture-backed product capabilities. Live provider delivery, native HD app, and human finance cohort sign-off remain deferred.

### Capability map

| Phase | Capability | Module / entry |
|-------|------------|----------------|
| 1 / HD-IR-001 | Use-of-funds ledger, attribution, append-only corrections | `domain/ledger.py` |
| 2 | Donor balances, fund timeline, receipt detail (read-only) | `domain/donor_views.py` |
| 3 | Consent, preferences, policy dedup, in-process delivery adapters | `domain/notifications.py` |
| 4 | Programs, funded assets, impact verify/publish IMPACT receipts | `domain/impact.py` |
| 5–6 | Multi-org isolation + multi-stage HD fixture pilot | `domain/tenant.py`, `pilot.run_all_phases_pilot` |

### Money invariants (regression bar)

- Donation allocations never exceed the cleared donation amount
- Approved expense allocations sum to the expense amount
- Restricted allocation remaining balance cannot go negative on approval
- Verified use-of-funds receipts only from `APPROVED` or `RECONCILED` expenses
- Attribution method required; donor attributions cannot exceed donation allocation
- Single live UOF receipt per donation+expense+allocation
- Corrections are append-only; prior receipts are never rewritten

### Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

### Pilot entry paths

**HD-IR-001 (use-of-funds only):**

```bash
python -m impact_relay
python -m impact_relay --fixture fixtures/pilot_hd_ir_001.json
```

**All phases (UOF → impact → notify → donor read, multi-tenant):**

```bash
python -m impact_relay --all-phases
python -m impact_relay --all-phases --fixture fixtures/pilot_all_phases.json
```

`--all-phases` prints JSON including `primary.use_of_funds_receipts`, `primary.impact_receipts`, `primary.notification_intents`, `primary.notification_deliveries`, and `primary.donor_dashboard_alice`.

Library API:

```python
from impact_relay.pilot import run_pilot, run_all_phases_pilot

ledger, receipts = run_pilot()
platform, payload = run_all_phases_pilot()
```

### Package layout (domain)

```text
src/impact_relay/
  domain/types.py           # entities, states, receipts, notify models
  domain/ledger.py          # money ledger + UOF + corrections
  domain/donor_views.py     # Phase 2 read projections
  domain/notifications.py   # Phase 3 policy + in-process adapters
  domain/impact.py          # Phase 4 impact layer
  domain/tenant.py          # multi-tenant Platform / TenantWorkspace
  pilot.py                  # fixture loaders + multi-stage runner
  cli.py                    # documented CLI entry
fixtures/pilot_hd_ir_001.json
fixtures/pilot_all_phases.json
tests/
docs/pilot-systems-of-record.md
```

### Fixture vs live

| Fixture-backed (shipped) | Live-integration deferred |
|--------------------------|---------------------------|
| Normalized donation/expense import | Payment processor / accounting product adapters |
| In-process push/email/SMS adapters | APNs / FCM / Twilio / SendGrid production |
| Multi-org isolation in domain | SaaS billing, white-label onboarding |
| Hacker Dojo fixture pilot path | Native app screens, TestFlight finance sign-off |

See [docs/pilot-systems-of-record.md](docs/pilot-systems-of-record.md).

---

## HD-IR-002 public use-of-funds export

**Status:** privacy-safe Pages export from the pilot ledger.

### What it ships

```text
pilot ledger receipts
  → public_export.receipt_to_public (strip donor/operator identity)
  → data/use-of-funds-public.json
  → GitHub Pages “Use of funds” section
```

Commands:

```bash
# Write Pages-safe export from the pilot fixture
python -m impact_relay --write-public data/use-of-funds-public.json

# Print only the public payload
python -m impact_relay --public-only
```

Public export never includes:

- donor ids or display names
- donation references
- operator emails / approved_by actors

CI runs the domain suite, regenerates the public export, and fails if the committed file drifts.

---

## HD-IR-003 / HD-IR-004 Pages pipelines

```bash
# One-shot Pages publish (CI default)
python -m impact_relay --publish-pages

# Domain verified impact events → digests (+ optional fixture merge)
python -m impact_relay --all-phases --digests-from-domain --merge-fixture-digests \
  --write-digests data/impact-digests-public.json

# Every.org-style aggregate summary → impact-state
python -m impact_relay \
  --every-org-aggregate fixtures/every_org_aggregate_v1.json \
  --write-impact-state data/impact-state.json
```

See [docs/HD-IR-003.md](docs/HD-IR-003.md), [docs/HD-IR-004.md](docs/HD-IR-004.md), and
[docs/HD-IR-005-notion-public-evidence.md](docs/HD-IR-005-notion-public-evidence.md).

### Notion public evidence

```bash
python -m impact_relay \
  --notion-public-evidence fixtures/notion_public_evidence_v1.json \
  --write-public-evidence data/public-evidence.json
```

### Public IMPACT outcomes + Every.org runbook

```bash
python -m impact_relay --publish-pages
# writes data/public-impact.json (event-level outcomes, no donor ids)
```

Operator guide for live aggregates: [docs/EVERYORG-AGGREGATE-RUNBOOK.md](docs/EVERYORG-AGGREGATE-RUNBOOK.md) · [docs/HD-IR-006.md](docs/HD-IR-006.md)

### Live raised (OBSERVED) — operator required

Published Pages numbers stay **`raisedSource: pilot_synthetic` / `PILOT`** until finance supplies an authorized aggregate file. Fixtures cannot be labeled OBSERVED.

```bash
# 1. Copy template, fill authorized totals only (no donor lists)
cp fixtures/templates/every_org_live_aggregate.template.json ~/private/every_org_live.json
# edit ~/private/every_org_live.json

# 2. Apply with hard provenance gate
./scripts/apply_live_every_org_aggregate.sh ~/private/every_org_live.json
# sets raisedSource=processor_aggregate, raisedClaimLabel=OBSERVED

# 3. PR data/impact-state.json after review
```

`python -m impact_relay --every-org-aggregate … --require-observed` fails on `fixture://` / pilot sources.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
