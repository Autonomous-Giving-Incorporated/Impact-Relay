# AGI Suite Architecture

AGI-001 defines the documentation boundary for **Autonomously Giving Incorporated (A.G.I.)**: a governed donor-impact suite that pairs a public-facing Fund-Intel experience with the Impact Relay financial transparency backend. A.G.I. is a product suite name, not a claim that agents own financial authority.

## Components

- **Fund-Intel frontend**: a static-first donor and operator experience intended for GitHub Pages hosting with Supabase authentication, profiles, and tenant metadata. It presents campaign, donor, and review workflows without becoming the ledger of record.
- **Impact Relay backend**: the deterministic donation, allocation, expense, attribution, receipt, workflow, and audit library. For hosted deployments, Cloud Run is the recommended backend target because it provides a small container surface, managed HTTPS, service-account isolation, and straightforward scaling for console APIs and durable workers.
- **Supabase**: planned identity and tenancy boundary for Fund-Intel. Supabase JWT validation is planned at the Impact Relay gateway before accepting privileged console calls. Until that validation is active, production hosts must validate JWTs before forwarding trusted principals.

## Shared tenant contract

Fund-Intel and Impact Relay share one tenancy key:

```text
client_id == tenant_id
```

The frontend sends `client_id`; the backend treats it as `tenant_id` for policy lookup, storage partitioning, evidence keys, run receipts, and audit queries. Cross-tenant reads or writes remain prohibited.

## Reference tenant

`hacker-dojo` is the reference tenant and canonical pilot template. It anchors example policies, fixture data, role mapping, public aggregate exports, and host-screen integration. Other nonprofit deployments should clone the tenant shape rather than fork the financial rules.

## Administrative boundaries

- **Master admin**: platform-level operator for onboarding tenants, configuring deployment infrastructure, managing Supabase project settings, and assigning tenant directors. A master admin does not approve expenses, change allocation splits, publish receipts, or override tenant financial controls.
- **Director**: tenant-level accountable human for nonprofit operations. A director may assign tenant roles and route work to finance, program, communications, and audit users, subject to separation-of-duties rules and explicit approval gates.
- **Agents**: remain bounded to observe or propose unless an independently approved reversible execution path exists. Agents never grant themselves authority and never replace human approval for consequential actions.

## Deployment posture

The preferred AGI-001 deployment shape is:

```text
GitHub Pages Fund-Intel UI
        │ Supabase session + client_id
        ▼
Cloud Run Impact Relay gateway/API
        │ validated tenant_id, RBAC, SoD
        ▼
Impact Relay deterministic services, workflow store, object storage, audit receipts
```

Planned Supabase JWT validation must verify issuer, audience, expiry, signature, role claims, and the `client_id == tenant_id` binding before privileged requests reach finance, donor, publication, or notification APIs.
