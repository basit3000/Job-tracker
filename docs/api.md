# Job Scout Tracker API v1

The Flask service implements device pairing, application mutations, stable
snapshots, and an incremental change feed. It works independently of Job Scout.
The standalone Node client demonstrates this contract with fictional records.
It is not an adapter for an installed Job Scout workspace.

Machine-readable OpenAPI 3.1 documentation is served at
`GET /api/v1/openapi.json`. Field schemas derive from `app/contracts.py` and are
checked against runtime inputs in the test suite. Authentication, operation
rules, and per-device field permissions are enforced by the server.

## Authentication and pairing

Device endpoints require HTTPS and `Authorization: Bearer <device-token>`.
Browser cookies never authorize device endpoints. CORS is closed. A development
exception requires `ALLOW_INSECURE_LOCAL_API=true` and a numeric loopback peer;
the reference client also requires `--allow-loopback-http`. Do not enable this
exception on a hosted service. The browser approval route uses session login
and CSRF-protected POST forms.

1. `POST /api/v1/pairings` with
   `{"installationId":"fictional-installation","name":"Example client"}`.
   The response contains `pairingId`, `pairingSecret`, `userCode`, `expiresIn`
   (600 seconds), and `approvalPath` (`/integrations`). Store the pairing secret
   privately. Only the approval code should be displayed to the user.
2. Sign in, open the integration page, inspect the code/device identity, and
   approve the optional field scope. Requests expire after ten minutes and can
   be approved only once. No account is selected by the anonymous request.
3. `POST /api/v1/pairings/redeem` with `pairingId` and `pairingSecret`.
   Before approval it returns `409 approval_pending`. Once approved it returns
   `deviceId`, `token`, and `optionalFields`, and consumes the pairing request.
4. `GET /api/v1/device` reports the current device identity and optional scope.
   `POST /api/v1/device/revoke`, or the browser Disconnect button, revokes the
   credential. Subsequent reads and writes return 401, including writes that
   authenticated before revocation but were waiting for the account lock.

Credential verification hashes, rather than plaintext credentials, are stored
in the database. Tokens are scoped to one account and installation and confer
no session, administrative, database, or attachment access. Losing the single
successful redemption response requires pairing again and revoking the orphan
device in the browser. Secrets and record bodies must not be logged.

Pairing is limited to 5 requests/minute and 20/hour per peer IP. Redemption is
limited to 30/minute; the API blueprint is limited to 120/minute. Redis shares
these limits across production workers. Devices display last authenticated
exchange and the last observed error code. Successful exchanges clear that
error code. This does not assert that a future adapter applied remote changes.

## Application fields and identity

Default device fields are `title`, `company`, `url`, `board`, `location`, `status`,
`appliedDate`, `followUpDate`, `postedAt`, `postedAtApproximate`, and `applicants`.
Mapping and status-history operations are also available. `note`, `contactName`,
`contactEmail`, `contactPhone`, and `salary` require explicit browser selection
at pairing. This grant applies to both push and pull for that account's records.
Changing scope requires revoking and pairing again.

Unknown fields are rejected, including owner IDs, memory, answers, attachment
fields, filesystem paths, settings, and credentials. Omitted allowed fields
are unchanged. An explicit null clears nullable fields; empty required titles,
companies, invalid statuses, and null booleans are rejected.

| API field | Model field | Constraint |
|---|---|---|
| `id` | `public_id` | Server-generated UUID; read only |
| `title` | `job_title` | Required, maximum 128 characters |
| `company` | `company` | Required, maximum 128 characters |
| `url` | `job_url` | HTTP/HTTPS without credentials; maximum 512 |
| `board`, `location` | Same names | Maximum 128 each |
| `note` | `notes` | Optional scope; maximum 20,000 |
| `contactName` | `contact_person` | Optional scope; maximum 128 |
| `contactEmail` | `contact_email` | Optional scope; validated email, maximum 254 |
| `contactPhone`, `salary` | `contact_phone`, `salary` | Optional scope; maximum 80 / 64 |
| `appliedDate`, `followUpDate` | `applied_on`, `follow_up_on` | Nullable calendar dates, `YYYY-MM-DD` |
| `createdAt`, `updatedAt` | `created_at`, `updated_date` | Server event timestamps, UTC |
| `version`, `deletedAt` | `version`, `deleted_at` | Server controlled |

Canonical statuses are `shortlisted`, `applied`, `interviewing`, `offer`,
`accepted`, `rejected`, `closed`, and `skipped`. Accepted, rejected, closed, and
skipped clear the follow-up date. Date queues use UTC calendar days. Setting
status to applied does not infer an application date. Existing legacy
`applied_date` remains preserved separately; it was often record creation time.

Public cloud IDs do not replace internal database IDs. `localRecordId` is an
opaque string up to 256 characters, preserved exactly, associated with the
paired installation. Account/installation/local-ID and application/installation
uniqueness prevent duplicate mappings. No company/title/URL fuzzy merge occurs.

`postedAt` is a nullable timestamp with an explicit offset, normalized to UTC.
`postedAtApproximate` is a boolean and requires a posting timestamp when true.
`applicants` is nullable or an object with `count`, `relation`, `label`, `source`,
`url`, and `observedAt`. Known counts require a nonempty source, observation time,
and `exact`, `less-than`, `more-than`, or `at-least` relation. Count must be a
nonnegative integer up to one billion, or null. Null is unknown, never zero.
Observation URLs are validated without fetching them. Counts are not verified
completed applications or views; the UI displays provenance and observation time.

