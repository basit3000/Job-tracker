# Job Tracker

Ready-to-configure hosting for Railway, Vercel, and Docker-based providers is
documented in [cloud deployment](docs/cloud-deployment.md). Railway supports
continuous workers; Vercel uses managed PostgreSQL, Redis, private object storage,
and external scheduling for frequent syncs/reminders.

Home brings together a community feed, a brief personal progress summary, friend
requests, and next steps. **My tracker → Insights** includes a 28-day application
chart, a 12-week consistency calendar, current/longest streaks, XP, goals, and
milestone badges. Optional daily email nudges are available in
**Account → Notifications**. See [email reminder setup](docs/notifications.md)
for SMTP configuration and the background worker. Email delivery defaults to off.

A Flask application for tracking private application records online, independently of
whether a local Job Scout process is running. It extends this repository's app
factory, blueprints, SQLAlchemy models, Jinja templates, and resume storage.

## Features

- Public email/password registration with private per-user records, password
  hashing, CSRF-protected forms, and POST logout.
- Google signup/sign-in when OAuth credentials are configured, with explicit
  password-confirmed linking for existing accounts in Account settings.
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
- Reviewed imports from Excel, ODS, CSV/TSV, JSON, pasted tables and Google Sheets,
  with suggested mappings, date/status validation and duplicate detection.
- Connected Google Sheets and Notion sources with exact cell ranges, custom
  mappings, stable IDs, conflict-preserving inbound updates and optional polling.
  See [source sync setup](docs/source-sync.md).
- Browser-approved device pairing, explicit optional field permissions, immediate
  revocation, and a versioned bearer-authenticated API with OpenAPI schemas.
- Atomic version checks, idempotent mutations, explicit identity mappings,
  commit-ordered change feeds, stable snapshots, and deletion tombstones.
- A standalone Node reference client that demonstrates durable retries, push/pull,
  conflict review, and revocation using fictional records.
- Docker deployment with Gunicorn, PostgreSQL roles for migration/runtime access,
  Redis rate limits, tracked migrations, and documented backup/recovery.
- Optional community profiles with public/private visibility, mutual friend
  requests, friend comparisons, and explicitly enabled sharing of applied jobs.
- Daily application goals, best-day records, streaks, XP, levels, activity charts,
  and milestones derived from your existing application records.

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

