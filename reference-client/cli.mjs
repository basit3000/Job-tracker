import { readFile } from 'node:fs/promises';
import { ApiError, TrackerClient } from './client.mjs';

const [command = 'help', baseUrl, ...args] = process.argv.slice(2);
const allowLoopbackHttp = args.includes('--allow-loopback-http');
const values = args.filter((item) => item !== '--allow-loopback-http');

async function run() {
  if (command === 'help' || !baseUrl) {
    console.log('node reference-client/cli.mjs <pair|redeem|demo|sync|conflicts|resolve|reset-snapshot|disconnect> <https-origin> [arguments] [--allow-loopback-http]');
    console.log('State and credentials remain in ignored private/reference-client.json. Demo uses only bundled fictional records.');
    return;
  }
  const client = await TrackerClient.open({ baseUrl, allowLoopbackHttp });
  try {
    if (command === 'pair') console.log(await client.beginPairing());
    else if (command === 'redeem') {
      await client.redeemPairing();
      console.log('Paired. Credential saved privately; never printed.');
    } else if (command === 'demo') {
      const records = JSON.parse(await readFile(new URL('./fictional-records.json', import.meta.url), 'utf8'));
      for (const record of records) {
        const mapped = Object.values(client.state.applications).find((application) =>
          application.mappings?.some((mapping) => mapping.localRecordId === record.id));
        if (!mapped) await client.enqueueLocalRecord(record);
      }
      console.log(await client.sync());
    } else if (command === 'sync') console.log(await client.sync());
    else if (command === 'reset-snapshot') { await client.resetSnapshot(); console.log('Snapshot reset. Pending changes and conflicts preserved for review.'); }
    else if (command === 'conflicts') console.log(client.state.conflicts.map(({ mutation, code }) =>
      ({ mutationId: mutation.mutationId, applicationId: mutation.applicationId, code })));
    else if (command === 'resolve') {
      const [mutationId, status] = values;
      if (!mutationId || !status) throw new Error('After reviewing the current application, supply conflict mutation ID and chosen canonical status.');
      await client.resolveConflict(mutationId, { status });
      console.log(await client.sync());
    } else if (command === 'disconnect') {
      await client.disconnect();
      console.log('Credential revoked.');
    } else throw new Error('Unknown command.');
  } finally { await client.close(); }
}

run().catch((error) => {
  if (error instanceof ApiError && error.status === 409 && error.code === 'approval_pending') {
    console.error('Approval pending. Approve the displayed code in your signed-in browser, then redeem again.');
  } else console.error(error.message);
  process.exitCode = 1;
});