## Mutations and conflicts

`POST /api/v1/mutations` accepts one JSON mutation, at most 128 KiB:

```json
{
  "mutationId": "fictional-mutation-001",
  "operation": "create",
  "localRecordId": "manual:application:11111111-1111-4111-8111-111111111111",
  "fields": {
    "title": "Example Engineer",
    "company": "Example Company",
    "status": "applied",
    "appliedDate": null
  }
}
```

Responses use `{"mutationId":"...","application":{...}}`. Creates require title
and company and reject client-selected cloud IDs/versions. `localRecordId` is
optional, so cloud-created applications work without a local mapping.

`update`, `delete`, and `map` require `applicationId` and the positive integer
`expectedVersion`. `map` also requires `localRecordId`. Updates can attach a
mapping. Delete/map reject application fields or history. Delete also rejects
a mapping input. Every browser edit/delete uses the same version-aware services.

A mutation ID is a stable string of up to 128 characters scoped to the device.
An exact retry returns the stored original outcome; reusing the ID with different
JSON content returns `409 mutation_reused`. Generate a new ID only for a new
intent or an explicitly reviewed conflict resolution, not for a network retry.
An unchanged update does not increment the version or create a status event.

Version conflicts return 409 with this shape:

```json
{
  "error": {
    "code": "version_conflict",
    "message": "This application changed. Review the current version before retrying.",
    "current": {"id":"11111111-1111-4111-8111-111111111111","version":2}
  }
}
```

The actual `current` object includes only the device's permitted fields. Display
the conflict and let the user choose which changes to retain. Do not automatically
substitute a new expected version and replay stale fields.

`statusHistory` accepts at most 100 imported events per mutation. Each event has
`sourceEventId`, `status`, optional `fromStatus`, and nullable `occurredAt`. Event
timestamps require an explicit UTC offset. The same installation/source-event ID
is deduplicated; reuse for another application or changed content conflicts.
Server history adds public event ID, source (`browser`, `device`, or `import`),
installation/source identifiers, and server `recordedAt`. Cloud creation and
actual status transitions are recorded truthfully; missing historical event
times are not invented. Browser and API edits share transition/follow-up rules.

Record changes, versions, mappings, history, change entries, and mutation receipts
commit together. Database failures return `503 temporarily_unavailable`; retry
the same mutation. No retired resume is removed before a successful commit.

## Snapshot and change feed

`GET /api/v1/applications?limit=50` starts a consistent snapshot. Responses have
`entries`, opaque `cursor`, `hasMore`, and `watermark`. Each entry contains
`sequence`, `source`, `mutationId`, and the scoped `application` snapshot.

Continue with `cursor` until `hasMore=false`. The final page includes a
`changesCursor`; pass it to `GET /api/v1/changes`. The snapshot includes the latest
immutable entry for each application at the fixed watermark, including tombstones.
Updates committed while paging appear in subsequent changes, not inconsistently
in the earlier snapshot. `GET /api/v1/applications/{applicationId}` retrieves one
owned current application or its minimal tombstone.

`GET /api/v1/changes?cursor=...&limit=50` resumes a finite commit-ordered window.
Without a cursor it starts from the beginning of retained account history.
Continue while `hasMore=true`; after reaching the watermark, a later poll with
the returned cursor opens the next window. Limits are 1-100. Cursors are signed
and bound to account, device, and feed kind. Never use a snapshot cursor as a
changes cursor; use the final `changesCursor` instead.

All record writers first acquire the account row with a database UPDATE. The
next account sequence and immutable payload are allocated in that same transaction.
PostgreSQL row locks serialize these writers through commit; SQLite serializes
its writers. No later account sequence can commit ahead of an earlier one. This
avoids the gaps caused by treating auto-increment IDs as commit order. The
production verification suite is in `tests/test_concurrency.py`.

Persist received changes and cursor advancement atomically. Repeated pages are
safe: retain the highest record version, including deletion versions. Do not
push imported remote events back as new local events; retain source/mutation/event
IDs as acknowledgments. A future adapter must persist its pending queue before
sending and remove items only after durable acknowledgment.

History, idempotency receipts, mappings, and tombstones have no automatic retention
expiry in this version. Deletion hides the record from active pages/exports and
removes its resume after commit, but database history/snapshots are retained for
reliable synchronization. A tombstone cannot be edited or recreated through its
old mapping. Cursors have no time expiry but become invalid after signing-key
rotation, device replacement, or incompatible history restoration. A watermark
ahead of restored history returns `409 cursor_reset_required`. Start a fresh
snapshot after reviewing/restoring client state; keep pending work for conflict
review. A future purge policy must introduce explicit cursor expiry/reset rules.

Other errors include 401 for missing/revoked credentials, 404 for unowned IDs,
410 for expired/consumed pairings, 413 for body limits, 415 for non-JSON input,
422 for validation/scope/cursor errors, and 429 for request limits. Error bodies
use `{"error":{"code":"...","message":"..."}}` and contain no credentials.
