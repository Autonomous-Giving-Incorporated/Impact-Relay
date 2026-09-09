// Number-free canonical JSON reference for Cloudflare/Supabase consumers.
// This is a byte/hash oracle, NOT authorization or a complete schema validator.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export function canonicalJSON(value) {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'string') {
    if (!value.isWellFormed()) throw new TypeError('Unicode scalar strings required');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return '[' + value.map(canonicalJSON).join(',') + ']';
  if (typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    const keys = Object.keys(value).sort();
    if (keys.some(key => /[^\x00-\x7f]/.test(key))) throw new TypeError('ASCII keys required');
    return '{' + keys.map(key => JSON.stringify(key) + ':' + canonicalJSON(value[key])).join(',') + '}';
  }
  throw new TypeError('Numbers and non-JSON values forbidden');
}

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'fixtures', 'portable_provisioning_v1');
const manifest = JSON.parse(readFileSync(join(root, 'manifest.json'), 'utf8'));
const sha = value => createHash('sha256').update(value, 'utf8').digest('hex');
for (const vector of manifest.vectors) {
  const raw = readFileSync(join(root, vector.file), 'utf8');
  const artifact = JSON.parse(raw);
  assert.equal(canonicalJSON(artifact), raw);
  assert.equal(sha(raw), vector.scaffold_sha256);
  assert.equal(sha(canonicalJSON(artifact.policy)), vector.policy_sha256);
  assert.equal(artifact.policy_sha256, vector.policy_sha256);
  assert.deepEqual(artifact.readiness, { operational: false, scaffold_verified: false });
}
for (const value of [1, NaN, Infinity, -0, '\ud800', { 'é': true }]) {
  assert.throws(() => canonicalJSON(value));
}
console.log(JSON.stringify({ format: manifest.format, vectors_verified: manifest.vectors.length, operational: false }));
