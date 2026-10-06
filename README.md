# Job Tracker

A full-stack web application for tracking job applications, built with Flask. Manage your
job search by logging applications, tracking statuses, attaching resumes, and keeping
notes — all behind secure user authentication.

## Features

- **User Authentication** — Register, login, and logout with hashed passwords (Werkzeug)
- **Dashboard** — At-a-glance stats: totals, in-progress, interviews, and offers, with a per-status breakdown
- **Job Application CRUD** — Add, edit, view, and delete applications with rich fields (title, company, location, salary, posting URL, contact, notes)
- **Search, Filter & Sort** — Find applications by company/role/location, filter by status, and sort by date or name
- **Resume Uploads** — Attach a resume (PDF/DOC/DOCX/RTF/TXT) to each application and download it later
- **Status Tracking** — Wishlist → Applied → Interviewing → Offer → Accepted / Rejected
- **Per-User Data** — Each user only ever sees their own applications
- **Security** — CSRF protection on every form, hardened session cookies, safe redirects, open-redirect protection
- **Docker Support** — Docker Compose with Gunicorn, PostgreSQL, and Redis for shared authentication rate limits
- **Database Migrations** — Schema changes managed with Flask-Migrate / Alembic

## Tech Stack

| Layer      | Technology                          |
|------------|-------------------------------------|
| Backend    | Python 3.11, Flask 3                 |
| Database   | PostgreSQL 14 (SQLite for dev)      |
| ORM        | Flask-SQLAlchemy                    |
| Migrations | Flask-Migrate (Alembic)             |
| Auth       | Flask-Login, Werkzeug password hash |
| Forms      | Flask-WTF, WTForms (+ CSRF)         |
| Frontend   | Jinja2 templates, Bootstrap 5       |
| Server     | Gunicorn (production)               |
| Container  | Docker, Docker Compose              |

## Project Structure

```
├── config.py                 # App configuration (secrets, DB URI, uploads, cookies)
├── run.py                    # Application entry point (dev server)
├── requirements.txt          # Pinned Python dependencies
├── Dockerfile                # Container image (Gunicorn)
├── docker-compose.yml        # Web + PostgreSQL + Redis orchestration
├── migrations/              # Checked-in Alembic migration history
├── tests/                   # Security, CRUD, file lifecycle, and migration checks
├── app/
│   ├── __init__.py           # App factory (create_app), error handlers, security headers
│   ├── extensions.py         # SQLAlchemy, LoginManager, Migrate, CSRFProtect, Limiter
│   ├── forms.py              # WTForms form classes
│   ├── authentication.py     # Account creation and credential checks
│   ├── database.py           # Shared commit / rollback boundary
│   ├── errors.py             # Shared error page rendering
│   ├── security.py           # HTTP headers and authentication rate limit policy
│   ├── services.py           # User-scoped application queries and persistence
│   ├── uploads.py            # Resume file storage and upload policy
│   ├── utils.py              # URL validation
│   ├── models.py             # User and JobApplication models
│   ├── routes/
│   │   ├── auth.py           # Register, login, logout
│   │   └── jobs.py           # Dashboard + job CRUD + resume upload/download
│   ├── static/css/styles.css # Custom styles
│   ├── static/js/forms.js    # Form confirmation behavior
│   └── templates/            # Jinja2 HTML templates
│       ├── base.html
│       ├── home.html
│       ├── login.html
│       ├── register.html
│       ├── auth/base.html    # Shared login / registration layout
│       ├── macros/           # Shared fields, CSRF inputs, badges, and controls
│       ├── errors/error.html
│       └── jobs/
│           ├── dashboard.html
│           ├── list.html
│           ├── detail.html
│           └── form.html     # Shared add/edit form
└── uploads/                  # User-uploaded resumes (created at runtime)
```

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional, for the PostgreSQL setup)

### Local Development (SQLite)

```bash
# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Copy .env.example to .env and set SECRET_KEY to a generated random value
# See "Environment Variables" below

# Apply the checked-in database migrations
flask --app run.py db upgrade

# Start the development server
python run.py
```

The app will be available at **http://localhost:5000**.

For future schema changes, run `flask --app run.py db migrate -m "message"`,
review the generated migration, then run `flask --app run.py db upgrade`.
Commit migration scripts along with model changes.

If an existing database was created with the old `init-db` command, it has no
Alembic revision. Back it up and compare its schema to the current models before
using `flask --app run.py db stamp head` to record an already matching schema.
Databases with migration history should use `db upgrade` directly.

### Docker (PostgreSQL + Gunicorn)

```bash
# Create a .env file with the variables below, then:
docker-compose up --build
```

