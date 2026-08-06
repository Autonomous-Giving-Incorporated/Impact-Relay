# Impact Relay — platform alignment

This repo participates in the **AGI suite**. Public hosting and tenancy identifiers follow suite canon.

## Canonical references

| Concern | Value |
| --- | --- |
| Public URL (production intent) | `https://autogive.app/impact-relay/` |
| Vercel project | `impact-relay` (team `scrimshawlife-8819s-projects`) |
| GitHub Pages fallback | `https://scrimshawlife-ctrl.github.io/Impact-Relay/` |
| Tenant id alignment | Impact Relay `tenant_id` = Fund Intel `clients.id` |
| **Supabase platform (suite)** | `utdioxwiskzatwoejgiu` (auth/tenancy via Fund Intel path; IR durable API later) |

Full suite table: [Autonomous-Giving-Incorporated/docs/PLATFORM.md](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/PLATFORM.md).

## Public surface

Static tracker + `data/public-impact.json` and related public aggregates. Authority on public impact projection: `public_aggregate_only`. No donor PII.

## Deploy (public)

```bash
vercel link --yes --scope scrimshawlife-8819s-projects --project impact-relay
vercel deploy --prod --yes --scope scrimshawlife-8819s-projects
```

Config: `vercel.json`, `.vercelignore` (excludes Python package, venv, node_modules).
