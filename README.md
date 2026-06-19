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
- **Docker Support** — One-command setup with Docker Compose (Gunicorn + PostgreSQL)
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
├── docker-entrypoint.sh      # Runs migrations/init-db before serving
├── docker-compose.yml        # Web + PostgreSQL orchestration
├── app/
│   ├── __init__.py           # App factory (create_app), CLI, error handlers
│   ├── extensions.py         # SQLAlchemy, LoginManager, Migrate, CSRFProtect
│   ├── forms.py              # WTForms form classes
│   ├── models.py             # User and JobApplication models
│   ├── routes/
│   │   ├── auth.py           # Register, login, logout
│   │   └── jobs.py           # Dashboard + job CRUD + resume upload/download
│   ├── static/css/styles.css # Custom styles
│   └── templates/            # Jinja2 HTML templates
│       ├── base.html
│       ├── home.html
│       ├── login.html
│       ├── register.html
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

# (Optional) create a .env file — see "Environment Variables" below

# Create the database tables
flask --app run.py init-db

# Start the development server
python run.py
```

The app will be available at **http://localhost:5000**.

> Using migrations instead of `init-db`? Run `flask db init` (first time only), then
> `flask db migrate -m "message"` and `flask db upgrade`.

### Docker (PostgreSQL + Gunicorn)

```bash
# Create a .env file with the variables below, then:
docker-compose up --build
```

The container automatically applies migrations (or runs `init-db` if no `migrations/`
folder exists) before starting Gunicorn. App available at **http://localhost:5000**.

## Environment Variables

Create a `.env` file in the project root (it is git-ignored). Generate a secret key with
`python -c "import secrets; print(secrets.token_hex(32))"`.

| Variable               | Description                                          | Default                   |
|------------------------|------------------------------------------------------|---------------------------|
| `SECRET_KEY`           | Flask secret key for sessions / CSRF                 | random per restart        |
| `DATABASE_URL`         | Database connection URI                              | `sqlite:///jobtracker.db` |
| `UPLOAD_FOLDER`        | Where resumes are stored                             | `./uploads`               |
| `SESSION_COOKIE_SECURE`| `true` to only send cookies over HTTPS               | `false`                   |
| `FLASK_DEBUG`          | `true`/`false` for the dev server                    | `true`                    |
| `POSTGRES_USER`        | PostgreSQL username (Docker)                         | —                         |
| `POSTGRES_PASSWORD`    | PostgreSQL password (Docker)                         | —                         |
| `POSTGRES_DB`          | PostgreSQL database name (Docker)                    | —                         |

Example `.env`:

```env
SECRET_KEY=replace-with-a-long-random-string
SESSION_COOKIE_SECURE=false
# Docker / PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-me
POSTGRES_DB=jobtracker
```

## Usage

1. **Register** an account at `/register`
2. **Log in** at `/login`
3. Land on your **Dashboard** (`/dashboard`) for an overview
4. **Add** applications at `/jobs/add` (optionally attach a resume)
5. **Browse** and search all applications at `/jobs`
6. **View** an application's details, **Edit**, or **Delete** it

## License

This project is for personal/educational use.
