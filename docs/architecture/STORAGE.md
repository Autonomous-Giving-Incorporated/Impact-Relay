# Storage and service boundaries

| Field | Value |
|---|---|
| **Status** | Implemented (v1 — ports + SQLite default; Postgres DSN; S3 object backend) |
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
  objects.py         # LocalObjectStorage + S3ObjectStorage + open_object_storage()
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
| Evidence objects | Local dir `{data_dir}/objects/{tenant_id}/…` | **S3 / MinIO** via `IMPACT_RELAY_OBJECT_STORE=s3` (same port) |
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
| `IMPACT_RELAY_OBJECT_STORE` | `local` (default) or `s3` |
| `IMPACT_RELAY_S3_BUCKET` | Bucket name (required for s3) |
| `IMPACT_RELAY_S3_PREFIX` | Optional key prefix (e.g. `impact-relay/`) |
| `IMPACT_RELAY_S3_ENDPOINT_URL` | MinIO / R2 custom endpoint |
| `IMPACT_RELAY_S3_REGION` / `AWS_REGION` | Region |
| `IMPACT_RELAY_S3_SSE` | `AES256` (default), `aws:kms`, or `none` |

```bash
pip install 'impact-relay[s3]'
export IMPACT_RELAY_OBJECT_STORE=s3
export IMPACT_RELAY_S3_BUCKET=impact-relay-evidence
# optional MinIO:
# export IMPACT_RELAY_S3_ENDPOINT_URL=http://127.0.0.1:9000
```

Keys are always tenant-scoped: `{prefix}{tenant_id}/{key}` (e.g. `org_hacker_dojo/evidence/inv-1.pdf`).

## Non-goals (this slice)

- Alembic multi-file history (single `migrate()` bootstrap is enough for pilot)
- Live IdP JWT validation (host implements `OidcIdentityProvider`; see `impact_relay.auth`)
- Client-side encryption beyond S3 SSE
