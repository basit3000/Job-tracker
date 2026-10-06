/** Runs against a disposable fictional service; invoked by pytest. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { ApiError, TrackerClient } from './client.mjs';

const [baseUrl, statePath] = process.argv.slice(2);
const options = { baseUrl, statePath, allowLoopbackHttp: true };
let client = await TrackerClient.open(options);
try {
  const pairing = await client.beginPairing('Fictional integration test');
  console.log(`PAIRING_CODE:${pairing.userCode}`);
  const deadline = Date.now() + 20000;
  while (!client.state.token) {
    try { await client.redeemPairing(); }
    catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'approval_pending' || Date.now() > deadline) throw error;
      await new Promise((done) => setTimeout(done, 250));
    }
  }
  const [record] = JSON.parse(await readFile(new URL('./fictional-records.json', import.meta.url), 'utf8'));
  await client.enqueueLocalRecord(record);
  // Simulate a successful server commit followed by an interrupted acknowledgment.
  await client.request('/mutations', { method: 'POST', body: client.state.pending[0] });
  await client.close();
  client = await TrackerClient.open(options);
  assert.equal(client.state.pending.length, 1);
  await client.sync();
  let application = Object.values(client.state.applications)[0];
  assert.equal(Object.keys(client.state.applications).length, 1);
  assert.equal(application.version, 1);
  assert.equal(application.appliedDate, null);
  assert.equal(application.note, undefined);
  assert.equal(application.contactEmail, undefined);
  assert.equal(application.mappings[0].localRecordId, record.id);
  const id = application.id;
  await client.enqueue({ operation: 'update', applicationId: id, expectedVersion: 1, fields: { status: 'interviewing' } });
  const staleId = await client.enqueue({ operation: 'update', applicationId: id, expectedVersion: 1, fields: { status: 'offer' } });
  const summary = await client.sync();
  assert.equal(summary.conflicts, 1);
  assert.equal(client.state.conflicts[0].code, 'version_conflict');
  await client.resolveConflict(staleId, { status: 'offer' });
  await client.sync();
  application = client.state.applications[id];
  assert.equal(application.status, 'offer');
  assert.equal(application.version, 3);
  await client.enqueue({ operation: 'delete', applicationId: id, expectedVersion: 3 });
  await client.sync();
  assert.ok(client.state.applications[id].deletedAt);
  await client.enqueue({ operation: 'update', applicationId: id, expectedVersion: 3, fields: { status: 'applied' } });
  await client.enqueueLocalRecord(record);
  await client.sync();
  assert.equal(client.state.conflicts.length, 2);
  assert.ok(client.state.applications[id].deletedAt);
  const revokedToken = client.state.token;
  await client.disconnect();
  const revoked = await fetch(`${baseUrl}/api/v1/device`, { headers: { Authorization: `Bearer ${revokedToken}` } });
  assert.equal(revoked.status, 401);
  console.log('REFERENCE_CLIENT_OK');
} finally { await client.close(); }
