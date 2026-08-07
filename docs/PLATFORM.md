# Impact Relay — platform alignment

This repo participates in the **AGI suite**. Public hosting and tenancy identifiers follow suite canon.

## Canonical references

| Concern | Value |
| --- | --- |
| Public URL (production intent) | `https://autogive.app/impact-relay/` |
| Vercel project | `impact-relay` (team `scrimshawlife-8819s-projects`) |
| GitHub Pages fallback | `https://scrimshawlife-ctrl.github.io/Impact-Relay/` |
| Tenant id alignment | Impact Relay `tenant_id` = Portfolio Signals `clients.id` |
| **Supabase platform (suite)** | `utdioxwiskzatwoejgiu` (auth/tenancy via Portfolio Signals path; IR durable API later) |

Full suite table: [Autonomous-Giving-Incorporated/docs/PLATFORM.md](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/PLATFORM.md).

## Public surface

Static tracker + `data/public-impact.json` and related public aggregates. Authority on public impact projection: `public_aggregate_only`. No donor PII.

**Live:** https://autogive.app/impact-relay/ (Vercel). Suite Phase 2 (Portfolio Signals workspace Auth) is operator-complete; Impact Relay public remains aggregate-only until an authorized live cohort promotes OBSERVED data (see [IMPACT-RELAY-LIVE-COHORT](https://github.com/scrimshawlife-ctrl/Fund-Intel/blob/main/docs/IMPACT-RELAY-LIVE-COHORT.md) in Fund-Intel docs).

## Deploy (public)

```bash
vercel link --yes --scope scrimshawlife-8819s-projects --project impact-relay
vercel deploy --prod --yes --scope scrimshawlife-8819s-projects
```

Config: `vercel.json`, `.vercelignore` (excludes Python package, venv, node_modules).
