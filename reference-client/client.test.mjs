import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { TrackerClient, selectFields, sourceHistory, validateOrigin } from './client.mjs';

test('local projection excludes private fields and never guesses an application date', () => {
  const record = { id: 'opaque-id', title: 'Role', decision: 'applied', date: '2026-01-01',
    note: 'Fictional note', salary: 'Example salary', memory: {}, prepPath: 'private/fictional', attachments: [] };
  assert.deepEqual(selectFields(record), { title: 'Role', status: 'applied' });
  assert.equal(selectFields(record, ['note']).note, 'Fictional note');
  assert.throws(() => selectFields(record, ['memory']));
});

test('credentials cannot be forwarded to non-HTTPS or redirected origins', () => {
  assert.throws(() => validateOrigin('http://example.com', true));
  assert.throws(() => validateOrigin('http://localhost:5000', true));
  assert.throws(() => validateOrigin('https://user:password@example.com'));
  assert.throws(() => validateOrigin('https://example.com/api'));
  assert.equal(validateOrigin('http://127.0.0.1:5000', true), 'http://127.0.0.1:5000');
});

test('source events have stable IDs and retain unknown dates', () => {
  const record = { id: 'opaque', statusHistory: [{ from: null, to: 'applied', at: null }] };
  const events = sourceHistory(record, 'fictional-installation');
  assert.equal(events[0].occurredAt, null);
  assert.deepEqual(events, sourceHistory(record, 'fictional-installation'));
});

test('pending mutations persist before sending and survive a restart', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tracker-client-'));
  const options = { baseUrl: 'https://example.com', statePath: join(root, 'private', 'client.json') };
  const client = await TrackerClient.open(options);
  try {
    client.state.token = 'fictional-token-for-storage-only';
    const mutationId = await client.enqueue({ operation: 'create', fields: { title: 'Role', company: 'Example' } });
    const stored = JSON.parse(await readFile(options.statePath));
    assert.equal(stored.pending[0].mutationId, mutationId);
    await assert.rejects(client.enqueue({ operation: 'create', memory: {}, fields: {} }));
    await assert.rejects(client.enqueue({ operation: 'create', fields: { note: 'Unselected' } }));
    await assert.rejects(TrackerClient.open(options));
  } finally { await client.close(); }
  const reopened = await TrackerClient.open(options);
  try { assert.equal(reopened.state.pending.length, 1); }
  finally { await reopened.close(); }
});

test('late old changes cannot resurrect a tombstone', async () => {
  const root = await mkdtemp(join(tmpdir(), 'tracker-client-'));
  const client = await TrackerClient.open({ baseUrl: 'https://example.com', statePath: join(root, 'private', 'client.json') });
  const id = '11111111-1111-4111-8111-111111111111';
  try {
    client.apply({ id, version: 2, deletedAt: '2026-10-06T10:00:00Z' });
    client.apply({ id, version: 1, title: 'Old record', resume_filename: 'forbidden.pdf' });
    assert.ok(client.state.applications[id].deletedAt);
    assert.equal(client.state.applications[id].title, undefined);
  } finally { await client.close(); }
});
