/** Fictional standalone client. It never reads or writes a Job Scout workspace. */
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, open, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, resolve, sep } from 'node:path';

export const DEFAULT_FIELDS = [
  'title', 'company', 'url', 'board', 'location', 'status', 'appliedDate',
  'followUpDate', 'postedAt', 'postedAtApproximate', 'applicants',
];
export const OPTIONAL_FIELDS = ['note', 'contactName', 'contactEmail', 'contactPhone', 'salary'];

export class ApiError extends Error {
  constructor(status, code, current) {
    // Do not put response contents, URLs, or credentials into error logs.
    super(`Tracker API error ${status}: ${code}`);
    this.status = status;
    this.code = code;
    this.current = current;
  }
}

export function validateOrigin(value, allowLoopbackHttp = false) {
  const url = new URL(value);
  const local = allowLoopbackHttp && ['127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) ||
      url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) {
    throw new Error('Use an HTTPS origin, or explicitly allow a numeric loopback HTTP origin.');
  }
  return url.origin;
}

export function selectFields(record, selectedOptional = []) {
  if (selectedOptional.some((name) => !OPTIONAL_FIELDS.includes(name))) {
    throw new Error('Unknown optional field selection.');
  }
  const selected = {};
  for (const name of [...DEFAULT_FIELDS, ...selectedOptional]) {
    if (Object.hasOwn(record, name)) selected[name] = record[name];
  }
  if (Object.hasOwn(record, 'decision')) selected.status = record.decision;
  // date, memory, answers, prepPath, attachments, and arbitrary fields never copy.
  return selected;
}

export function sourceHistory(record, installationId) {
  return (record.statusHistory ?? []).map((event, index) => ({
    sourceEventId: createHash('sha256').update(JSON.stringify([
      installationId, record.id, index, event.from ?? null, event.to, event.at ?? null,
    ])).digest('hex'),
    fromStatus: event.from ?? null,
    status: event.to,
    occurredAt: event.at ?? null,
  }));
}

