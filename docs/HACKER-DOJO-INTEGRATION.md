# Hacker Dojo integration (canonical pilot + nonprofit template)

Impact Relay is a **reusable** donor-impact / ledger-workflow library.  
**Hacker Dojo** is the **canonical test and product integration** — the path every CI fixture and the Portfolio Signals host should exercise first. Other nonprofits copy the same shape, not a fork of the money rules.

## Roles

| Repo / system | Role |
|---|---|
| **Impact Relay** (this repo) | Domain ledger, agents L0–L3, durable workflows, public aggregates, multi-tenant storage ports |
| **Portfolio Signals** (host repo) | UX, OIDC, finance console, donor screens, org-specific branding — **consumes** Impact Relay. Hacker Dojo is the reference tenant, not a separate host repo. |
| **Future nonprofit apps** | Same as Portfolio Signals host: host UX + tenant config; **reuse** Impact Relay + clone policy template |

## Canonical identifiers

| Item | Value |
|---|---|
| Tenant / organization id | `org_hacker_dojo` |
| Policy pack | `policies/tenants/hacker-dojo.v1.0.yaml` |
| Display name | Hacker Dojo |
| Fixture pilots | `fixtures/pilot_hd_ir_001.json`, expense batch, digests, Every.org aggregate |

```python
from impact_relay.storage.template import CANONICAL_PILOT_TENANT_ID, CANONICAL_POLICY_SLUG

assert CANONICAL_PILOT_TENANT_ID == "org_hacker_dojo"
assert CANONICAL_POLICY_SLUG == "hacker-dojo"
```

## Recommended host app wiring

```text
Hacker-Dojo App (template for other nonprofits)
  ├── Auth (OIDC) — maps humans → finance_approver / … roles
  ├── impact_relay.host  ← prefer this façade
  │     open_hacker_dojo_session(data_dir)
  │       seed / list_waiting / approve / list_expenses
  └── Public Pages (optional) — publish digests / UOF aggregates
```

### Preferred API (Portfolio Signals host)

```python
from impact_relay.host import open_hacker_dojo_session
from impact_relay.host.hacker_dojo import finance_approver_fixture, hacker_dojo_oidc_mapper

# Production: validate OIDC access token in the host, then:
#   mapper = MyAuth0Provider(...)  # implements OidcIdentityProvider
#   principal = mapper.map_principal(claims, tenant_id="org_hacker_dojo")

# Local pilot without live IdP:
principal = (
    finance_approver_fixture()
)  # or hacker_dojo_oidc_mapper().principal_for_token("email:…")

with open_hacker_dojo_session(
    "./data/hd-pilot",
    require_principal_for_approve=True,
) as session:
    session = session.with_principal(principal)
    session.seed()
    waiting = session.list_waiting()
    session.approve(workflow_id=waiting["cases"][0]["workflow_id"])
    for exp in session.list_expenses():
        print(exp["id"], exp["state"])
```

Default data dir: `.impact-relay/hacker-dojo`  
Identity: `impact_relay.auth` (roles, RBAC, OIDC ports) + `hacker_dojo_identity()`

### Which identity provider, exactly

Both "Supabase" and "OIDC" appear across these docs; they are different layers,
not alternatives:

| Layer | What it is | Where |
|---|---|---|
| **Supabase** | Hacker Dojo's *actual* IdP. Owns login, MFA, and the `profile.role` values (`director`, `campaign_lead`, `data_steward`, …). | Portfolio Signals host |
| **Campaign-role bridge** | Maps a Supabase `profile.role` to Impact Relay RBAC roles. | `impact_relay.auth.role_map` |
| **OIDC ports** | The generic, vendor-neutral boundary any nonprofit host implements. | `impact_relay.auth.oidc` |
| **JWKS validation** | Optional in-library token validation for hosts that don't terminate auth at a gateway. | `impact_relay.auth.jwt_oidc` (`[oidc]` extra) |

The host is responsible for authenticating the user and enforcing MFA. Impact
Relay only maps an already-authenticated identity to roles — with one exception:
if you use `JwksOidcProvider`, the library validates the token itself.

`console_server` accepts `X-Impact-*` identity headers **only** when started with
`--trusted-proxy`, and only a gateway that authenticates the user and strips
client-supplied copies of those headers may set them. Without that flag the
headers are ignored and requests are anonymous — which the default posture
rejects.

**Hacker Dojo / Portfolio Signals host path:** the browser bridge sends only
`Authorization: Bearer <Supabase JWT>` or a fixture Bearer pilot email. It does
**not** require `--trusted-proxy`. Prefer that path for local and production-like
host screens. Enable `--trusted-proxy` only when a real gateway injects identity
headers after authentication.

### Roles (platform vocabulary)

| Role | Can approve expenses | Notes |
|------|----------------------|--------|
| `finance_approver` | yes | L3 money path |
| `finance_reviewer` | no | list / read |
| `communications_approver` | no | publish/send later |
| `auditor` | no | read-only |
| `tenant_admin` | yes (all perms) | host ops |
| `donor` | no | own receipts (host filters) |

Separation of duties: same person cannot approve their own proposal (`proposer_id`).

### Easy local pilot (CLI alone)

```bash
python -m impact_relay --durable seed --data-dir .impact-relay/hacker-dojo
python -m impact_relay --durable list --data-dir .impact-relay/hacker-dojo
python -m impact_relay --durable approve --data-dir .impact-relay/hacker-dojo
```

