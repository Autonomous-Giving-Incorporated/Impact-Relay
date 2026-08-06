# Every.org aggregate reduction runbook

## Goal

Publish **live campaign raised / committed / donor-count** to Impact Relay Pages with honest provenance:

| Claim | `raisedSource` | When |
|---|---|---|
| **OBSERVED** | `processor_aggregate` | Authorized operator aggregate from Every.org (or finance), **not** a repo fixture |
| **PILOT** | `pilot_synthetic` | Demo / fixture numbers only |
| **NOT_COMPUTABLE** | `not_available` | Explicitly no live total |

The UI shows an empty/pilot banner for `pilot_synthetic` and `not_available`. It treats totals as live only for `processor_aggregate`.

## Rule

Every.org (or finance exports) must be reduced to an **aggregate_summary** **outside** this repository before git sees them.

## Allowed fields only

Copy `fixtures/templates/every_org_live_aggregate.template.json` and fill:

```json
{
  "processor": "every.org",
  "exportKind": "aggregate_summary",
  "nonprofitSlug": "hacker-dojo",
  "exportedAt": "2026-08-01T18:00:00Z",
  "currency": "USD",
  "campaignStatus": "active",
  "claimLevel": "OBSERVED",
  "source": "every.org/aggregate:hacker-dojo",
  "totals": {
    "raised": 0,
    "committed": 0,
    "donorCount": 0
  },
  "note": "Operator-reduced aggregate for SupperHappyFundHouse campaign window"
}
```

**Provenance gate:** `source` must **not** contain `fixture`, `pilot`, `synthetic`, `demo`, or `template`. `claimLevel: OBSERVED` is rejected for those sources.

## Forbidden (never commit)

- donor names, emails, phones, addresses
- itemized gifts / charges / transactions
- personal tax receipts
- CRM exports, spreadsheets with constituent rows

## Steps (live OBSERVED)

1. Export or view authorized totals for the campaign period from Every.org or finance.
2. Manually write only the aggregate JSON above (private path, e.g. `~/private/every_org_live.json`).
3. **Dry-run validate** (no write; refuses fixture/template paths):

```bash
python -m impact_relay --validate-every-org-aggregate ~/private/every_org_live.json
# or
./scripts/apply_live_every_org_aggregate.sh --dry-run ~/private/every_org_live.json
```

4. Apply with hard gate:

```bash
chmod +x scripts/apply_live_every_org_aggregate.sh
./scripts/apply_live_every_org_aggregate.sh ~/private/every_org_live.json
```

Equivalent:

```bash
python -m impact_relay \
  --every-org-aggregate ~/private/every_org_live.json \
  --require-observed \
  --write-impact-state data/impact-state.json
```

Or:

```bash
export IMPACT_RELAY_EVERY_ORG_AGGREGATE=~/private/every_org_live.json
python -m impact_relay --every-org-aggregate "$IMPACT_RELAY_EVERY_ORG_AGGREGATE" \
  --require-observed --write-impact-state data/impact-state.json
```

Or fetch a pre-aggregated document from an operator-owned HTTPS bridge:

```bash
export IMPACT_RELAY_EVERY_ORG_AGGREGATE_URL=https://bridge.example/every-org
export IMPACT_RELAY_EVERY_ORG_AGGREGATE_TOKEN="$(secret-tool lookup service impact-relay-every-org)"
python -m impact_relay --require-observed \
  --write-impact-state data/impact-state.json
```

The bridge must return the same aggregate-only JSON shape documented above. The client requires HTTPS and JSON, caps the body at 1 MiB, sanitizes transport errors, and runs the local Every.org privacy and provenance validators before any write. Do not expose a donor-detail or transaction endpoint through this bridge. Keep the bearer token in the host secret manager and prefer an egress/domain allowlist.

4. Confirm `data/impact-state.json`:

```yaml
raisedSource: processor_aggregate
raisedClaimLabel: OBSERVED
raisedPublic: <authorized>
lastReconciledAt: <export time>
```

5. Open a PR that updates **only** aggregate public fields in `data/impact-state.json` (and optional notification text). Do **not** commit private gift exports.

6. Optional full Pages refresh after live raise is set:

```bash
IMPACT_RELAY_EVERY_ORG_AGGREGATE=~/private/every_org_live.json \
  python -m impact_relay --publish-pages --require-observed
```

(`--publish-pages` uses the env aggregate when set; otherwise falls back to the pilot fixture, which will **fail** `--require-observed`.)

## Why Pages still shows PILOT today

No authorized private Every.org aggregate has been applied in this environment:

- Public Every.org pages are bot-protected (no scrape path).
- Repo fixture `fixtures/every_org_aggregate_v1.json` is labeled `fixture://…` and **must** stay `PILOT`.
- Inventing OBSERVED totals would violate HD-IR provenance rules.

Until an operator runs the script above with real numbers, the public site correctly shows pilot/demo provenance.

## Relationship to Notion

Notion Public EvidencePack provides **historical** Form 990 and older campaign aggregates.
It does **not** provide live 2026 campaign raised (NOT_COMPUTABLE there).

| Source | Use for |
|---|---|
| Notion public evidence | Form 990 history, 2012 campaign |
| Every.org aggregate (authorized) | Live campaign raised/committed/donorCount |
| Domain pilot fixtures | Synthetic demos only |

## Publish command (demo / pilot)

```bash
python -m impact_relay --publish-pages
```

This uses the pilot Every.org fixture unless `IMPACT_RELAY_EVERY_ORG_AGGREGATE` points at a live file.
