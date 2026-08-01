# HD-IR-003 — Impact digests + aggregate reconciliation

## Objective

1. Publish **program/event digests** with public attendance counts only.
2. Apply **aggregate-only** donation processor summaries into the public tracker.
3. Keep all personal identifiers out of GitHub Pages artifacts.

## Pipelines

### Event digests

```text
fixtures/impact_events_pilot.json
  → digest.build_public_digests
  → data/impact-digests-public.json
  → Pages “Event digests” section
```

Forbidden in digest inputs: attendee names, emails, phones, rosters.

### Aggregate reconciliation

```text
fixtures/reconcile_aggregate_v1.json   # raised/committed/donorCount only
  → reconcile.apply_aggregate_reconciliation
  → data/impact-state.json
  → campaign metrics + notification + milestone state
```

Forbidden in reconcile inputs: donors, gifts, transactions, emails, names.

## Commands

```bash
python -m impact_relay \
  --reconcile-from fixtures/reconcile_aggregate_v1.json \
  --write-impact-state data/impact-state.json \
  --write-public data/use-of-funds-public.json \
  --write-digests data/impact-digests-public.json
```

## Evidence boundary

- Pilot fixtures are synthetic.
- Live Every.org exports must be reduced to aggregates **outside** this repository before use.
- Production import of personal donation detail remains blocked.
