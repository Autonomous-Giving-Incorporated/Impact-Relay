# HD-IR-004 — Domain digests + Every.org aggregate adapter

## Objective

1. Export **verified domain impact events** into the public digests feed.
2. Normalize **Every.org-style aggregate summaries** into the reconcile pipeline.
3. One-shot **`--publish-pages`** path for CI and operators.

## Domain digests

```text
run_all_phases_pilot
  → TenantWorkspace.impact_events (VERIFIED only)
  → digests_from_workspace
  → data/impact-digests-public.json
```

Optional merge with `fixtures/impact_events_pilot.json` for community events that are not yet modeled as domain ImpactEvents.

Reviewer emails and donor identities are never included.

## Every.org aggregate adapter

```text
fixtures/every_org_aggregate_v1.json   # aggregate_summary only
  → every_org_to_reconcile_aggregate
  → apply_aggregate_reconciliation
  → data/impact-state.json
```

Forbidden in Every.org summary inputs: gifts, transactions, donors, emails, receipts (personal), line items.

Live processor pulls remain outside this repository. Operators reduce exports to aggregates first.

## Commands

```bash
# Full Pages publish (CI default)
python -m impact_relay --publish-pages

# Domain digests only
python -m impact_relay --all-phases --digests-from-domain --digests-only

# Every.org aggregate → impact-state
python -m impact_relay \
  --every-org-aggregate fixtures/every_org_aggregate_v1.json \
  --write-impact-state data/impact-state.json
```

## Evidence boundary

- Fixtures are synthetic.
- Domain IMPACT receipts still contain donor ids internally; only public digests/UOF/aggregate state are Pages artifacts.
- Personal gift detail from Every.org must never be committed.
