# Job Tracker

A full-stack web application for tracking job applications, built with Flask. Manage your
job search by logging applications, tracking statuses, attaching resumes, and keeping
notes — all behind secure user authentication.

## Features

- **User Authentication** — Register, login, and logout with hashed passwords (Werkzeug)
- **Dashboard** — At-a-glance stats: totals, in-progress, interviews, and offers, with a per-status breakdown
- **Job Application CRUD** — Add, edit, view, and delete applications with rich fields (title, company, location, salary, posting URL, contact, notes)
- **Search, Filter & Sort** — Find applications by company, role, location, or contact; filter by status; sort by date or name
- **Resume Uploads** — Attach a resume (PDF/DOC/DOCX/RTF/TXT, max 5 MB) and download it later
- **Status Tracking** — Wishlist → Applied → Interviewing → Offer → Accepted / Rejected
- **Per-User Data** — Each user only ever sees their own applications
- **Security** — CSRF protection on every form, hardened session cookies, safe redirects / open-redirect protection
- **Docker Support** — One-command setup with Docker Compose (Gunicorn + PostgreSQL)

## Tech Stack

| Layer      | Technology                          |
|------------|-------------------------------------|
| Backend    | Python 3.11, Flask 3                 |
| Database   | PostgreSQL 14 (SQLite for local dev) |
| ORM        | Flask-SQLAlchemy                    |
| Migrations | Flask-Migrate (optional; see below) |
| Auth       | Flask-Login, Werkzeug password hash |
| Forms      | Flask-WTF, WTForms (+ CSRF)         |
| Frontend   | Jinja2 templates, Bootstrap 5       |
| Server     | Gunicorn (Docker / production)      |
| Container  | Docker, Docker Compose              |

## Architecture

```
Browser ──► Flask app factory (app/__init__.py)
              ├── auth blueprint   — register / login / logout
              ├── jobs blueprint   — dashboard, CRUD, resume files
              ├── SQLAlchemy models (User, JobApplication)
              └── uploads/         — resume files on disk (UUID filenames)
```

Local `python run.py` binds **127.0.0.1:5000**. Docker serves with Gunicorn
(`0.0.0.0:5000`, 3 workers) after creating tables via `flask init-db`, or
`flask db upgrade` if a `migrations/` directory is present at runtime.

## Project Structure

```
├── config.py                 # Secrets, DB URI, uploads, cookies
├── run.py                    # Dev entry point (127.0.0.1:5000)
├── requirements.txt          # Pinned Python dependencies
├── example.env               # Env template (copy to .env)
├── Dockerfile                # Image; inline CMD starts DB then Gunicorn
├── docker-compose.yml        # Web + PostgreSQL orchestration
├── app/
│   ├── __init__.py           # App factory, CLI (init-db), error handlers
│   ├── extensions.py         # SQLAlchemy, LoginManager, Migrate, CSRFProtect
│   ├── forms.py              # WTForms form classes
│   ├── models.py             # User and JobApplication models
│   ├── routes/
│   │   ├── auth.py           # Register, login, logout, home redirect
│   │   └── jobs.py           # Dashboard + job CRUD + resume upload/download
│   ├── static/css/styles.css
│   └── templates/            # Jinja2 HTML templates
└── uploads/                  # User-uploaded resumes (created at runtime)
```

> `migrations/` is gitignored and dockerignored by design. The image runs
> `flask init-db` unless you mount a local `migrations/` folder. Optional local
> flow: `flask --app run.py db init`, `db migrate`, `db upgrade`.

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional, for PostgreSQL)

### Local Development (SQLite)

```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Optional: copy example.env → .env and set SECRET_KEY
cp example.env .env

# Create the database tables
flask --app run.py init-db

# Start the development server
python run.py
```

App: **http://127.0.0.1:5000**.

Password rules on register: minimum **8** characters. Emails are stored lowercased.

### Docker (PostgreSQL + Gunicorn)

```bash
cp example.env .env   # set SECRET_KEY; Postgres defaults work out of the box
docker-compose up --build
```

Startup (from `Dockerfile` CMD): if `migrations/` exists → `flask db upgrade`;
else → `flask init-db`; then Gunicorn. App: **http://localhost:5000**.
Resumes persist via the `./uploads` bind mount; Postgres data uses volume `pgdata`.

## Environment Variables

Create a `.env` in the project root (git-ignored). Generate a secret with
`python -c "import secrets; print(secrets.token_hex(32))"`.

| Variable                | Description                                       | Default |
|-------------------------|---------------------------------------------------|---------|
| `SECRET_KEY`            | Sessions / CSRF                                   | Random hex each process restart (local); Docker Compose default `dev-secret-change-me` |
| `DATABASE_URL`          | SQLAlchemy URI                                    | Absolute SQLite under the project dir (`sqlite:////…/jobtracker.db`) |
| `UPLOAD_FOLDER`         | Resume storage directory                          | `{project}/uploads` |
| `SESSION_COOKIE_SECURE` | `true` to send cookies only over HTTPS            | `false` |
| `FLASK_DEBUG`           | Dev server debug flag                             | `true` |
| `FLASK_APP`             | Set in Docker image only                          | `run.py` |
| `POSTGRES_USER`         | Postgres user (Compose)                           | `postgres` |
| `POSTGRES_PASSWORD`     | Postgres password (Compose)                       | `postgres` |
| `POSTGRES_DB`           | Postgres database name (Compose)                  | `jobtracker` |

`postgres://` URIs are rewritten to `postgresql://` automatically.

Also enforced in config (not env): `MAX_CONTENT_LENGTH = 5 MB`, upload extensions
`pdf/doc/docx/rtf/txt`, cookies `HttpOnly` + `SameSite=Lax`.

See `example.env` for a ready-to-copy template.

## Routes

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/` | No | Redirects to dashboard if logged in |
| GET/POST | `/register` | No | Min 8-char password |
| GET/POST | `/login` | No | Supports safe `?next=` |
| GET | `/logout` | Yes | |
| GET | `/dashboard` | Yes | Stats + recent 5 applications |
| GET | `/jobs` | Yes | Query: `q`, `status`, `sort` (`newest`/`oldest`/`company`/`title`) |
| GET | `/jobs/<id>` | Yes | Detail |
| GET/POST | `/jobs/add` | Yes | Optional resume upload |
| GET/POST | `/jobs/<id>/edit` | Yes | Replacing a resume deletes the old file |
| POST | `/jobs/<id>/delete` | Yes | Deletes row + resume file |
| GET | `/jobs/<id>/resume` | Yes | Download attached resume |

Dashboard cards: **In progress** = Applied + Interviewing + Offer; **Offers** =
Offer + Accepted. Default new status is **Applied**.

## Usage

1. **Register** at `/register`, then **log in** at `/login`
2. Open the **Dashboard** for totals and recent applications
3. **Add** an application at `/jobs/add` (optionally attach a resume ≤ 5 MB)
4. **Browse** `/jobs` — search (`q`), filter by status, sort
5. **View** / **edit** / **delete** from the detail page; download resume when present

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Logged out after every restart | Set a stable `SECRET_KEY` in `.env` |
| CSRF / form validation errors | Refresh the page; ensure cookies are enabled |
| `413` on upload | Resume exceeds 5 MB — compress or use a smaller file |
| Docker web waits forever | Confirm `db` healthcheck passes (`pg_isready`); check `POSTGRES_*` |
| Empty DB after rebuild | Local SQLite file was wiped, or Docker volume was removed |

## License

This project is for personal/educational use.