### Other nonprofit host (same session class)

```python
from impact_relay.host import open_host_session

with open_host_session(
    "./data/other-makerspace",
    tenant_id="org_other_makerspace",
    display_name="Other Makerspace",
) as session:
    session.ensure_registered()  # clones policy shape from Hacker Dojo template
    # session.seed / approve / list_expenses — same API
```

## Onboarding another nonprofit (template pattern)

**Suite operator path (FI + IR):** Portfolio Signals commercial lifecycle, then this clone — see Portfolio Signals [`docs/SECOND-TENANT-ONBOARDING.md`](https://github.com/Autonomous-Giving-Incorporated/Portfolio-Signals/blob/main/docs/SECOND-TENANT-ONBOARDING.md) (slice D). Shared id contract: **`client_id` == `tenant_id`** (`org_*`).

1. Clone policy from Hacker Dojo (same confidence / evidence / L3 set; new ids).
2. Register tenant in storage registry.
3. Point durable data-dir (or Postgres schema) at that tenant only.
4. Keep **Hacker Dojo fixtures green** — they remain the CI oracle for money + privacy.

```python
from impact_relay.storage.template import clone_tenant_from_hacker_dojo
from impact_relay.storage import open_storage

store = open_storage(Path(".impact-relay/storage"))
policy = clone_tenant_from_hacker_dojo(
    tenant_id="org_other_makerspace",
    display_name="Other Makerspace",
)
store.tenants.upsert_from_policy(policy, template_source="org_hacker_dojo")
```

Do **not** special-case Hacker Dojo money invariants in product code. Special-casing lives only in:

- fixture paths and default `tenant_id`s in pilots/tests;
- this integration doc;
- optional display branding in the host app.

## Isolation rules (must hold for HD + others)

- No cross-tenant ledger, workflow, object, or outbox reads.
- `LedgerCommandExecutor` rejects `command.tenant_id != ledger.organization.id`.
- Object keys are always `{tenant_id}/…` (local FS or S3 prefix).
- Public exports use Privacy Sentinel (no donor/attendee PII).

## Evidence objects (local or S3)

Default (easy local): files under `{data_dir}/objects/{tenant_id}/…`.

Production / shared pilot bucket:

```bash
pip install 'impact-relay[s3]'
export IMPACT_RELAY_OBJECT_STORE=s3
export IMPACT_RELAY_S3_BUCKET=hd-impact-relay
export IMPACT_RELAY_S3_PREFIX=prod/
# AWS credentials via standard env / instance role
```

```python
from impact_relay.storage import open_storage

store = open_storage("./data/hd-pilot")  # uses S3 when env set
store.objects.put(
    "org_hacker_dojo",
    "evidence/inv-9101.pdf",
    pdf_bytes,
    content_type="application/pdf",
)
```

## What the Hacker-Dojo repo should test

Prefer **library integration tests** that:

1. Load `org_hacker_dojo` policy.
2. Run durable seed/approve or `run_expense_approval_slice` against HD fixtures.
3. Assert correction append-only lineage and public digest privacy.

Host-only UI tests can mock Impact Relay; money truth tests should call the real package.

## Console HTTP API (pilot UI backend)

```bash
# terminal 1 — from Impact-Relay checkout
# Prefer default (no --trusted-proxy) with Bearer JWT or fixture email
python -m impact_relay.console_server --data-dir .impact-relay/hacker-dojo --port 8787

# seed queue
curl -X POST http://127.0.0.1:8787/api/pilot/seed \
  -H 'Authorization: Bearer finance.approver@hackersdojo.example'
curl http://127.0.0.1:8787/api/finance/queue \
  -H 'Authorization: Bearer finance.approver@hackersdojo.example'
```

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/finance/metrics` | Queue counts |
| GET | `/api/finance/queue` | Waiting / blocked cases |
| GET | `/api/finance/cases/{id}` | Case + packet + events |
| POST | `/api/finance/cases/{id}/approve` | L3 approve |
| POST | `/api/pilot/seed` | Fixture seed |
| GET | `/api/donors/{id}/dashboard` | Donor screen |
| GET | `/api/donors/{id}/timeline` | Fund timeline |
| GET | `/api/donors/{id}/receipts` | Receipt list |
| GET | `/api/donors/{id}/receipts/{rid}` | Receipt detail |

Hacker-Dojo static pages: `finance-impact.html`, `donor-impact.html` (point `IMPACT_RELAY_API` at the server).

## Donor experience API (v0.7)

```python
from impact_relay.pilot import run_pilot
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.donor import open_donor_api

ledger, receipts = run_pilot()
api = open_donor_api(TenantWorkspace(ledger.organization, ledger=ledger))
donor_id = receipts[0].donor_id
print(api.get_receipt(donor_id, receipts[0].receipt_id))
print(api.fund_timeline(donor_id))
print(api.allocation_balances(donor_id))
api.set_notification_preference(donor_id, channel="EMAIL", enabled=True, topics=["MONEY_USED"])
```

Or via host session after durable runs: `session.donor_api()`.

## Related

- `docs/DURABLE-QUICKSTART.md` — operator durable CLI  
- `docs/architecture/STORAGE.md` — storage ports and schema  
- `docs/architecture/AGENTIC-SYSTEM.md` — modular monolith boundary  
- `docs/pilot/HACKER-DOJO-PILOT.md` — pilot process  
- `docs/ops/` — threat model, incident response, runbooks  
