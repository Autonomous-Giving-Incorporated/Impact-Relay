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

## Local verification

`tests/test_tenant_admin_api.py` exercises real HTTP handler dispatch and real
SQLite repositories in temporary directories, with database/object-store
environment isolation. It covers permission/default-deny gates, public fixture
credentials, provider principal tenancy and agent rejection, traversal, scoped
registry reads, missing/corrupt/symlinked databases, read-only connections, and
no-write clone containment. Existing JWT and Supabase tests remain separate.

Run syntax, Ruff lint/format, mypy, and pytest before review. No live host,
production database, Supabase tenant, or deployment is validated by these tests.
The new Postgres read-only transaction path still needs a disposable Postgres
integration run; local SQLite tests do not establish Postgres/RLS isolation.
