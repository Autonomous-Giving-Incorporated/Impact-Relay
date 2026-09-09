// Strict local conformance oracle. No storage, authority or runtime is inferred.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { canonicalJSON } from './check_portable_conformance.mjs';

const hash = value => createHash('sha256').update(canonicalJSON(value), 'utf8').digest('hex');
const load = name => JSON.parse(readFileSync(new URL('../fixtures/portable_provisioning_v1/' + name, import.meta.url), 'utf8'));
const template = load('default.json');
const tables = ['tenants', 'ledger_command_log', 'ledger_entity', 'ledger_meta', 'outbox_events'];
const maps = ['donors', 'donations', 'allocations', 'donation_allocations', 'expenses', 'expense_allocations', 'evidence', 'attributions', 'receipts', 'receipt_snapshots', 'expense_receipts', 'external_index'];
function shape(value, example, path = '') {
  if (path === '.policy.policy.source_path') {
    assert.ok(value === null || typeof value === 'string'); return;
  }
  if (Array.isArray(example)) {
    assert.ok(Array.isArray(value));
    for (const item of value) assert.equal(typeof item, 'string');
  } else if (example !== null && typeof example === 'object') {
    assert.ok(value !== null && typeof value === 'object' && !Array.isArray(value));
    assert.deepEqual(Object.keys(value).sort(), Object.keys(example).sort());
    for (const key of Object.keys(example)) shape(value[key], example[key], path + '.' + key);
  } else assert.equal(typeof value, typeof example);
}
function scaffold(value) {
  shape(value, template);
  assert.equal(value.format, 'ir-empty-scaffold-v1');
  assert.match(value.tenant_id, /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/);
  assert.match(value.idempotency_key, /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/);
  assert.equal(value.policy.format, 'ir-portable-policy-v1');
  const p = value.policy.policy;
  assert.equal(p.tenant_id, value.tenant_id);
  assert.match(p.version, /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/);
  // JS $ permits a terminal newline; reject that rather than repairing tokens.
  for (const token of [value.tenant_id, value.idempotency_key, p.version]) assert.ok(!/[\r\n]/.test(token));
  for (const number of Object.values(p.confidence)) assert.match(number, /^(?:0|1|0\.[0-9]{0,5}[1-9])$(?![\s\S])/);
  const millionths = number => BigInt(number.split('.')[0]) * 1000000n + BigInt((number.split('.')[1] || '').padEnd(6, '0'));
  assert.ok(millionths(p.confidence.block_below) <= millionths(p.confidence.recommend_high));
  for (const gate of template.policy.policy.authority.l3_command_types) assert.ok(p.authority.l3_command_types.includes(gate));
  assert.equal(p.evidence.require_donor_visible, true);
  assert.equal(p.notifications.require_separate_send_approval, true);
  assert.deepEqual(value.empty_state, { entities: [], ledger_commands: [], outbox_events: [] });
  assert.deepEqual(value.readiness, { operational: false, scaffold_verified: false });
  assert.equal(value.policy_sha256, hash(value.policy));
}
export function validateState(raw) {
  const state = JSON.parse(raw);
  assert.equal(canonicalJSON(state), raw);
  scaffold(state.scaffold);
  const p = state.scaffold.policy.policy;
  const entities = Object.fromEntries(maps.map(key => [key, {}]));
  entities.organization = { id: p.tenant_id, name: p.display_name, policy_version: p.version };
  assert.deepEqual(state, {
    format: 'ir-initialized-empty-workspace-v1', scaffold: state.scaffold,
    ledger_binding: { format: 'ir-empty-ledger-binding-v1', tenant_id: p.tenant_id, entities },
    operational: false,
  });
  return state;
}
export function validateReceipt(raw, state) {
  validateState(canonicalJSON(state));
  const s = state.scaffold;
  assert.equal(raw, canonicalJSON({
    format: 'ir-initialized-workspace-verification-v1', tenant_id: s.tenant_id,
    idempotency_key: s.idempotency_key, policy_sha256: s.policy_sha256,
    scaffold_sha256: hash(s), state_sha256: hash(state),
    storage_scope: 'sql-scaffold-empty-tables-v1', empty_tables: tables,
    readiness: { policy_initialized: true, artifact_verified: true, storage_initialized: true,
      workspace_reopened: true, operational: false },
  }));
}
const state = validateState(canonicalJSON(load('initialized-empty.json')));
validateReceipt(canonicalJSON(load('initialized-receipt.json')), state);
if (process.argv.includes('--stdin')) {
  const cases = JSON.parse(readFileSync(0, 'utf8'));
  const accepted = cases.map(item => {
    try {
      if (item.kind === 'state') validateState(item.raw);
      else validateReceipt(item.raw, state);
      return true;
    } catch { return false; }
  });
  console.log(JSON.stringify(accepted));
} else console.log(JSON.stringify({ initialized_state_verified: true, receipt_verified: true, operational: false }));