On Windows, a `DLL load failed while importing _psycopg` error can come from
an older driver built locally without its required DLLs. Python 3.14 requires
psycopg2 2.9.11 or newer; this project pins a compatible version. After updating
the repository, reinstall the prebuilt driver wheel in the affected environment
(replace `venv` with `.venv` if that is your environment's name):

```powershell
venv\Scripts\python.exe -m pip install --force-reinstall --no-cache-dir --only-binary=:all: psycopg2-binary==2.9.13
venv\Scripts\python.exe -c "import psycopg2; print(psycopg2.__version__)"
```

Set a private, stable `SECRET_KEY` in `.env`, using a generated value:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

For a new local development database, use a SQLite `DATABASE_URL`, then:

```powershell
flask --app run.py db upgrade
python run.py
```

Open `http://localhost:5000/register` to create an account, then log in.
The optional `flask --app run.py create-user` command still creates accounts
administratively. A real existing database needs a backup before `db upgrade`;
development tests do not migrate your local database.

Keep the migration directory tracked. Migration files describe schema changes,
not your database contents. Tracker revision `c61e92ad7401` preserves legacy IDs,
ownership, resume associations, and the original `applied_date`, maps legacy
statuses, and introduces a separate nullable actual application date. Unexpected
legacy statuses stop the upgrade for review. Never stamp an old schema as `head`
to bypass these changes.

Revision `d48f7a916b02` preserves existing password accounts and adds Google
identities. Google-only accounts have no password credential. It refuses a
downgrade that would discard Google identities; use a compatible backup instead.

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
| `PUBLIC_SIGNUP_ENABLED` | Registration switch, default `true`; `false` closes new signup |
| `GOOGLE_CLIENT_ID` | Google OAuth web client ID; empty until configured |
| `GOOGLE_CLIENT_SECRET` | Private Google OAuth client secret; never commit it |
| `GOOGLE_REDIRECT_URI` | Exact registered callback; local default `http://localhost:5000/auth/google/callback` |
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

## Google signup and sign-in

A public domain is not needed for local development. Create a Google OAuth web
client with the authorized redirect URI
`http://localhost:5000/auth/google/callback`, then set its client ID and secret in
your private `.env`. Restart after configuring them. The Google button appears
on login/registration pages only when both credentials are configured.

Follow [the Google login setup guide](docs/google-login.md) for Cloud Console
steps, local testing, HTTPS deployment, and connecting an existing account.

## Community and progress

The header keeps **Home**, **My tracker**, and **People** visible. Home is the
default destination after sign-in; explicit links to other pages still work.
Inside My tracker, switch between **Applications**, **Status board**, **Insights**,
and **Follow-ups**. Use **Data tools** for imports, exports, and connections;
use **Account** for profile/privacy,
sign-in settings, and logout. **Add application** is always available in the header.
On phones, **Menu** opens data tools and account settings while the main sections
remain visible.

Open **People** in the header. Choose a username
in **Account → Profile & privacy**, set a goal, and decide who can see your profile.
Existing and new accounts default to private with job sharing off. Public means
visible to signed-in community members. Private profiles show their identity for
an exact username lookup, but only accepted friends can see their bio and stats.
Email addresses are never part of member discovery or other members' profiles.

Send and accept friend requests to compare today, the last seven days, total
applications, best day, or current streak. Either friend can remove the connection
to end private-profile access. A public profile remains visible to signed-in
members until its owner switches it to private.

**Share my applied jobs on my profile** is a separate opt-in. Shared lists and
the home feed show
only company, role, posting link, status, and application date. Notes, resumes,
salary, contact details, follow-ups, and connected-source credentials remain
private. Viewers can open the posting or save a job to their own shortlist; this
creates a new private record without copying application dates or private fields.
It does not submit an application to the employer.

The home feed has **Discover** (public profiles and accepted friends), **Friends**,
and **Career wins** (shared interviewing, offer, and accepted applications).
Search by role, company, or public name/username. Results use application-date
order, with unknown dates last and ten items per page. The feed uses the same
permissions and limited field projection as shared profiles; sharing changes,
removed friendships, and deleted records take effect on the next request.
Private edits never become feed timestamps. No new sharing defaults or schema
migrations are introduced by the social home.

The UI includes visible keyboard focus, labeled controls and errors, reduced
motion support, larger touch targets, higher-contrast status badges, and mobile
shortcuts to requests and next steps. Browser coverage checks 320, 390, 768, and
1440 pixel home layouts. To also run an automated WCAG A/AA audit, set
`AXE_CORE_SCRIPT` to a local axe-core JavaScript bundle while running
`RUN_BROWSER_TESTS=1 pytest tests/test_social_home_browser.py`. The app loads no
external accessibility script at runtime. Automated checks are not a complete
accessibility conformance assessment.

Daily stats use recorded `applied_on` dates and the UTC calendar, never creation
timestamps. Submitted statuses are applied, interviewing, offer, accepted, and
rejected; closed records count only when they have an application date. Unknown
dates count toward total applications and XP but not daily totals or streaks.
Future dates, shortlisted, skipped, and deleted records are excluded. A streak
remains active when yesterday was the latest application day. Each submitted
record contributes 10 XP; every 10 applications adds a level. Editing or deleting
records updates stats and milestones, and changing status never counts a job twice.

Migration `a93e7d4b620f` adds profile preferences, friendships, and an activity
index without altering existing application records. Back up an existing database
before running `flask --app run.py db upgrade`. Compose startup also refreshes
runtime permissions, including deletion of friendship requests/connections.

## API and reference client

Import an existing tracker from **Data tools → Import & sync**. Choose a
one-time import or keep Google Sheets or Notion connected for later syncing.
See [the import guide](docs/importing.md) for supported formats, smart mapping,
private Google Sheets authorization and preview cleanup. Apply migration
`f70a93bd2158` when updating an existing database.

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

Google tests replace only the provider HTTP transport with fictional responses;
Authlib performs real state, PKCE, signature, issuer, audience, expiry, and nonce
validation. Browser tests exercise public signup, Google signup/sign-in, and
password-confirmed linking at desktop/mobile sizes. These do not contact real
Google accounts or replace a live OAuth credential/deployment check.

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

See the [code and privacy review](docs/code-and-privacy-review.md) for applied
principles, verification, and the remaining personal attribution in Git history.
Browser fonts, stylesheets, and scripts are served locally; asset versions and
licenses are documented in `app/static/vendor/README.md`.

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
