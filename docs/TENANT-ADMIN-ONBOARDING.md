# Tenant admin API: security containment and provisioning blockers

The console is tenant-scoped, not a platform provisioning service. These routes
must not be used as evidence that cross-system onboarding is complete.

## Current contract

All three admin routes require an authenticated human principal with the existing
`tenant.admin` permission for `ServerConfig.tenant_id`. Finance approval is not
administration. Anonymous pilot mode does not bypass this gate. The implicit
public email-as-token fixture mapper is disabled for admin routes. Configure a
validating identity provider, or a trusted proxy that authenticates users and
strips client-supplied identity headers; CORS is not authentication.

- `GET /api/admin/tenants`: returns only the configured tenant's registry record,
  with `scope: "configured_tenant"`. It is not a platform-wide registry listing.
- `GET /api/admin/tenants/verify?tenant_id=org_...`: validates the literal ID and
  rejects other tenants. Reports registration, not readiness. `ready` is false,
  `storage_isolated` is null, and `cross_tenant_access` is `"not_tested"`.
  A multi-tenant registry is neither proof of leakage nor proof of isolation.
- `POST /api/admin/tenants/clone`: after authentication/authorization, returns
  HTTP 503 with `tenant_provisioning_unavailable`. No body fields can activate
  writes. This deliberately replaces the unsafe success response until the
  authority and provisioning contracts below exist.

Registry reads use the same configured database precedence as `open_storage`:
`IMPACT_RELAY_DATABASE_URL`, then `DATABASE_URL`, otherwise
`ServerConfig.data_dir / "storage.db"`. They use `SqlTenantRepository.get`, with
read-only connections, without schema migrations or object-store initialization.
No sibling-directory scan, tenant-derived path, or special `storage` basename
routing remains. A missing local registry yields no record without creating it;
a configured database failure is a sanitized HTTP 500, not healthy/isolated.
Filesystem and database configuration remain trusted operator inputs. They must
not be writable by tenants; this does not establish OS-level sandboxing.

## Why cloning is blocked

The existing `clone_tenant_from_hacker_dojo(*, tenant_id, display_name,
version=None)` returns a `TenantPolicy`. It does not accept an arbitrary template
source, persist a policy pack, create signed membership, or create a usable
workflow workspace. `register_cloned_tenant` returns `(policy, record)` and
upserts a registry row; it is not an atomic provisioning transaction. The old
HTTP path accepted arbitrary template-source metadata despite always cloning
Hacker Dojo, could overwrite registrations, and claimed success too early.

Required architecture work before re-enabling platform provisioning:

1. Define a separately reviewed platform authority, tenant membership semantics,
   and step-up/MFA requirements. `Principal` currently binds roles to one tenant;
   never promote `finance_approver`, a campaign role, or `tenant_admin` into
   cross-tenant authority merely because the UI calls it Platform Admin.
2. Define canonical workspace routing independent of tenant-supplied paths,
   including shared Postgres tenant enforcement and object-store isolation.
3. Persist/load versioned policy packs and initialize a tenant-correct durable
   workspace, with create-only/idempotent semantics, audit receipts, concurrency
   controls, and rollback/recovery. Do not overwrite an existing tenant.
4. Verify signed membership and client activation in the host, required-document
   readiness, policy loading, workspace binding, and adversarial cross-tenant
   reads/writes. Registry presence alone is not this verification.
5. Update host UI to handle the explicit unavailable/not-tested states rather
   than interpreting `ok: true` on a registry lookup as production readiness.

## Durable storage foundation (not provisioning authority)

`SqlLedgerCommandLog.append` binds `(tenant_id, idempotency_key)` to the first
committed command type and serialized request payload. Reusing a key with a
different request raises the existing `LedgerLogError` with a sanitized
`ledger command idempotency conflict` message; it does not replace the row.
Identical retries may carry new result IDs/timestamps, but the first result and
creation timestamp remain authoritative. Reopen/replay folds only that result,
never re-dispatches the request.

The SQL unique constraint arbitrates concurrent inserts before the winner is
read in the same transaction. Independent engines do not rely on a shared
Python lock. PostgreSQL's normal READ COMMITTED isolation lets the subsequent
read see the committed winner; deployments selecting stronger isolation must
retry whole transactions on serialization failures, not suppress those errors.
SQLite's write transaction serializes competing inserts. SQLite now ignores
only the tenant/key uniqueness conflict, not unrelated constraint violations.
Serialization remains `json.dumps(..., sort_keys=True, default=str)`; tuple/list
and Decimal/string representations that serialize identically are retries.
Postgres compares the serialized payload in JSONB space (including its numeric
equality semantics) so exponent normalization cannot reject an identical request.
SQLite compares canonicalized JSON text. Both distinguish booleans from numbers.

