# Hacker Dojo integration (canonical pilot + nonprofit template)

Impact Relay is a **reusable** donor-impact / ledger-workflow library.  
**Hacker Dojo** is the **canonical test and product integration** — the path every CI fixture and the Hacker-Dojo application repo should exercise first. Other nonprofits copy the same shape, not a fork of the money rules.

## Roles

| Repo / system | Role |
|---|---|
| **Impact Relay** (this repo) | Domain ledger, agents L0–L3, durable workflows, public aggregates, multi-tenant storage ports |
| **Hacker-Dojo app** (sibling / host repo) | UX, OIDC, finance console, donor screens, org-specific branding — **consumes** Impact Relay |
| **Future nonprofit apps** | Same as Hacker-Dojo app: host UX + tenant config; **reuse** Impact Relay + clone policy template |

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

### Preferred API (Hacker-Dojo app)

```python
from impact_relay.host import open_hacker_dojo_session
from impact_relay.host.hacker_dojo import finance_approver_fixture, hacker_dojo_oidc_mapper

# Production: validate OIDC access token in the host, then:
#   mapper = MyAuth0Provider(...)  # implements OidcIdentityProvider
#   principal = mapper.map_principal(claims, tenant_id="org_hacker_dojo")

# Local pilot without live IdP:
principal = finance_approver_fixture()  # or hacker_dojo_oidc_mapper().principal_for_token("email:…")

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

