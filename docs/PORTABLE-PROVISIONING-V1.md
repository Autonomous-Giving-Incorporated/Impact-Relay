# Portable empty-tenant provisioning contract v1

**Status: local contract/conformance implementation; not a deployed executor.**
Existing Cloudflare + Supabase is the target. Python remains a local oracle/library;
this contract adds no host, route, public tracker API, console clone action, tenant
activation, worker, provider connection, money, donor data, or notification delivery.
Schema and financial gating changes require independent human review before release.

## Plan and ownership

1. Preserve the existing SQL command-log/workspace implementation and its stored bytes.
2. Specify a separate portable policy/scaffold format and deterministic public synthetic
   vectors; verify Python, JSON Schema and JavaScript byte/hash agreement locally.
3. The host executor independently integrates its immutable authorized request with
   this format, commits to the **existing Supabase**, reads back and verifies, then
   records a scaffold-only receipt. Live authorization/transactions/RLS/deployment
   are host acceptance criteria, not claims made by these fixtures.

## Artifacts and exact fields

Normative structural schemas (JSON Schema 2020-12):

- `schemas/ir-empty-scaffold-v1.schema.json`
- `schemas/ir-scaffold-verification-v1.schema.json`
- `schemas/ir-initialized-empty-workspace-v1.schema.json`
- `schemas/ir-initialized-workspace-verification-v1.schema.json`

The initialized schemas reference `urn:impact-relay:ir-empty-scaffold-v1`; register
`ir-empty-scaffold-v1.schema.json` by its `$id` in an offline schema registry (Ajv:
`-r schemas/ir-empty-scaffold-v1.schema.json`). They reuse the policy, identifier
and hash constraints without copying or relaxing the predecessor contract.

Every declared object is closed (`additionalProperties: false`); every field is
required. No implicit defaults, coercion, dropped nulls, or sorted/deduplicated arrays.
Unknown formats fail closed; this is **not** a permissive YAML policy document.

Scaffold fields:

| Field | Meaning / invariant |
| --- | --- |
| `format` | Exactly `ir-empty-scaffold-v1` |
| `tenant_id` | Literal `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`; equals nested policy tenant |
| `idempotency_key` | Literal `[A-Za-z0-9][A-Za-z0-9._:-]{0,255}`; bind to the host's immutable provisioning request |
| `policy` | Object with exactly `format: ir-portable-policy-v1` and `policy` body below |
| `policy_sha256` | Lowercase 64-hex SHA-256 of canonical UTF-8 bytes of the entire `policy` envelope |
| `empty_state` | Exactly `{ledger_commands: [], entities: [], outbox_events: []}`; declarative empty initial state, **not proof** external tables are empty |
| `readiness` | Exactly `{scaffold_verified: false, operational: false}` in the immutable input |

Policy body fields (same names as `TenantPolicy.to_dict()`, except numeric encoding):