This is an append-boundary guard, **not** a distributed command executor or an
atomic ledger/provisioning transaction. It cannot undo an already-executed
in-memory mutation or external side effect. The file-backed command log is
unchanged. Any future provisioner must check/reserve request identity before
side effects and durably coordinate its result, registry, policy, workspace,
and audit/outbox state under a separately reviewed contract.

### Policy serialization and reopen requirements

Current behavior is deliberately characterized in
`tests/test_clone_policy_provenance.py`:

- `dataclasses.replace` in `clone_tenant_from_hacker_dojo` retains the template's
  `source_path`. `TenantPolicy.to_dict()` also retains it; changing the tenant ID
  does not clear or rewrite that field. It means **template provenance**, not
  a newly persisted tenant policy location.
- `parse_tenant_policy(document)` ignores a `source_path` inside the document;
  it takes provenance only from the explicit caller argument. `load_tenant_policy`
  supplies the actual resolved local path. A JSON serialization round trip is
  therefore not a durable policy-loading contract.
- `SqlTenantRepository.upsert_from_policy` stores registry identity/version and
  metadata, not the effective policy body. Neither a registry row nor a template
  path proves that the clone can reopen without the original template files.

Before implementing durable creation, specify and test:

1. A versioned, validated effective-policy document, with exact tenant/version
   binding, every effective rule explicit, and deterministic serialization/hash.
   Separate template identity/version/content hash from the new durable document
   locator. Exclude machine-local paths from portable identity; do not trust a
   client-supplied path as a locator or authorization. Preserve template lineage
   rather than mislabeling it as a clone-owned file.
2. Strict reopen validation for schema version, tenant, policy version, hash,
   types and completeness. The current permissive parser applies defaults and
   truthiness conversions; it is not sufficient validation for an untrusted
   durable document. Missing/corrupt/unsupported policy must fail closed, not
   fall back through `default_policy` or regenerate from a changed template.
3. Create-only publication and conflict detection for request identity, tenant
   identity and policy version. Coordinate durable policy bytes and registry/
   workspace/audit state, with crash recovery and no partial-success claim. A
   retry returns the original committed outcome, not a fresh policy or overwrite.
4. A fresh-process reopen test without the source template file: verify the
   effective rules, provenance, tenant-bound empty ledger/workflow/object roots,
   approvals and isolation. Do not seed a new tenant from Hacker Dojo donations,
   receipts or fixture consent. Fixture consent settings need explicit review;
   template copying is not consent or membership authorization.

The additive local storage foundation now implements policy serialization,
create-only scaffolds and reopen/replay; see [DURABLE-ONBOARDING-CORE.md](DURABLE-ONBOARDING-CORE.md)
and [PORTABLE-PROVISIONING-V1.md](PORTABLE-PROVISIONING-V1.md) for its exact boundaries.
The orchestration, authorization and activation requirements above remain separate
integration gates. The clone route remains HTTP 503; no new platform authority or
new-tenant runtime exists.

## Local verification

`tests/test_tenant_admin_api.py` exercises real HTTP handler dispatch and real
SQLite repositories in temporary directories, with database/object-store
environment isolation. It covers permission/default-deny gates, public fixture
credentials, provider principal tenancy and agent rejection, traversal, scoped
registry reads, missing/corrupt/symlinked databases, read-only connections, and
no-write clone containment. Existing JWT and Supabase tests remain separate.

`tests/test_sql_command_log.py` runs real SQLite identity/retry/replay and
independent-engine concurrency tests. With `IMPACT_RELAY_DATABASE_URL` pointing
to a **disposable test database** and the `[db]` extra installed, it runs the
same tests on Postgres plus `SqlEngine(read_only=True)` SELECT, rejected
INSERT/UPDATE/DELETE/DDL, rollback and fresh-connection checks. It creates and
drops only its own random schemas. Missing URL/driver produces explicit skips;
connection/setup failures are failures, not skips. The `postgres-store` CI job
runs the suite and rejects skips. No default test run requires a service.

```bash
.venv/bin/pytest
# Operator must supply a disposable local/test database, never production:
IMPACT_RELAY_DATABASE_URL="$TEST_POSTGRES_URL" .venv/bin/pytest \
  tests/test_workflow_sql_store.py tests/test_sql_command_log.py -v -rs
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

Read-only transaction enforcement is defense in depth for trusted repository
queries, not sandboxing of arbitrary SQL or proof of RLS/cross-tenant isolation.
No live host, production database, Supabase tenant, or deployment is validated
by these tests.
