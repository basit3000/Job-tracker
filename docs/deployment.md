# Setup deployment and recovery

The tracker is a Flask application served by Gunicorn, with PostgreSQL persistence
and Redis rate limits in Compose. A local Job Scout process is not required.
No resources are provisioned by this repository. The configured Compose port is
bound to host loopback; publish through an HTTPS reverse proxy when ready.

## Local development

Use Python 3.11 or later, a private environment file, and a disposable SQLite
database when evaluating fictional data:

```text
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

On Unix, activate with `source .venv/bin/activate`. Copy `.env.example` to `.env`
and set a newly generated `SECRET_KEY` (at least 32 characters). Generate values
with `python -c "import secrets; print(secrets.token_hex(32))"`. Never commit `.env`.
Omit `DATABASE_URL` only when intentionally using the local SQLite default.
Keep `PUBLIC_SIGNUP_ENABLED=false`; create the first account interactively:

```text
flask --app run.py db upgrade
flask --app run.py create-user
python run.py
```

Back up an existing database/uploads before upgrading. Migration
`c61e92ad7401` preserves internal IDs, ownership, old date values and resumes,
maps existing statuses to canonical values, adds nullable actual application
dates, and seeds the change feed without inventing historical transitions.
Unknown legacy statuses cause a preflight error before this migration changes
the schema. Investigate them and resolve them through a reviewed migration;
do not delete data or manually rewrite a live database to bypass the check.

For a fictional demo, choose an empty disposable SQLite database, enable debug
locally, and run `flask --app run.py seed-demo --confirm-fictional`. It prompts
for a password, creates `demo@example.com`, and refuses non-SQLite, non-debug,
or populated databases. Disable debug after development. Do not seed production.

## Compose with separate database roles

Generate four separate values: `SECRET_KEY`, `POSTGRES_PASSWORD` (administration),
`MIGRATOR_DB_PASSWORD` (schema changes), and `APP_DB_PASSWORD` (runtime).
The role bootstrap requires hexadecimal migrator/runtime passwords of at least
32 characters. Generated hex values also work safely in the Compose connection
URIs without additional URI escaping.

```text
docker compose up --build
docker compose exec web flask --app run.py create-user
```

The database image installs `ops/init-postgres.sh`, normalizing Windows line
endings. On a fresh PostgreSQL volume it creates `tracker_migrator` and
`tracker_runtime`, both non-superusers without role/database creation privileges.
The migrator owns the public schema. PUBLIC schema access is revoked; runtime
receives schema usage. The administrative credential remains only in the database
service's environment and is never distributed to browsers or device clients.

`ops/serve.py` applies migrations using `MIGRATION_DATABASE_URL`, grants explicit
application-table permissions with `flask grant-runtime`, removes the migration
URI from the worker environment, and starts Gunicorn with `DATABASE_URL` pointing
to `tracker_runtime`. The runtime cannot alter the schema or Alembic version table.
Events, feed snapshots, mutation receipts and mappings receive SELECT/INSERT only.
Mutable application/account/device tables receive SELECT/INSERT/UPDATE; expired
pairing intents also permit DELETE. Sequence usage allows ordinary inserts.

**Existing database volumes need an administrator-led role transition.** The
official PostgreSQL image runs init scripts only for an empty data directory.
Do not remove an existing volume to force initialization. Back it up, create the
two roles, assign passwords privately, transfer ownership of this application's
tables and their sequences to the migration role, give runtime schema usage,
then apply migrations and runtime grants. A managed PostgreSQL service may use
provider-specific role setup instead of the initialization script.

For an original database containing only `user`, `job_application`, and Alembic
history, an administrator can transfer those known objects explicitly:

```sql
ALTER SCHEMA public OWNER TO tracker_migrator;
ALTER TABLE public."user" OWNER TO tracker_migrator;
ALTER TABLE public.job_application OWNER TO tracker_migrator;
ALTER TABLE IF EXISTS public.alembic_version OWNER TO tracker_migrator;
ALTER SEQUENCE IF EXISTS public.user_id_seq OWNER TO tracker_migrator;
ALTER SEQUENCE IF EXISTS public.job_application_id_seq OWNER TO tracker_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO tracker_runtime;
```

Provision roles before these statements. Verify actual object/sequence names;
if newer tracker tables exist, transfer those application objects too. Avoid
blanket ownership reassignment on a shared database. Set runtime and migration
URIs independently and run migration commands with the migration URI explicitly;
normal CLI account creation should use runtime credentials.

Verify the effective runtime privileges on a disposable deployment using an
administrator or migration connection. These expected booleans check schema
creation, account access, append-only records, and migration-history access:

```sql
SELECT has_schema_privilege('tracker_runtime', 'public', 'CREATE'); -- false
SELECT has_table_privilege('tracker_runtime', 'public."user"', 'INSERT'); -- true
SELECT has_table_privilege('tracker_runtime', 'public.status_event', 'INSERT'); -- true
SELECT has_table_privilege('tracker_runtime', 'public.status_event', 'UPDATE'); -- false
SELECT has_table_privilege('tracker_runtime', 'public.change_entry', 'DELETE'); -- false
SELECT has_table_privilege('tracker_runtime', 'public.alembic_version', 'UPDATE'); -- false
SELECT rolsuper, rolcreatedb, rolcreaterole
FROM pg_roles WHERE rolname = 'tracker_runtime'; -- all false
```

Exercise account creation, pairing, application changes and revocation through
the runtime connection after these checks. Role membership or existing default
grants can add privileges: investigate unexpected results before using real data.

Account isolation is enforced by shared application services and tested API
queries, with database constraints for identities, mappings, statuses and versions.
This implementation does not claim PostgreSQL row-level security. No browser or
device receives database credentials. Use a dedicated application database and
keep database ports private. Redis has no published port and holds rate counters,
not the application records.

## HTTPS and proxy configuration

Terminate HTTPS in a maintained reverse proxy and forward to the loopback web
port. Set `SESSION_COOKIE_SECURE=true`, `FLASK_DEBUG=false`,
`PUBLIC_SIGNUP_ENABLED=false`, and `ALLOW_INSECURE_LOCAL_API=false`.
Forward the original Host and `X-Forwarded-Proto: https`. Gunicorn's
`FORWARDED_ALLOW_IPS` must contain only the exact trusted proxy peer address as
seen by the web container, not `*`. A Docker bridge peer is often different from
host loopback. Verify `request.is_secure` through the deployment and exercise
pairing before use. Never bypass TLS verification or distribute admin credentials.

Browser forms need no CORS allowance. The Node adapter initiates HTTPS requests
outbound. The peer-IP limiter currently sees the server/proxy peer; account for
that aggregate limit when deploying behind a proxy. Do not trust arbitrary
forwarded client-IP headers to increase limits. Configure shared Redis for all
multiworker deployments; in-memory limiting is for one local development process.

Persist PostgreSQL `pgdata` and the upload directory. Keep environment secrets,
backups, logs and uploads outside tracked source/build context. Avoid logging
request bodies, authorization headers, cookies, pairing secrets, or SQL driver
error details. The API stores only safe error codes for connection state.
The Docker lifecycle/role setup must be exercised on a disposable PostgreSQL
deployment before production; Docker was not available during implementation.

## Backups exports and recovery

Browser JSON/CSV exports include active application records and explicitly
selected fields, plus public IDs/versions and creation/update timestamps. They
exclude account credentials, device credentials, resume files, and internal paths.
They are portable record exports, not full backups or a round-trip restore format.
No general JSON/CSV restore endpoint is implemented. Use reviewed API creation for
selected portable fields, producing new cloud IDs, or database backup restoration
when preserving identities, versions, devices and tombstones is required.

Full recovery needs the database and upload directory from a consistent point.
Stop writes for a coordinated database/file backup; encrypt private backups and
verify restoration in an isolated disposable environment. Keep encryption keys
and database passwords separately. Never commit backups, including hashed-account
and device-credential databases. Follow [PostgreSQL privileges](https://www.postgresql.org/docs/current/ddl-priv.html)
and [official image initialization guidance](https://hub.docker.com/_/postgres)
when configuring roles and recovery tooling.

For local SQLite, the backup helper uses SQLite's backup API so committed WAL
contents are included without manually copying journals:

```text
python ops/backup_sqlite.py --database jobtracker.db --destination backups/tracker-backup.db
```

It refuses to overwrite files or the source database and checks backup integrity.
Point an isolated app at the backup copy to validate it, rather than replacing a
live file. `tests/test_recovery.py` verifies restored public IDs, history, versions,
and cursor reset behavior using fictional data. Back up uploads separately while
writes are stopped; SQLite backup does not include attachment bytes.

For PostgreSQL, use `pg_dump --format=custom --file=<private-backup>` with credentials
supplied privately, then restore with `pg_restore` into a separately provisioned
disposable database and roles. Match database and upload snapshots. Verify schema
revision, row ownership, public IDs, version/feed consistency, attachment access
and constraints before switching service traffic. Do not use a destructive clean
restore against an active database as a validation step. Retain migrations in Git.
Downgrading the new tracker migration loses new sync/date/history fields; backup
restoration is the recovery method when those fields must be preserved.

After an older backup restore, retained device tokens may refer to later lost
history. Revoke existing devices, rotate the session signing key, and require
fresh pairing/snapshots. Preserve client pending/conflict state for explicit
review; do not replay it blindly or promise to recover changes absent from the
backup. Tombstones, change snapshots and receipts have no automatic expiry in
this version, so database backups contain retained historical record data.

## Verification

```text
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pip_audit -r requirements.txt
node --test reference-client/client.test.mjs
```

PostgreSQL concurrency tests create and drop only a generated `tracker_test_*`
schema. Supply `TEST_POSTGRES_URL` privately for a dedicated disposable test
database whose test role can create schemas, then run
`python -m pytest tests/test_concurrency.py -q`. Do not point this at production.
The five PostgreSQL cases skip when no test URI is provided; SQLite cases still
exercise real concurrent transactions. Tests do not load a real local `.env`.

For desktop/mobile browser flows:

```text
pip install -r requirements-browser.txt
python -m playwright install chromium
```

Set `RUN_BROWSER_TESTS=1` (`$env:RUN_BROWSER_TESTS='1'` in PowerShell), then run
`python -m pytest tests/test_browser_flows.py -q`. It uses a temporary HTTP service,
fictional accounts/uploads, Chromium at desktop/mobile sizes, and screenshots in
ignored `.venv/browser-review/`. Tests cover login, creation/editing, dates/history,
resume download, board/queues, field-selected export, deletion and logout.