- `version`: literal `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; never repair malformed identifiers.
- `tenant_id`, `display_name` (Unicode string), `source_path` (Unicode string or null).
- `confidence`: `block_below`, `recommend_high` are **decimal strings**, not JSON numbers.
  Grammar: `0`, `1`, or `0.` followed by one through six digits, last digit nonzero.
  No exponent, sign, trailing zero, whitespace, `1.0`, NaN, Infinity, or negative zero.
  Enforce `block_below <= recommend_high` using exact decimal arithmetic (JS may
  convert to integer millionths for comparison). Reject unsupported precision;
  never round. For example `"0.75"`, `"0.95"`, `"0.000001"`.
- `evidence`: `sufficient_kinds` string array; `require_donor_visible` exactly true.
- `attribution`: `default_method` string; `allowed_methods` string array.
- `notifications`: `require_separate_send_approval` exactly true;
  `default_email_topics` string array; `fixture_consent_allowed` boolean.
- `authority`: `l3_command_types` string array containing at least all of:
  `approve_expense`, `reject_expense`, `publish_use_of_funds_receipt`,
  `send_notification`, `publish_public_evidence`, `change_attribution_policy`,
  `correct_published_amount`, `reverse_expense`, `supersede_expense`.

Empty arrays stay empty, not parser defaults. Extra L3 gates remain intact. The
schema is a transport/scaffold contract, not certification that arbitrary method
names or topic strings are operationally supported. Hosts must use an independently
reviewed, immutable template allowlist, not caller-authored financial policy. Policy
compatibility and human policy approval remain separate gates. Fixture consent
configuration never grants actual donor consent or send authority.

### Provenance

`source_path` is preserved **literally**, hashed, and treated only as provenance
metadata. Never open it, resolve it, download it, or require it at reopen. It is not
proof of origin or authorization. Do not replace it with the clone's persistence
path. Host audit records must bind the authorized request, requester, template
version/digest and resulting hashes; those host identity fields intentionally do
not appear in this portable artifact. Never place secrets or private local paths
in public vectors. `fixtures/portable_provisioning_v1/manifest.json` declares
`public_synthetic`; no fixture is an OBSERVED claim or a provisioned production tenant.

## Canonical bytes and hashes (normative)

This is **number-free canonical JSON**, not JCS and not Python `ir-policy-v1`:

1. Accept only JSON objects, arrays, Unicode scalar strings, booleans and null.
   No JSON numbers anywhere. Reject lone UTF-16 surrogates and non-ASCII object keys.
2. Sort object keys lexicographically by ASCII code. Preserve array order and
   duplicate entries. Emit compact JSON with `,` and `:` and no whitespace/BOM/newline.
3. Quote strings using `\"`, `\\`, `\b`, `\t`, `\n`, `\f`, `\r`; other U+0000–001F
   use lowercase `\u00xx`. Do not escape `/` or non-ASCII scalar characters.
   In particular emit U+2028/U+2029 literally. No Unicode normalization.
4. Encode as UTF-8. Hash raw bytes with SHA-256, lowercase hex, no `sha256:` prefix.
   `policy_sha256` covers only the policy envelope, including format and source_path.
   `scaffold_sha256` in the receipt covers the **complete immutable scaffold**, including
   policy hash and its false/false input readiness. Never include a hash of itself.
5. On wire ingestion, parse then compare canonical reserialization with the exact
   original decoded UTF-8 string. This rejects duplicate keys, whitespace, alternate
   escapes, malformed numeric tokens and noncanonical member order. A plain JSONB
   parse cannot establish original-wire canonicality: verify first, then persist
   the canonical text alongside any JSONB projection. Do not hash `jsonb::text`.

Semantic checks beyond JSON Schema: exact hash recomputation, tenant equality,
threshold ordering, scalar Unicode, canonical bytes/duplicate-key rejection, and
host authorization/idempotency/storage emptiness. JSON Schema validation alone is
insufficient. Python `storage/portable.py` supplies a strict round-trip decoder;
`check_portable_conformance.mjs` is a byte/hash oracle, **not** a full host validator.

## Durable storage and host executor acceptance

`storage/workspace.py` continues storing `ir-policy-v1` using Python ASCII escaping
and numeric formatting. JavaScript `JSON.stringify` is NOT byte-compatible with it
(e.g. `1.0` versus `1`, astral Unicode, exponent formatting). This change leaves
existing rows and serializer untouched. `build_scaffold` / `decode_scaffold` bridge
the new format to `TenantPolicy`; unsupported portable precision/identifiers fail.
Never relabel the new policy as `ir-policy-v1` or insert portable policy text into
Python's `workspace_scaffolds.policy_json` without the explicit decode adapter.

Host executor requirements, to be implemented/tested independently:

