# Durable onboarding core: phased plan and integration contract

## Scope and ordering

1. **Policy serialization**: add a versioned canonical JSON codec for the complete
   `TenantPolicy` value. The existing parser treats empty lists as defaults and
   ignores embedded `source_path`; it is not a lossless persistence decoder.
   Keep its behavior unchanged. Preserve source_path as provenance, never as a
   claimed persisted clone location. Store sorted compact JSON, reject nonfinite
   numbers and malformed shapes, and verify round trips including empty lists.
2. **Empty scaffold persistence**: add an immutable SQL repository using existing
   SqlEngine transactions on SQLite/Postgres. Persist literal tenant identity,
   organization name, complete policy, provenance, and idempotency key in one row.
   Exact retries return the existing value; divergent retries conflict. Never
   copy fixture ledger entities, overwrite registry rows, seed or activate.
3. **Reopen/replay**: reconstruct Organization and an empty Ledger, fold only that
   tenant's SQL command results, and bind a TenantWorkspace to that same ledger.
   Prove fresh-process reopening without policy files or fixtures. Unknown tenants
   must fail, not synthesize a workspace. This is a storage core, not a worker.
4. **Authority boundary**: no console clone enablement, new role, HTTP route, or
   FI executor. FI request metadata remains runtime_ready=false. Calling these
   internal APIs requires a separately authorized orchestration service; database
   access is not proof of human authority, membership, MFA, or policy approval.
5. **Hosted verification**: run offline regressions, Ruff/mypy, and disposable
   Postgres tests. Later, separately authorized work must connect signed FI
   request identity/audit to IR, test worker policy injection/command persistence,
   prove cross-tenant signed-token denial and host activation, and verify required
   documents. No remote migration/deployment is authorized in this change.

## Exact additive API contract (target implementation)

Module `impact_relay.storage.workspace`:

- `canonical_policy_json(policy: TenantPolicy) -> str`
- `policy_from_canonical_json(document: str) -> TenantPolicy`
- `SqlWorkspaceRepository(engine: SqlEngine)` (does not initialize storage).
- `create(*, policy: TenantPolicy, idempotency_key: str) -> WorkspaceScaffold`:
  atomic create-only identity; same tenant/key/canonical policy is an exact retry;
  any changed key or content raises `WorkspaceConflict`. No active tenant registry
  row is created. `source_path` is retained as supplied provenance only, not
  authenticated provenance. Trusted orchestration must validate policy selection.
- `get(tenant_id: str) -> WorkspaceScaffold | None`: read-only exact lookup.
- `reopen(tenant_id: str) -> ReopenedWorkspace`: missing tenant raises KeyError;
  returns scaffold, policy, and TenantWorkspace with SQL result-folded ledger.
- `WorkspaceScaffold`: tenant_id, idempotency_key, policy_json; `runtime_ready`
  is always false. `ReopenedWorkspace`: scaffold, policy, workspace.

`StorageBundle.workspaces` exposes the repository. Tenant IDs must match
`[A-Za-z0-9][A-Za-z0-9_-]{0,127}` literally; no slug/alias normalization occurs.
The `workspace_scaffolds` table stores tenant_id (primary key), idempotency_key,
and canonical policy_json as TEXT on both engines. TEXT intentionally preserves
canonical bytes instead of JSONB rewriting their representation. No timestamps or
approval/audit claims are fabricated. `INSERT ... ON CONFLICT DO NOTHING RETURNING`
arbitrates concurrent scaffold creators; changed requests roll back without edits.
A newly inserted scaffold is rolled back if tenants, ledger_command_log,
ledger_entity, ledger_meta, or outbox_events already contains that tenant. Exact
retries are permitted after ledger use. Legacy writers do not share this reservation
protocol: orchestration must exclude concurrent legacy writes and cannot use this
as a migration/adoption tool. Separate workflow databases/object stores cannot be
checked by this repository; their emptiness is an orchestration precondition.

Reopen folds SQL results with the existing deterministic projection function,
rejecting explicit foreign organization_id values before binding. This is not a
full relational integrity audit of all historical entity references. Notification,
consent, and impact service state starts empty and is not reconstructed here.

Schema creation remains the
existing explicit SqlEngine.migrate/StorageBundle initialization boundary; get
and reopen do not migrate, create directories, or access object storage. Callers
can use a read-only SqlEngine for inspection/reopen. The database locator must be
trusted configuration, never derived from tenant IDs. No policy update API exists.

## Residual integration gates

Legacy workflows/durable.py still opens a fixture-backed FileLedgerCommandLog;
this new core must not be selected by relabeling meta.json. Runtime policy lookup,
workflow/executor factory wiring, transactional execution recovery, durable consent
and notification state, registry reconciliation, FI request execution and audit,
platform authority validation, organization-proof documents, and hosted signed-token
acceptance remain separate gates. Scaffold persistence and ledger replay are not
production readiness or authorization to import parked CRM exports.

## Local execution evidence

Review preparation verification (local library/contract only):

- Canonical repository `.venv/bin/pytest`, without database URL overrides:
  **532 passed, 40 skipped**. Unconfigured Postgres skips are covered separately,
  not counted as hosted acceptance evidence.
- Dedicated workflow-store, SQL command-log, workspace, portable, initialized
  workspace and clone-provenance suites: **122 passed, no skips** against a
  disposable loopback-only `postgres:16-alpine` container. Container deletion
  verified after the run.
- `.venv/bin/mypy`: clean (80 source files); canonical Ruff lint and format checks
  clean. Public assets and the HTTP 503 clone boundary are unchanged.
- Both standalone Node conformance scripts pass. The initialized schema tests pass
  in a fresh environment installed with exactly `.[dev]` plus `jsonschema`; both
  initialized fixtures also pass independent Ajv draft2020 validation with the
  scaffold schema registered offline.
- CI explicitly gates initialized schema/Python/Node/Ajv conformance in
  `portable-conformance`, and runs the dedicated database suites in `postgres-store`
  with skip rejection. Neither job activates or deploys a Python runtime.
- Fresh subprocess tests use an unrelated working directory, no policy file,
  explicit database locator and read-only SqlEngine. They recover persisted
  policy/provenance and only the requested tenant's result-folded donor state.
- No remote database writes, deployment, fixture ledger copying, destructive seed,
  console activation, new role or operational-readiness claim is part of this work.
