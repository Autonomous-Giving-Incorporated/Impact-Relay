# Storage and service boundaries

| Field | Value |
|---|---|
| **Status** | Implemented (v1 — ports + SQLite default; Postgres-ready DSN) |
| **Related** | `DURABLE-WORKFLOWS.md` K11/K17, `docs/HACKER-DOJO-INTEGRATION.md`, `TODO.md` P1 Storage |

## Goals

1. **Multi-tenant isolation** — every durable row is scoped by `tenant_id` (`organization_id`).
2. **Reusable platform** — Impact Relay is not Hacker-Dojo-only; other nonprofits onboard by cloning the **canonical template**.
3. **Canonical pilot** — Hacker Dojo (`org_hacker_dojo`, policy `hacker-dojo.v1.0`) is the **reference integration** for tests, fixtures, and the Hacker-Dojo application repo.
4. **Easy local use** — SQLite under a data directory; optional `IMPACT_RELAY_DATABASE_URL` for Postgres (same pattern as workflows).

## Package layout

```text
src/impact_relay/storage/
  ports.py           # Protocol interfaces
  sql.py             # connection + migrate (SQLite / Postgres)
  tenants.py         # tenant registry repository
  command_log.py     # SQL ledger_command_log (K17 fold rows)
  objects.py         # evidence / receipt object storage (local FS default)
  outbox.py          # structured event outbox (skeleton)
  template.py        # clone tenant policy from Hacker Dojo template
```

Workflow tables remain in `workflows/store_sql.py` (already multi-tenant). Domain money mutations still go only through `LedgerCommandExecutor`.

## Tenancy model

| Concept | ID example | Notes |
|---|---|---|
| **Canonical pilot tenant** | `org_hacker_dojo` | Fixture + CI default; Hacker-Dojo app integration |
| **Template policy** | `policies/tenants/hacker-dojo.v1.0.yaml` | Clone source for other nonprofits |
| **Other nonprofit** | `org_*` | Isolated registry row + own policy pack + own data paths |

Cross-tenant access is a hard error at repository and object-storage boundaries.

## Persistence tiers (this PR)

| Store | Default | Optional |
|---|---|---|
| Tenant registry | SQLite `tenants` table | Postgres DSN |
| Ledger command log | SQLite `ledger_command_log` **or** existing file `ledger_commands.jsonl` | Postgres |
| Ledger entities | SQLite `ledger_entity` + `ledger_meta` (donors/expenses/receipts maps) | Postgres |
| Workflow store | `workflows.db` / Postgres (P2 already) | — |
| Evidence objects | Local dir `{data_dir}/objects/{tenant_id}/…` | S3-compatible later (same `ObjectStorage` port) |
| Outbox | SQLite `outbox_events` | Postgres |

**Money durability:** command log (K17 fold) remains the authoritative append-only path for mutations. **Entity repo** is a queryable snapshot for host apps (list expenses/receipts) after pilot/runtime save.

## Hacker Dojo as template

```python
from impact_relay.storage.template import (
    CANONICAL_PILOT_TENANT_ID,
    clone_tenant_from_hacker_dojo,
)

# New makerspace reuses HD policy shape, different tenant_id
policy = clone_tenant_from_hacker_dojo(
    tenant_id="org_other_makerspace",
    display_name="Other Makerspace",
)
```

The Hacker-Dojo application repo should depend on Impact Relay as a library and use `org_hacker_dojo` for all pilot/CI paths. See `docs/HACKER-DOJO-INTEGRATION.md`.

## Feature flags / env

| Env | Purpose |
|---|---|
| `IMPACT_RELAY_DATABASE_URL` / `DATABASE_URL` | Postgres for storage + workflows |
| `IMPACT_RELAY_DATA_DIR` | Default local root (`.impact-relay`) |

## Non-goals (this slice)

- Alembic multi-file history (single `migrate()` bootstrap is enough for pilot)
- S3 encryption (interface only; local FS is the pilot backend)
- Live IdP JWT validation (host implements `OidcIdentityProvider`; see `impact_relay.auth`)
