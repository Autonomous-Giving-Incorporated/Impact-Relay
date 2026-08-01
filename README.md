# Impact Relay

Donation fund-use transparency and impact notification platform.

This repository has two related surfaces:

1. **Public tracker (GitHub Pages)** — aggregate campaign progress only (no donor PII).
2. **HD-IR-001 domain core** — use-of-funds ledger pilot (donation → allocation → approved expense → receipt).

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

## HD-IR-001 use-of-funds ledger pilot

**Status:** domain core for finance-grade use-of-funds receipts (preview/publish artifact only — not live push/email/SMS).

### What it ships

A pure-Python domain ledger that implements:

```text
donation import → allocation assignment → expense import/classification
  → finance approval / reconciliation → use-of-funds receipt
```

Hard invariants:

- Donation allocations never exceed the cleared donation amount
- Approved expense allocations sum to the expense amount
- Restricted allocation remaining balance cannot go negative on approval
- Verified use-of-funds receipts only from `APPROVED` or `RECONCILED` expenses
- Attribution method required (no phantom one-to-one linkage)
- Corrections are append-only (`reverse_expense` / `supersede_expense`); prior receipts are never rewritten

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

### Pilot entry path

```bash
python -m impact_relay
# or
impact-relay-pilot
# or with explicit fixture
python -m impact_relay --fixture fixtures/pilot_hd_ir_001.json
```

Output is JSON on stdout with `receipts[]` containing allocation name, expenditure figures, verification state, remaining designated balance, attribution method, and receipt id/hash.

Library API:

```python
from impact_relay.pilot import run_pilot

ledger, receipts = run_pilot()
print(receipts[0].to_dict())
```

### Package layout (domain)

```text
src/impact_relay/
  domain/types.py    # entities, states, receipt model
  domain/ledger.py   # invariants, approval, attribution, receipts, corrections
  pilot.py           # fixture loader + pilot runner
  cli.py             # documented CLI entry
fixtures/pilot_hd_ir_001.json
tests/
docs/pilot-systems-of-record.md
```

Fixture systems of record: [docs/pilot-systems-of-record.md](docs/pilot-systems-of-record.md).

### Non-goals (HD-IR-001)

- Live push / email / SMS delivery
- Full donor portal or Hacker Dojo native app
- Multi-tenant SaaS onboarding
- Impact-event / class digest layer

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

## HD-IR-003 digests + aggregate reconciliation

**Status:** public event digests and aggregate-only donation reconciliation pipeline.

### Event digests

```bash
python -m impact_relay --write-digests data/impact-digests-public.json
python -m impact_relay --digests-only
```

Digests publish class/workshop/open-lab outcomes with **attendance counts only**.

### Aggregate reconciliation

```bash
python -m impact_relay \
  --reconcile-from fixtures/reconcile_aggregate_v1.json \
  --write-impact-state data/impact-state.json
```

Updates public raised/committed/donor-count fields, milestone reach state, and a reconcile notification. Rejects any payload containing donor lists or itemized gifts.

See [docs/HD-IR-003.md](docs/HD-IR-003.md).

---

## License

Apache-2.0. See [LICENSE](LICENSE).
