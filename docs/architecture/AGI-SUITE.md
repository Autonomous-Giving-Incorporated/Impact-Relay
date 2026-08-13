# AGI Suite Architecture

AGI-001 defines the documentation boundary for **Autonomously Giving Incorporated (A.G.I.)**: a governed donor-impact suite that pairs Portfolio Signals (decision workspace) with Impact Relay (financial transparency and impact evidence). A.G.I. is a product suite name, not a claim that agents own financial authority.

Zero State is credited only as the software builder.

## Components

| Component | Role | Hosting (canonical) |
|-----------|------|---------------------|
| **AGI public site** | Brand, narrative, suite entry | `https://autogive.app/` (Vercel) |
| **Portfolio Signals** | Decision workspace, tenant admin shell, authenticated operator UI | `https://autogive.app/portfolio-signals/` · platform Supabase Auth/RLS |
| **Impact Relay (public)** | Aggregate-only use-of-funds / impact tracker | `https://autogive.app/impact-relay/` (Vercel until Cloudflare Workers cutover; see [CLOUDFLARE.md](../CLOUDFLARE.md)) |
| **Impact Relay (backend)** | Deterministic ledger, receipts, workflows, audit | Library + Cloud Run (recommended for APIs/workers) |
| **Supabase (platform)** | Identity, multi-tenant Postgres, RLS, Storage | Project ref `utdioxwiskzatwoejgiu` |

Portfolio Signals presents campaign, donor, and review workflows without becoming the ledger of record. Impact Relay is the financial truth surface after human approval.

## Shared tenant contract

Portfolio Signals and Impact Relay share one tenancy key:

```text
client_id == tenant_id
```

The frontend sends `client_id`; the backend treats it as `tenant_id` for policy lookup, storage partitioning, evidence keys, run receipts, and audit queries. Cross-tenant reads or writes remain prohibited.

## Reference tenant (not product identity)

`hacker-dojo` / `org_hacker_dojo` is the **reference tenant** and canonical pilot template. It anchors example policies, fixture data, role mapping, public aggregate exports, and host-screen integration.

- Product chrome and suite tokens are **AGI / Portfolio Signals / Impact Relay**.
- Hacker Dojo brand (mark, red palette) is **tenant assets** — in Portfolio Signals: `assets/tenants/hacker-dojo/`.
- Other nonprofit deployments clone the tenant shape rather than forking financial rules or rebranding the product as Hacker Dojo.

## Administrative boundaries

- **Master admin**: platform-level operator for onboarding tenants, configuring deployment infrastructure, managing Supabase project settings, and assigning tenant directors. A master admin does not approve expenses, change allocation splits, publish receipts, or override tenant financial controls.
- **Director**: tenant-level accountable human for nonprofit operations. A director may assign tenant roles and route work to finance, program, communications, and audit users, subject to separation-of-duties rules and explicit approval gates.
- **Agents**: remain bounded to observe or propose unless an independently approved reversible execution path exists. Agents never grant themselves authority and never replace human approval for consequential actions.

## Deployment posture

Preferred AGI public + operator shape:

```text
autogive.app/                 AGI brand site
autogive.app/portfolio-signals/     Portfolio Signals UI + workspace
autogive.app/impact-relay/    public aggregate tracker
        │
        │  Supabase session + client_id (platform project)
        ▼
Cloud Run Impact Relay gateway/API  (when live APIs are enabled)
        │  validated tenant_id, RBAC, SoD
        ▼
Impact Relay deterministic services, workflow store, object storage, audit receipts
```

GitHub Pages remains optional fallback only.

Planned Supabase JWT validation must verify issuer, audience, expiry, signature, role claims, and the `client_id == tenant_id` binding before privileged requests reach finance, donor, publication, or notification APIs. Until that validation is active, production hosts must validate JWTs before forwarding trusted principals.

## Phase status (2026-08-07)

| Phase | Status |
| --- | --- |
| Public path suite on autogive.app | Live |
| Portfolio Signals workspace + platform Supabase | Operator-complete |
| Allocation middleware production host | Pending (local pilot green) |
| IR live OBSERVED cohort | Operator-owned |

## Related

- Suite phase map: [AGI docs/PLATFORM.md](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/PLATFORM.md)
- Portfolio Signals live receipt: Fund-Intel `docs/CURRENT-STATE.md`
- Portfolio Signals platform canon: Fund-Intel `docs/PLATFORM.md`
- Portfolio Signals suite architecture: Fund-Intel `docs/AGI-SUITE-ARCHITECTURE.md`
- Design system: [AGI-DESIGN-SYSTEM.md](../AGI-DESIGN-SYSTEM.md)
