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
  ├── Impact Relay library
  │     ├── policy: load_tenant_policy("org_hacker_dojo")
  │     ├── durable: --data-dir per env (dev/staging/prod)
  │     ├── storage: open_storage(data_dir)  # tenants, objects, outbox
  │     └── workflows: expense / correction / digest
  └── Public Pages (optional) — publish digests / UOF aggregates
```

### Easy local pilot (Impact Relay alone)

```bash
python -m impact_relay --durable seed --data-dir .impact-relay/hd-pilot
python -m impact_relay --durable list --data-dir .impact-relay/hd-pilot
python -m impact_relay --durable approve --data-dir .impact-relay/hd-pilot
```

### Register HD in durable storage (library)

```python
from pathlib import Path
from impact_relay.storage import open_storage
from impact_relay.storage.template import ensure_canonical_hacker_dojo_tenant
from impact_relay.pilot import run_pilot

store = open_storage(Path(".impact-relay/storage"))
tenant = ensure_canonical_hacker_dojo_tenant(store)
assert tenant.tenant_id == "org_hacker_dojo"

# After a pilot / durable approve: persist queryable entity snapshot
ledger, _ = run_pilot()
store.ledger.save_ledger(ledger)
expenses = store.ledger.list_expenses("org_hacker_dojo")
loaded = store.ledger.load_ledger(tenant_id="org_hacker_dojo")
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
- Object keys are always `{tenant_id}/…`.
- Public exports use Privacy Sentinel (no donor/attendee PII).

## What the Hacker-Dojo repo should test

Prefer **library integration tests** that:

1. Load `org_hacker_dojo` policy.
2. Run durable seed/approve or `run_expense_approval_slice` against HD fixtures.
3. Assert correction append-only lineage and public digest privacy.

Host-only UI tests can mock Impact Relay; money truth tests should call the real package.

## Related

- `docs/DURABLE-QUICKSTART.md` — operator durable CLI  
- `docs/architecture/STORAGE.md` — storage ports and schema  
- `docs/architecture/AGENTIC-SYSTEM.md` — modular monolith boundary  
