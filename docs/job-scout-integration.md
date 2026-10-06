# Connecting Job Scout later

The tracker API and Node reference client work now. This repository does not
modify, read candidate stores from, or connect to an installed Job Scout app.
The later adapter belongs in the local repository and must use an explicit
selection/preview flow before sending records.

## Source compatibility

The local source interfaces were inspected read-only. In
`scripts/lib/decisions.mjs`, `VALID_DECISIONS` matches all eight canonical tracker
statuses. Local current status is `decision`. History is an array of `{from,to,at}`.
`patchDecision(id, patch, {root})` serializes local updates and merges a patch over
the existing record. `recordDecision` can read the fetched archive and supply
additional application fields, so it is not a safe default for cloud imports.

`scripts/lib/application-fields.mjs` validates selected application fields and
calendar dates. Current local limits exceed some tracker limits: title/company
are 300 locally versus 128 online, URL 2000 versus 512, salary 150 versus 64,
contact name 200 versus 128, and phone 100 versus 80. Show validation errors for
selected oversized fields; do not silently truncate or rewrite local originals.
Local notes are limited to 10,000 characters; online notes permit 20,000, so remote
imports need an explicit local validation/conflict decision too.

`web/tracker-routes.mjs` invokes Google Sheets `sync(entry)` after its ordinary
POST/PATCH path. Do not call that route for remote imports. Add a separate local
validated import service with no submission, generation, email, or Sheets effects.
Preserve `web/local-boundary.mjs`: loopback, Host, Origin, fetch-site, and JSON
checks remain unchanged. Outbound Node HTTPS does not require browser CORS,
inbound connections, tunnels, or weakening this boundary.

## Field selection and mapping

Only application records the user explicitly selects enter the pending queue.
Project the allowlist before constructing HTTP requests; never send whole state
files. Pairing grants optional note/contact/salary scope in both directions.
Each local push can further restrict which optional fields it includes. Exclude
memory/answers, CVs/letters/attachments, preparation paths, configuration,
provider credentials, local paths, and the fetched archive regardless of grants.

Map local `decision` to API `status`, with no case conversion or synonym guessing.
Map `note`, contact fields, and the other documented application fields by name.
Never use legacy `date` to fill `appliedDate`. Pass an explicit null for an unknown
application date; local transition logic otherwise assigns today's date when
entering applied. Map an API null clearing contact/text fields to the local
validator's supported empty value deliberately; omitted fields remain untouched.

Persist the installation ID once in ignored private configuration. Maintain
explicit `(installationId, localRecordId) -> cloudId/version` mappings. Local IDs,
including `manual:application:<uuid>`, remain opaque. Never infer identity from
company/title/URL. An online-created record can be assigned a new local manual ID
and explicitly mapped through the API's `map` mutation after user selection.

Retain a durable ledger of source history IDs. Current local events have no IDs;
assign stable IDs to existing events once and persist them privately. The
fictional client demonstrates deterministic IDs using installation, record ID,
event index, and content; a production adapter must additionally detect history
rewrites/reordering rather than treating edited old events as new transitions.
Preserve unknown occurrence times and distinguish them from server recorded time.

## Applying remote changes safely

Extend the local validated update layer with explicit remote-import semantics:
preserve local-only fields and attachments, apply only granted/selected remote
fields, retain source/event IDs, avoid duplicate transition events, and honor
terminal-status follow-up clearing. The current `patchDecision` automatically
updates timestamps/history on a transition; a remote import helper must account
for already imported history instead of appending it again. Existing status,
calendar-date, URL, and contact validation still applies.

Use the serialized record-update functions; do not overwrite `state/decisions.json`
directly or replace entire local records. Do not read `state/memory.json`, private
answers, prep paths, attachment files, or the full job archive for synchronization.
New local records need a validated, side-effect-free creation path that preserves
chosen IDs and unknown dates instead of reusing the ordinary tracker HTTP route.

Persist pending local mutations before sending. Reuse their IDs on transport
retries. Persist applied remote changes and their resumable cursor together, with
recovery bookkeeping if updating local storage and adapter state cannot share a
single atomic operation. Importing a remote event must not enqueue a new local
mutation: maintain origin/acknowledgment markers independently of timestamps.

Display version/mapping/history conflicts and require explicit user choices.
Do not automatically overwrite competing cloud edits or revive a tombstone.
Persist deletion versions and mappings even after hiding a deleted local record.
Credential revocation leaves pending local work available for review; reconnect
through browser-approved pairing and a fresh snapshot.

## Fictional reference client

Node 22 or later is sufficient; no npm dependencies or Job Scout process are
required. From this repository, against an HTTPS service:

```text
node reference-client/cli.mjs pair https://tracker.example.com
node reference-client/cli.mjs redeem https://tracker.example.com
node reference-client/cli.mjs demo https://tracker.example.com
node reference-client/cli.mjs sync https://tracker.example.com
node reference-client/cli.mjs conflicts https://tracker.example.com
node reference-client/cli.mjs disconnect https://tracker.example.com
```

Approve the displayed code in the signed-in browser before redeeming. For a local
Python development server, use `http://127.0.0.1:5000`, set
`ALLOW_INSECURE_LOCAL_API=true`, and add `--allow-loopback-http` to each command.
The client rejects redirects, URL credentials, non-HTTPS remote hosts, and generic
localhost HTTP exceptions. Docker's forwarded loopback port may have a bridge
peer IP and is not this exception; use HTTPS for its device API.

State and credentials live in ignored `private/reference-client.json`, with an
exclusive lock and atomic file replacement. Credentials and record contents are
not printed. Preserve the pending queue after errors. A crashed process can
leave a lock file: verify no client is running before removing that specific
private lock file. Do not delete the state file as a shortcut to retrying work.

`demo` selects only the bundled fictional fixture. It is an explicit sync action,
so run it against a disposable development account. The library exposes
`enqueue`, `enqueueLocalRecord`, `sync`, and explicit `resolveConflict` methods.
After reviewing a status conflict, `resolve <origin> <mutationId> <status>` queues
that chosen change with a fresh mutation ID and the current server version.
Mapping/create conflicts require explicit mapping review, not this shortcut.
`reset-snapshot` clears received cache/cursors while retaining pending/conflict
work; use it for reviewed cursor recovery. The demo does not mutate real local
Job Scout storage or perform any application/AI/Sheets action.

`tests/test_reference_client.py` runs the real client against a temporary HTTP
service, logs in and approves pairing through browser forms, simulates a lost
acknowledgment, resolves a conflict, verifies deletion retries, and revokes access.
`node --test reference-client/client.test.mjs` verifies projection and durable
state independently. Before a real adapter rollout, implement and test local
selection, import semantics, event ledgers, and crash recovery in Job Scout, then
exercise them with fictional records against PostgreSQL and an HTTPS deployment.
