# Every.org aggregate reduction runbook

## Goal

Publish **live campaign raised / committed / donor-count** to Impact Relay Pages without committing personal gift data.

## Rule

Every.org (or finance exports) must be reduced to an **aggregate_summary** **outside** this repository before git sees them.

## Allowed fields only

```json
{
  "processor": "every.org",
  "exportKind": "aggregate_summary",
  "nonprofitSlug": "hacker-dojo",
  "exportedAt": "2026-08-01T15:00:00Z",
  "currency": "USD",
  "campaignStatus": "active",
  "totals": {
    "raised": 0,
    "committed": 0,
    "donorCount": 0
  },
  "note": "Operator-reduced aggregate for SupperHappyFundHouse campaign window"
}
```

## Forbidden (never commit)

- donor names, emails, phones, addresses
- itemized gifts / charges / transactions
- personal tax receipts
- CRM exports, spreadsheets with constituent rows

## Steps

1. Export or view authorized totals for the campaign period from Every.org or finance.
2. Manually (or via a private secure job) write only the aggregate JSON above.
3. Save as a **local** file (not in git until reviewed), e.g. `~/private/every_org_live.json`.
4. Dry-run:

```bash
python -m impact_relay \
  --every-org-aggregate ~/private/every_org_live.json \
  --write-impact-state data/impact-state.json \
  --write-public data/use-of-funds-public.json
```

5. Confirm `data/impact-state.json` campaign fields match the authorized totals.
6. Set campaign provenance (see HD-IR-006):

```yaml
raisedSource: processor_aggregate
raisedClaimLabel: OBSERVED
```

7. Open a PR with **only** the updated aggregate JSON under `fixtures/` if leadership approves publishing those numbers, **or** keep the live file private and update `data/impact-state.json` numbers via CI secret-free operator process.

## Relationship to Notion

Notion Public EvidencePack provides **historical** Form 990 and 2012 campaign aggregates.
It does **not** provide live 2026 campaign raised (labeled NOT_COMPUTABLE there).

| Source | Use for |
|---|---|
| Notion public evidence | Form 990 history, 2012 campaign |
| Every.org aggregate | Live campaign raised/committed/donorCount |
| Domain pilot fixtures | Synthetic demos only |

## Publish command

```bash
python -m impact_relay --publish-pages
```