async function atomicWrite(path, state) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(state)}\n`, { flag: 'wx', mode: 0o600 });
    await rename(temporary, path);
  } finally {
    await unlink(temporary).catch((error) => { if (error.code !== 'ENOENT') throw error; });
  }
}

export class TrackerClient {
  static async open({ baseUrl, statePath = 'private/reference-client.json', allowLoopbackHttp = false }) {
    const origin = validateOrigin(baseUrl, allowLoopbackHttp);
    const path = resolve(statePath);
    if (!path.split(sep).includes('private') || !path.endsWith('.json')) {
      throw new Error('Store client state in an ignored private directory as a JSON file.');
    }
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    let lock;
    try {
      lock = await open(`${path}.lock`, 'wx', 0o600);
    } catch {
      throw new Error('Client state is in use. After a crash, verify no client is running before removing its private lock file.');
    }
    try {
      let state;
      try { state = JSON.parse(await readFile(path, 'utf8')); }
      catch (error) {
        if (error.code !== 'ENOENT') throw new Error('Client state cannot be read. Preserve it before recovery.');
        state = { origin, installationId: randomUUID(), token: null, optionalFields: [],
          pending: [], conflicts: [], failures: [], applications: {}, cursor: null, snapshotCursor: null };
      }
      if (state.origin !== origin) throw new Error('This state belongs to another service origin. Use a separate state file.');
      const client = new TrackerClient(origin, path, state, lock);
      await client.persist();
      return client;
    } catch (error) {
      await lock.close();
      await unlink(`${path}.lock`);
      throw error;
    }
  }

  constructor(origin, path, state, lock) {
    this.origin = origin;
    this.path = path;
    this.state = state;
    this.lock = lock;
  }

  async close() {
    if (this.lock) {
      await this.lock.close();
      await unlink(`${this.path}.lock`);
      this.lock = null;
    }
  }

  async persist() { await atomicWrite(this.path, this.state); }

  async request(path, { method = 'GET', body, authenticated = true } = {}) {
    if (authenticated && !this.state.token) throw new Error('Pair a device before syncing.');
    const headers = { Accept: 'application/json' };
    if (authenticated) headers.Authorization = `Bearer ${this.state.token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    for (let attempt = 0; attempt < 3; attempt++) {
      let response;
      try {
        response = await fetch(`${this.origin}/api/v1${path}`, {
          method, headers, body: body === undefined ? undefined : JSON.stringify(body),
          redirect: 'manual', signal: AbortSignal.timeout(10000),
        });
      } catch {
        if (attempt === 2) throw new Error('Tracker unreachable. Pending changes and cursors remain in private state.');
        await new Promise((done) => setTimeout(done, 250 * 2 ** attempt));
        continue;
      }
      if (response.status >= 300 && response.status < 400) {
        throw new Error('Redirect refused. Configure the final HTTPS service origin.');
      }
      if ((response.status === 429 || response.status >= 500) && attempt < 2) {
        const delay = Math.min(2000, Math.max(250, Number(response.headers.get('retry-after') ?? 1) * 1000));
        await new Promise((done) => setTimeout(done, Number.isFinite(delay) ? delay : 1000));
        continue;
      }
      let payload;
      try { payload = await response.json(); }
      catch { throw new Error('Invalid tracker response. State has been preserved.'); }
      if (!response.ok) throw new ApiError(response.status, payload.error?.code ?? 'unknown', payload.error?.current);
      return payload;
    }
  }

  async beginPairing(name = 'Fictional reference client') {
    if (this.state.token) throw new Error('Disconnect this client before pairing again.');
    const pairing = await this.request('/pairings', { method: 'POST', authenticated: false,
      body: { installationId: this.state.installationId, name } });
    this.state.pairing = pairing;
    await this.persist();
    return { userCode: pairing.userCode, approvalUrl: `${this.origin}${pairing.approvalPath}` };
  }

  async redeemPairing() {
    if (!this.state.pairing) throw new Error('Start pairing first.');
    const { pairingId, pairingSecret } = this.state.pairing;
    const result = await this.request('/pairings/redeem', { method: 'POST', authenticated: false,
      body: { pairingId, pairingSecret } });
    this.state.token = result.token;
    this.state.deviceId = result.deviceId;
    this.state.optionalFields = result.optionalFields;
    this.state.applications = {};
    this.state.cursor = null;
    this.state.snapshotCursor = null;
    delete this.state.pairing;
    await this.persist();
  }

  async enqueue(mutation) {
    if (!this.state.token) throw new Error('Pair before creating pending changes.');
    const mutationKeys = new Set(['operation', 'mutationId', 'applicationId', 'expectedVersion', 'fields', 'localRecordId', 'statusHistory']);
    if (!mutation || typeof mutation !== 'object' || Array.isArray(mutation) || Object.keys(mutation).some((key) => !mutationKeys.has(key))) {
      throw new Error('Mutation contains forbidden metadata.');
    }
    const allowed = new Set([...DEFAULT_FIELDS, ...this.state.optionalFields]);
    if (Object.keys(mutation.fields ?? {}).some((key) => !allowed.has(key))) {
      throw new Error('Mutation contains fields outside the paired device scope.');
    }
    const pending = structuredClone({ ...mutation, mutationId: mutation.mutationId ?? randomUUID() });
    this.state.pending.push(pending);
    // Durable before the first request: restart sends exactly the same mutation ID.
    await this.persist();
    return pending.mutationId;
  }

  async enqueueLocalRecord(record, { selectedOptional = [], applicationId, expectedVersion } = {}) {
    if (selectedOptional.some((key) => !this.state.optionalFields.includes(key))) {
      throw new Error('Pairing did not grant one of the selected optional fields.');
    }
    const mutation = {
      operation: applicationId ? 'update' : 'create',
      localRecordId: record.id,
      fields: selectFields(record, selectedOptional),
      statusHistory: sourceHistory(record, this.state.installationId),
    };
    if (applicationId) Object.assign(mutation, { applicationId, expectedVersion });
    return this.enqueue(mutation);
  }

  apply(application) {
    if (!application || !/^[a-f0-9-]{36}$/.test(application.id) || !Number.isSafeInteger(application.version) || application.version < 1) {
      throw new Error('Invalid application response. State has been preserved.');
    }
    const permitted = new Set([...DEFAULT_FIELDS, ...this.state.optionalFields,
      'id', 'version', 'createdAt', 'updatedAt', 'deletedAt', 'statusHistory', 'mappings']);
    application = Object.fromEntries(Object.entries(application).filter(([key]) => permitted.has(key)));
    const existing = this.state.applications[application.id];
    if (!existing || application.version >= existing.version) this.state.applications[application.id] = application;
  }

  async pushPending() {
    while (this.state.pending.length) {
      const mutation = this.state.pending[0];
      try {
        const result = await this.request('/mutations', { method: 'POST', body: mutation });
        this.apply(result.application);
        this.state.pending.shift();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status === 401 || error.status === 429 || error.status >= 500) throw error;
        const collection = error.status === 409 ? this.state.conflicts : this.state.failures;
        collection.push({ mutation, code: error.code, current: error.current ?? null });
        this.state.pending.shift();
      }
      await this.persist();
    }
  }

  async pull() {
    if (!this.state.cursor) {
      let more = true;
      while (more) {
        const cursor = this.state.snapshotCursor;
        const page = await this.request(`/applications?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
        for (const entry of page.entries) this.apply(entry.application);
        this.state.snapshotCursor = page.cursor;
        more = page.hasMore;
        if (!more) {
          this.state.cursor = page.changesCursor;
          this.state.snapshotCursor = null;
        }
        await this.persist();
      }
    }
    let more = true;
    while (more) {
      const page = await this.request(`/changes?limit=50&cursor=${encodeURIComponent(this.state.cursor)}`);
      for (const entry of page.entries) this.apply(entry.application);
      // State application and cursor advancement share one atomic file replacement.
      this.state.cursor = page.cursor;
      more = page.hasMore;
      await this.persist();
    }
  }

  async sync() {
    await this.pushPending();
    await this.pull();
    return { pending: this.state.pending.length, conflicts: this.state.conflicts.length,
      failures: this.state.failures.length, applications: Object.keys(this.state.applications).length };
  }

  async resetSnapshot() {
    // Explicit recovery; preserve pending changes and conflicts for review.
    this.state.cursor = null;
    this.state.snapshotCursor = null;
    this.state.applications = {};
    await this.persist();
  }

  async resolveConflict(mutationId, chosenFields) {
    const index = this.state.conflicts.findIndex((item) => item.mutation.mutationId === mutationId);
    if (index < 0) throw new Error('Conflict not found.');
    const conflict = this.state.conflicts[index];
    if (!conflict.mutation.applicationId) throw new Error('Mapping/create conflicts require explicit mapping review.');
    const current = await this.request(`/applications/${encodeURIComponent(conflict.mutation.applicationId)}`);
    if (current.deletedAt) throw new Error('Deleted applications cannot be revived.');
    // User must review and choose fields; never replay the stale request automatically.
    await this.enqueue({ operation: 'update', applicationId: current.id,
      expectedVersion: current.version, fields: chosenFields });
    this.state.conflicts.splice(index, 1);
    await this.persist();
  }

  async disconnect() {
    await this.request('/device/revoke', { method: 'POST' });
    this.state.token = null;
    delete this.state.deviceId;
    await this.persist();
  }
}