The container applies the checked-in migrations before starting Gunicorn.
Compose requires both `SECRET_KEY` and `POSTGRES_PASSWORD` in `.env` and starts
Redis for rate limits shared across Gunicorn workers.
App available at **http://localhost:5000**.

## Environment Variables

Create a `.env` file in the project root (it is git-ignored). Generate a secret key with
`python -c "import secrets; print(secrets.token_hex(32))"`.

| Variable               | Description                                          | Default                   |
|------------------------|------------------------------------------------------|---------------------------|
| `SECRET_KEY`           | Private random session / CSRF key, at least 32 characters | required              |
| `DATABASE_URL`         | Database connection URI                              | `sqlite:///jobtracker.db` |
| `UPLOAD_FOLDER`        | Where resumes are stored                             | `./uploads`               |
| `SESSION_COOKIE_SECURE`| `true` to only send cookies over HTTPS               | `false`                   |
| `FLASK_DEBUG`          | `true`/`false` for the dev server                    | `false`                   |
| `RATELIMIT_STORAGE_URI`| Shared rate limit storage for multiple workers     | `memory://` locally; Redis in Compose |
| `POSTGRES_USER`        | PostgreSQL username (Docker)                         | —                         |
| `POSTGRES_PASSWORD`    | PostgreSQL password (Docker)                         | required for Docker       |
| `POSTGRES_DB`          | PostgreSQL database name (Docker)                    | —                         |

Example `.env`:

```env
SECRET_KEY=paste-a-generated-random-secret-of-at-least-32-characters
SESSION_COOKIE_SECURE=false
# Docker / PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=paste-a-separately-generated-random-password
POSTGRES_DB=jobtracker
```

Generate separate random values for `SECRET_KEY` and `POSTGRES_PASSWORD` using
the command above. Hexadecimal passwords also avoid URI escaping issues in the
Compose database URL. For an HTTPS deployment, set `SESSION_COOKIE_SECURE=true`.
Keep debug mode off on public deployments. Non-Compose deployments with multiple
workers must configure shared rate limit storage, such as Redis.

Login and registration POST requests are limited to 10 per minute and 100 per
hour per client IP. Logout uses a CSRF-protected POST form. Job posting links
accept HTTP and HTTPS, and unsafe legacy URLs are displayed as plain text.

## Tests and Dependency Audit

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pip_audit -r requirements.txt
```

Tests use temporary SQLite databases upgraded through Alembic and temporary
upload folders. They cover authentication, CSRF, authorization between users,
unsafe URLs, resume replacement failures, and migration data preservation.

## Development Conventions

Follow [PEP 8](https://peps.python.org/pep-0008/) for naming, imports, and readable
Python formatting. `pyproject.toml` sets Python 3.11 as the lint target, a
79-character line limit, and checks for errors, import order, common mistakes,
unnecessary complexity, and functions with excessive branching.

The [Flask application factory](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)
configures extensions and registers blueprints. Routes handle HTTP input,
forms, and responses; authentication and application services handle business
operations. Models own reusable account and application queries.

- Begin application queries with `JobApplication.for_user(user_id)` to preserve
  ownership scoping.
- Use `database_transaction()` for service writes. Upload cleanup follows a
  successful commit, and failed uploads or commits clean up new files.
- Reuse [Jinja macros](https://jinja.palletsprojects.com/en/stable/templates/#macros)
  and the shared authentication layout for fields, validation errors, CSRF
  inputs, badges, dates, and delete controls.
- Derive form length limits from model columns and upload messages from config
  so validation and displayed limits agree.
- Keep migration scripts self-contained: historical schema steps must remain
  independent of changing application models and helpers.

Tests are organized by authentication, job behavior, upload failures, security,
configuration, and migrations. Common request helpers live in `tests/helpers.py`.

## Private Local Files

Git and Docker exclusions cover local environment files, database files and
journals, database exports and backups, resume uploads, logs, private keys,
credential files, and private data directories. Local data remains on your
computer; it is excluded from source commits and container build context.

`.env.example` is a committable template with empty credential values. Test
accounts and migration-test rows use fictional `example.com` addresses.
The privacy tests check exclusions for both root and nested paths and verify
that the environment template contains no credential values.

## Usage

1. **Register** an account at `/register`
2. **Log in** at `/login`
3. Land on your **Dashboard** (`/dashboard`) for an overview
4. **Add** applications at `/jobs/add` (optionally attach a resume)
5. **Browse** and search all applications at `/jobs`
6. **View** an application's details, **Edit**, or **Delete** it

## License

This project is for personal/educational use.