- Consume only the stored immutable request, freshly authorize its privileged action
  (including the host's AAL2/platform-admin rules), and validate a pinned template.
  An artifact/hash alone grants no authority. Do not trust browser readiness flags.
- Atomically bind the request to one literal tenant and exact canonical artifact.
  Retries with the identical request/artifact succeed idempotently. Any change in
  tenant, key, policy, provenance or hash conflicts; never overwrite/adopt a legacy
  tenant silently. Serialize concurrent attempts; rollback partial writes.
- On first creation, prove absence of pre-existing tenant registry, commands,
  entities, metadata, outbox and workflow state in the corresponding host tables.
  The Python repository currently checks `tenants`, `ledger_command_log`,
  `ledger_entity`, `ledger_meta`, `outbox_events`; no broader host-table coverage is
  claimed. An empty scaffold writes no financial commands/entities/outbox events.
- Persist in existing Supabase with privileged server-only writes and appropriate
  tenant isolation. Exact table/RPC names belong to the host, not this contract.
- Read back the exact persisted target, validate and compare its canonical bytes,
  confirm required empty-state checks, then record `ir-scaffold-verification-v1`:
  `tenant_id`, `idempotency_key`, `policy_sha256`, `scaffold_sha256`, and
  `readiness: {scaffold_verified: true, operational: false}`. Never mutate input
  readiness. `verify_readback` is a pure byte verifier; passing the same in-memory
  string twice is not evidence of persistence or database isolation.
- A scaffold receipt does **not** establish request authorization, a running Python
  backend, command-log replay support on Cloudflare, workers, live providers, delivery,
  public publication or an operational tenant. Those require separate evidence and
  a future activation contract. No `operational: true` is valid in v1.

## Initialized-empty workspace: actual repository evidence

The additive API in `src/impact_relay/storage/portable.py` is:

```python
state, receipt = verify_initialized_workspace(database, expected_scaffold_canonical_text)
decode_initialized_workspace(canonical_json(state))
validate_initialized_receipt(canonical_json(receipt), state)
```

`database` is an explicit existing SQLite path/SQLite URL or Postgres DSN. The verifier
opens it **read-only**, never migrates or creates it, calls the actual
`SqlWorkspaceRepository.reopen`, compares the reopened policy/request with the strict
expected portable scaffold, and checks tenant-scoped absence in `tenants`,
`ledger_command_log`, `ledger_entity`, `ledger_meta`, `outbox_events`. All reads share
one SQLite snapshot / Postgres REPEATABLE READ transaction. Foreign-tenant rows are
not adopted. Any missing scaffold, invalid policy, request/hash drift, nonempty
checked table or foreign binding fails without a success receipt. No readiness
booleans, reopened objects, or caller-supplied check results are accepted as input.

This is storage initialization for the **SQL scaffold reopen model**, not an
assertion that a Cloudflare executor, Supabase runtime binding row, tenant registry,
workflow runtime, or worker was initialized. The host must verify its own persisted
binding/request/RLS and cannot relabel this receipt as host runtime evidence. In
particular this model requires `ledger_meta` and `tenants` to be empty for this tenant:
a populated snapshot/registry is a different storage mode and fails this verifier.

### Exact binding wire format

`fixtures/portable_provisioning_v1/initialized-empty.json` is generated from a real
fresh SQLite create/reopen, not a hand-authored success stub. It is canonical
number-free UTF-8 JSON with exactly these fields:

- `format`: `ir-initialized-empty-workspace-v1`.
- `scaffold`: the complete unchanged `ir-empty-scaffold-v1` input (including its
  original false/false readiness).
- `operational`: **false**.
- `ledger_binding`: exactly `format: ir-empty-ledger-binding-v1`, `tenant_id`, and
  `entities`.

`entities` is the actual `snapshot_ledger_entities(reopened.workspace.ledger)`
serialization. **Empty collections are objects `{}`, not arrays `[]`, null, missing
fields or `{items: []}`.** The required empty map keys are `allocations`,
`attributions`, `donation_allocations`, `donations`, `donors`, `evidence`,
`expense_allocations`, `expense_receipts`, `expenses`, `external_index`,
`receipt_snapshots`, `receipts`. The remaining required key is `organization`, an
object with exactly:

```json
{"id":"org_synthetic_portable","name":"Synthetic portable scaffold","policy_version":"v1"}
```

`organization.id == ledger_binding.tenant_id == scaffold.tenant_id ==
scaffold.policy.policy.tenant_id`; `organization.name` equals policy `display_name`
and `organization.policy_version` equals policy `version`. All are required, even
for an empty ledger. The organization uses `id`, **not** `tenant_id` or
`organization_id`; there is no defaulting to a fixture tenant/name/version. The
empty map shape differs intentionally from the scaffold's declarative
`empty_state.entities: []`. This binding is a strict projection of a reconstructed
ledger, not a ledger command, money mutation, stored Python pickle, or general
nonempty ledger interchange format. Unknown fields/formats fail closed.

### Receipt and separated initialization semantics

`initialized-receipt.json` is generated only by the real SQL verifier. Format is
`ir-initialized-workspace-verification-v1`, with exactly:

- `tenant_id`, `idempotency_key`, `policy_sha256`, `scaffold_sha256` (same hash
  definitions as before), `state_sha256` (hash of the entire canonical state above).
- `storage_scope`: exactly `sql-scaffold-empty-tables-v1`.
- `empty_tables`: exactly the ordered array `['tenants', 'ledger_command_log',
  'ledger_entity', 'ledger_meta', 'outbox_events']`.
- `readiness`: exactly `policy_initialized: true` (strict persisted policy reopened),
  `artifact_verified: true` (immutable expected artifact matched),
  `storage_initialized: true` (within the explicitly named SQL storage scope),
  `workspace_reopened: true` (real tenant workspace reconstructed),
  `operational: false` (never activation).

The initialized schemas enforce all required organization fields, exactly empty
object maps, closed nested objects, literal formats, policy gates, hash syntax,
ordered `empty_tables`, and the exact readiness/scope constants. They do **not**
enforce cross-field organization/policy/tenant equality, recompute the three hashes,
compare confidence thresholds, or validate canonical original bytes and scalar
Unicode. Run the strict Python or Node wire validator as well. The conformance
corpus explicitly expects schema acceptance but semantic rejection for those
structurally valid counterexamples (including duplicate-key/noncanonical wire
inputs after JSON parsing). Neither layer proves that storage was reopened: only
the actual storage verifier supplies that evidence. In particular the SQL receipt
scope is not interchangeable with any Continuity Forge (CF) or host runtime scope.

All fields are mandatory, closed and strictly typed. Hashes are lowercase SHA-256
hex. The evidence is a point-in-time read-only observation, not a signature or an
ongoing readiness guarantee; it does not persist the receipt or authorize writes.
Decoders/`validate_initialized_receipt` only validate wire claims, never prove their
provenance. A host must obtain evidence from its actual storage verifier, not by
passing a matching fixture or constructing these booleans itself. Deterministic
fixtures are explicitly public synthetic conformance evidence, never OBSERVED.

`check_initialized_conformance.mjs` is an independent Node test oracle for the
same strict state/receipt rules; its `--stdin` mode consumes a JSON array of
`{kind: "state" | "receipt", raw: canonical_text}` and reports acceptance booleans
on its final output line (receipt cases bind to the deterministic state fixture).
Its imports also run the existing scaffold byte oracle. This script is not a
Cloudflare storage verifier or a production import surface. Cloudflare can consume
the JSON fixtures and normative wire rules without a Python runtime.

## Reproduce local evidence

From the IR repository with its Python source importable and dev/schema test tools:

```sh
PYTHONPATH=src python scripts/generate_portable_fixtures.py --output fixtures/portable_provisioning_v1
python -m pytest tests/test_portable_provisioning.py tests/test_workspace_repository.py tests/test_sql_command_log.py tests/test_clone_policy_provenance.py -ra
node scripts/check_portable_conformance.mjs
node scripts/check_initialized_conformance.mjs
python -m pytest tests/test_initialized_workspace.py tests/test_initialized_schemas.py -ra
npx --yes --package=ajv-cli@5 ajv validate --spec=draft2020 -r schemas/ir-empty-scaffold-v1.schema.json -s schemas/ir-initialized-empty-workspace-v1.schema.json -d fixtures/portable_provisioning_v1/initialized-empty.json
npx --yes --package=ajv-cli@5 ajv validate --spec=draft2020 -r schemas/ir-empty-scaffold-v1.schema.json -s schemas/ir-initialized-workspace-verification-v1.schema.json -d fixtures/portable_provisioning_v1/initialized-receipt.json
```

Vectors cover defaults, non-ASCII/astral/control/quoted strings, empty lists, missing
filesystem provenance and null provenance. Generation is deterministic; tests compare
all regenerated bytes. Python tests also reject corruption, duplicate keys, foreign
tenants, unsupported versions, weakened gates and premature readiness, and bridge a
fixture through real SQLite create/reopen. Postgres tests only run when an explicitly
configured disposable test database is available; local SQLite evidence is not a
Supabase deployment/transaction proof. For Postgres, run the dedicated SQL/workspace/
portable suites (as the `postgres-store` CI job does) against a disposable database.
Do not export its URL to the entire default suite: legacy host tests share fixed
business keys and are designed for per-test SQLite directories, not one shared
Postgres schema. Run the full default suite with database environment variables
unset, and the dedicated Postgres suite separately.
