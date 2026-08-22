# Cloudflare Workers static assets (public tracker)

The designed suite stack is **Cloudflare + Supabase**. Impact Relay’s public tracker is a static site on Cloudflare Workers: `index.html`, `app.js`, `styles.css`, `tokens.css`, brand assets, and committed `data/*.json` aggregates. There is no Next.js app and no Python runtime on the public host. Vercel already deploys that tree as static files (`vercel.json` `framework: null`, skip install/build). This repo therefore uses the smallest Cloudflare path: an **assets-only Worker** with no `main` script.

Auth and tenancy stay on platform **Supabase** (Portfolio Signals workspace). Public aggregates only. Do not put auth, donations, donor-level records, or the console API on this Worker.

## URLs

| Surface | URL | Status |
| --- | --- | --- |
| Canonical suite path | `https://autogive.app/impact-relay/` | Production intent; still on Vercel until cutover |
| Vercel project | `https://impact-relay.vercel.app` | Kept until cutover is complete |
| Cloudflare Worker | `https://impact-relay.<account-subdomain>.workers.dev/impact-relay/` | Created on first `wrangler deploy` |
| GitHub Pages fallback | `https://scrimshawlife-ctrl.github.io/Impact-Relay/` | Unchanged |

`<base href="/impact-relay/">` is load-bearing. The staging script nests the tracker under `/impact-relay/` so Workers, Vercel path rewrites, and the suite URL all resolve CSS/JS/`data/` the same way.

## What is deployed

Staged by `scripts/stage_cloudflare_assets.sh` into `.cloudflare-assets/` (gitignored):

- `/` → redirect to `/impact-relay/`
- `/impact-relay/` → public tracker
- `/impact-relay/data/*.json` → committed public aggregates
- `_headers` / `_redirects` from `cloudflare/`

Not deployed: `src/`, `tests/`, `fixtures/`, `policies/`, `schemas/`, `docs/`, the Python package, or `console_server`.

## Local preview

```bash
./scripts/stage_cloudflare_assets.sh
npx wrangler@4.123.0 dev
```

Open `/impact-relay/` on the printed localhost URL.

## CI deploy

On `main`, after the existing validate job, GitHub Actions stages assets and runs `wrangler deploy` via `cloudflare/wrangler-action`. Required repository secrets:

| Secret | Purpose |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Token with Workers Scripts Edit (and Account Settings Read) |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |

If either secret is missing, the Cloudflare deploy step is skipped so CI stays green until credentials exist. Create a token from [Cloudflare API tokens](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) and copy the account ID from the dashboard.

Vercel config (`vercel.json`, `.vercelignore`) stays until cutover. GitHub Pages remains an optional fallback: the `deploy` job probes the repo Pages site and skips cleanly when Pages is not enabled (or not set to GitHub Actions). Enable Pages with **Source = GitHub Actions** to activate that path.

## Cutover (operator)

1. Add `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` to this GitHub repo.
2. Merge to `main` and confirm the Worker serves `/impact-relay/` on `workers.dev`.
3. Attach `autogive.app/impact-relay*` as a Worker route (or a custom domain) so the suite URL hits Cloudflare. DNS for `autogive.app` is operator-owned.
4. Smoke-check aggregates, headers (`X-Frame-Options`, `X-Content-Type-Options`), and that no donor PII is present.
5. Point canonical links at Cloudflare, then retire the Vercel project `impact-relay`.
6. Remove `vercel.json` / `.vercelignore` in a follow-up PR after Vercel is disabled.

## Remaining work

Operator-owned, still on Cloudflare + Supabase — not a new hosting platform:

- Add `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`, then confirm the first Workers deploy.
- Attach `autogive.app/impact-relay*` as a Cloudflare Worker route (or custom domain). DNS for `autogive.app` stays operator-owned.
- After smoke-check, retire the Vercel project and delete `vercel.json` / `.vercelignore` in a follow-up PR.
- GitHub Pages stays an optional fallback until operators drop it (CI skips the Pages deploy until Pages Source = GitHub Actions is enabled).
- Tenant-scoped operator auth remains platform Supabase. This Worker must not grow a ledger, approval, or notification API.

Do not add another application host for this public surface.

## Evidence semantics

Staging copies committed public JSON as-is. It does not regenerate Pages exports, relabel provenance, or change `public_aggregate_only` privacy flags. Operators still commit `python -m impact_relay --publish-pages` output when aggregate content changes.
