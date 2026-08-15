# Impact Relay — platform alignment

This repo participates in the **AGI suite**. Public hosting and tenancy identifiers follow suite canon.

## Canonical references

| Concern | Value |
| --- | --- |
| Public URL (production intent) | `https://autogive.app/impact-relay/` |
| Vercel project (until cutover) | `impact-relay` (team `scrimshawlife-8819s-projects`) · `https://impact-relay.vercel.app` |
| Cloudflare Worker | `impact-relay` (assets-only; see [CLOUDFLARE.md](CLOUDFLARE.md)) |
| GitHub Pages fallback | `https://scrimshawlife-ctrl.github.io/Impact-Relay/` |
| Tenant id alignment | Impact Relay `tenant_id` = Portfolio Signals `clients.id` |
| **Supabase platform (suite)** | `utdioxwiskzatwoejgiu` (auth/tenancy via Portfolio Signals path; IR durable API later) |

Full suite table: [Autonomous-Giving-Incorporated/docs/PLATFORM.md](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/PLATFORM.md).

## Public surface

Static tracker + `data/public-impact.json` and related public aggregates. Authority on public impact projection: `public_aggregate_only`. No donor PII.

**Live:** https://autogive.app/impact-relay/ (Vercel until Cloudflare cutover). Direct Vercel URL: https://impact-relay.vercel.app. Suite Phase 2 (Portfolio Signals workspace Auth) is operator-complete; Impact Relay public remains aggregate-only until an authorized live cohort promotes OBSERVED data (see [IMPACT-RELAY-LIVE-COHORT](https://github.com/scrimshawlife-ctrl/Fund-Intel/blob/main/docs/IMPACT-RELAY-LIVE-COHORT.md) in Fund-Intel docs).

## Deploy (public)

Designed stack: **Cloudflare + Supabase**. The public tracker is static HTML/CSS/JS plus committed `data/` JSON on Cloudflare Workers; operator auth/tenancy remain platform Supabase. Vercel remains until cutover. Details: [CLOUDFLARE.md](CLOUDFLARE.md).

```bash
./scripts/stage_cloudflare_assets.sh
npx wrangler@4.123.0 deploy
```

GitHub Actions on `main` runs the same path with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.

Vercel remains available until operators attach `autogive.app/impact-relay/` to the Worker and retire the Vercel project:

```bash
vercel link --yes --scope scrimshawlife-8819s-projects --project impact-relay
vercel deploy --prod --yes --scope scrimshawlife-8819s-projects
```

Config kept until cutover: `vercel.json`, `.vercelignore` (excludes Python package, venv, node_modules).
