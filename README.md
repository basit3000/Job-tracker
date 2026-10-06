# Job Scout Tracker

A private Flask application for tracking applications online, independently of
whether a local Job Scout process is running. It extends this repository's app
factory, blueprints, SQLAlchemy models, Jinja templates, and resume storage.

## Features

- Private accounts, password hashing, CSRF-protected forms, and POST logout.
  Public registration is disabled by default; create an account through the CLI.
- Dashboard, searchable paginated table, status board, and follow-up queue with
  filters for status, company, board, and due dates.
- Manual application editing, notes, contacts, salary, safe job links, and
  authenticated resume uploads/downloads.
- Eight canonical statuses: `shortlisted`, `applied`, `interviewing`, `offer`,
  `accepted`, `rejected`, `closed`, and `skipped`.
- Nullable application/follow-up calendar dates, UTC event timestamps, and status
  history with provenance. Unknown application dates remain unknown. Follow-ups
  use the UTC calendar and clear automatically for terminal statuses.
- Optional public posting/applicant observations with source and observation
  time; unknown counts remain unknown.
- Account-scoped JSON/CSV exports with field selection and CSV formula protection.
- Browser-approved device pairing, explicit optional field permissions, immediate
  revocation, and a versioned bearer-authenticated API with OpenAPI schemas.
- Atomic version checks, idempotent mutations, explicit identity mappings,
  commit-ordered change feeds, stable snapshots, and deletion tombstones.
- A standalone Node reference client that demonstrates durable retries, push/pull,
  conflict review, and revocation using fictional records.
- Docker deployment with Gunicorn, PostgreSQL roles for migration/runtime access,
  Redis rate limits, tracked migrations, and documented backup/recovery.

The reference client is working demonstration code. Connecting the installed
Job Scout application still requires a dedicated adapter; see the
[integration guide](docs/job-scout-integration.md). Resume files and candidate
memory are outside the sync API.

## Local setup

Use Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a private, stable `SECRET_KEY` in `.env`, using a generated value:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

For a new local development database, use a SQLite `DATABASE_URL`, then:

```powershell
flask --app run.py db upgrade
flask --app run.py create-user
python run.py
```

Open `http://localhost:5000/login`. The account command prompts for an email and
password without enabling public signup. A real existing database needs a backup
before `db upgrade`; development tests do not migrate your local database.

Keep the migration directory tracked. Migration files describe schema changes,
not your database contents. The new revision preserves legacy internal IDs,
ownership, resume associations, and the original `applied_date`, maps legacy
statuses, and introduces a separate nullable actual application date. Unexpected
legacy statuses stop the upgrade for review. Never stamp an old schema as `head`
to bypass these changes.

[Deployment and recovery](docs/deployment.md) explains existing databases,
account bootstrap, opt-in fictional seeding, HTTPS, and backups. Do not seed a
real database.

## Configuration

`.env.example` contains empty secret placeholders; `.env` is private and ignored.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required stable random signing key, at least 32 characters |
| `DATABASE_URL` | Runtime database URI; local default `sqlite:///jobtracker.db` |
| `UPLOAD_FOLDER` | Private resume storage, local default `uploads/` |
| `PUBLIC_SIGNUP_ENABLED` | Explicit registration switch, default `false` |
| `FLASK_DEBUG` | Development debugging, default `false`; off in production |
| `SESSION_COOKIE_SECURE` | Use `true` behind HTTPS |
| `RATELIMIT_STORAGE_URI` | Shared Redis storage for multiple workers |
| `ALLOW_INSECURE_LOCAL_API` | Explicit loopback-only development API exception, default `false` |
| `POSTGRES_PASSWORD` | Compose database administration credential |
| `MIGRATOR_DB_PASSWORD` | Separate Compose schema-owner credential |
| `APP_DB_PASSWORD` | Separate Compose runtime credential |
| `MIGRATION_DATABASE_URL` | Migrator URI for startup migrations, separate from runtime URI |
| `FORWARDED_ALLOW_IPS` | Exact trusted proxy peers for Gunicorn |

For a fresh Compose database, generate separate hexadecimal passwords of at least
32 characters for all three database credentials. Compose publishes the web port
on loopback. Production device connections require HTTPS; put a correctly
configured reverse proxy in front, with secure cookies and trusted proxy peers.

```powershell
docker compose up --build
```

Compose provisions migration/runtime roles only on a fresh database volume.
Existing volumes require the documented ownership transition before using this
configuration. Do not delete an existing volume to make initialization rerun.

## API and reference client

The public schema is served at `/api/v1/openapi.json`. All tracker API data
requires a device credential, independently of browser cookies. Pairing requires
approval from the signed-in browser. Notes, contact fields, and salary require
explicit individual permissions; omitted fields leave stored values unchanged.

See [the API contract](docs/api.md) for request/response fields, validation,
versions, idempotency, cursors, snapshots, tombstones, and retention. See
[reference-client instructions](docs/job-scout-integration.md#fictional-reference-client) for Node 22+ usage
and durable private state. The client does not read real Job Scout records.

## Tests and checks

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
python -m pip_audit -r requirements.txt
node --test reference-client/client.test.mjs
```

Tests use fictional accounts, temporary databases upgraded through Alembic, and
temporary uploads. They cover auth/ownership/privacy, migration preservation,
API/browser versions, atomic failures, concurrent commits, retries, exports,
reference-client recovery, and database backup/restore. The Node end-to-end test
runs when Node 22+ is installed.

Optional desktop/mobile browser checks:

```powershell
pip install -r requirements-browser.txt
python -m playwright install chromium
$env:RUN_BROWSER_TESTS = '1'
python -m pytest tests/test_browser_flows.py -q
```

PostgreSQL concurrency and constraint checks run when `TEST_POSTGRES_URL` points
to a dedicated test database whose user can create schemas. They create and
remove only their own randomly named test schema. Without that variable, those
checks skip; SQLite tests do not verify PostgreSQL behavior. Deployment role
verification and commands are in [the deployment guide](docs/deployment.md).

## Code and privacy conventions

Routes handle HTTP input and responses; shared services enforce ownership,
validation, version checks, and transactions. Browser and API writes use one
application update path. Shared Jinja macros render fields, badges, dates,
CSRF tokens, pagination, and deletion controls. Python formatting and complexity
limits are configured in `pyproject.toml`; migration scripts stay independent of
changing application helpers.

Git and Docker exclusions cover private environment files, database files,
dumps/backups, uploads, logs, keys, credentials, and private state directories.
Test fixtures and demo records are fictional. Keep real personal data and
credentials out of commits and screenshots. Author attribution belongs in Git
commit metadata.

Deletion hides records, removes their manual resume, and creates a sync tombstone.
Historical snapshots, receipts, mappings, and tombstones are retained; deletion
is not an immediate purge of every historical copy. JSON/CSV exports contain
selected active records and are not a full database/upload backup. Read the
retention and recovery documentation before production use.

## License

This project is for personal/educational use.
