# HD-IR-001 — Deterministic donation-to-receipt pilot

The first milestone. Later milestone notes (HD-IR-002 onward) build on it, and
`fixtures/pilot_hd_ir_001.json` is its canonical input.

## Objective

Prove that a donation can be traced to an approved expense and back to a
donor-readable use-of-funds receipt, deterministically, with no model in the
money path.

## Scope

In scope:

- normalized fixture donations, allocations, expenses, and evidence;
- the money invariants in `impact_relay.domain.ledger`;
- direct restricted attribution;
- `UseOfFundsReceipt` generation with a stable content hash;
- an append-only audit trail.

Out of scope (deliberately): live payment processors, live accounting systems,
agents, durable workflows, notifications, and any public export. Those arrive in
HD-IR-002 and later.

## Run it

```bash
python -m impact_relay
```

The default fixture is `fixtures/pilot_hd_ir_001.json`. Use `--fixture` for a
different input and `--all-phases` for the full phase 2–6 pilot.

## Invariants established here

These hold for every later milestone and are regression-gated by
`tests/test_ledger_invariants.py`:

- donation allocations never exceed the cleared donation amount;
- a restricted allocation balance never goes negative;
- an approved expense's allocations sum exactly to the expense amount;
- attribution requires a valid method and an evidenced, verified expense —
  never a phantom one-to-one link;
- approved expenses and published receipts are never silently mutated;
  corrections go through `reverse_expense` / `supersede_expense` and produce new
  receipts that preserve lineage.

## Provenance rule

Fixture data is synthetic and must always be labelled as such. Nothing derived
from this milestone may be published as an `OBSERVED` figure — see
[pilot-systems-of-record.md](pilot-systems-of-record.md).

## Next

[HD-IR-002](HD-IR-002.md) — privacy-safe public use-of-funds export.
