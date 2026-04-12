# Job Tracker

A full-stack web application for tracking job applications, built with Flask and PostgreSQL. Manage your job search by logging applications, tracking statuses, and keeping notes — all behind secure user authentication.

## Features

- **User Authentication** — Register, login, and logout with hashed passwords (Werkzeug)
- **Job Application CRUD** — Add, edit, and delete job applications
- **Status Tracking** — Track each application as Applied, Interviewing, Offer, or Rejected
- **Per-User Data** — Each user sees only their own applications
- **Contact & Notes** — Store contact person and free-form notes per application
- **Docker Support** — One-command setup with Docker Compose (Flask + PostgreSQL)
- **Database Migrations** — Schema changes managed with Flask-Migrate / Alembic

## Tech Stack

| Layer      | Technology                          |
|------------|-------------------------------------|
| Backend    | Python 3.11, Flask                  |
| Database   | PostgreSQL 14 (SQLite for dev)      |
| ORM        | Flask-SQLAlchemy                    |
| Migrations | Flask-Migrate (Alembic)             |
| Auth       | Flask-Login, Werkzeug password hash |
| Forms      | Flask-WTF, WTForms                  |
| Frontend   | Jinja2 templates, Bootstrap 5       |
| Container  | Docker, Docker Compose              |

## Project Structure

```
├── config.py                 # App configuration (secrets, DB URI)
├── run.py                    # Application entry point
├── requirements.txt          # Python dependencies
├── Dockerfile                # Container image definition
├── docker-compose.yml        # Multi-service orchestration
├── app/
│   ├── __init__.py           # App factory (create_app)
│   ├── extensions.py         # SQLAlchemy, LoginManager, Migrate
│   ├── forms.py              # WTForms form classes
│   ├── models.py             # User and JobApplication models
│   ├── routes/
│   │   ├── auth.py           # Register, login, logout routes
│   │   └── jobs.py           # Job CRUD routes
│   ├── static/css/styles.css # Custom styles
│   └── templates/            # Jinja2 HTML templates
│       ├── base.html
│       ├── home.html
│       ├── login.html
│       ├── register.html
│       └── jobs/
│           ├── add.html
│           ├── edit.html
│           └── list.html
├── migrations/               # Alembic migration versions
└── uploads/                  # User-uploaded files
```

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (or SQLite for local development)
- Docker & Docker Compose (optional)

### Local Development

```bash
# Clone the repository
git clone <repo-url>
cd "Job tracker"

# Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Set up environment variables (create a .env file)
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///jobtracker.db

# Run database migrations
flask db upgrade

# Start the development server
python run.py
```

The app will be available at **http://localhost:5000**.

### Docker

```bash
# Create a .env file with PostgreSQL credentials
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password
POSTGRES_DB=jobtracker
DATABASE_URL=postgresql://postgres:your-password@db:5432/jobtracker
SECRET_KEY=your-secret-key

# Build and start
docker-compose up --build
```

The app will be available at **http://localhost:5000**.

## Environment Variables

| Variable            | Description                        | Default                     |
|---------------------|------------------------------------|-----------------------------|
| `SECRET_KEY`        | Flask secret key for sessions      | `devkey`                    |
| `DATABASE_URL`      | Database connection URI            | `sqlite:///jobtracker.db`   |
| `POSTGRES_USER`     | PostgreSQL username (Docker)       | —                           |
| `POSTGRES_PASSWORD` | PostgreSQL password (Docker)       | —                           |
| `POSTGRES_DB`       | PostgreSQL database name (Docker)  | —                           |

## Usage

1. **Register** an account at `/register`
2. **Log in** at `/login`
3. **Add** job applications at `/jobs/add`
4. **View** all your applications at `/jobs`
5. **Edit** or **Delete** applications from the list

## License

This project is for personal/educational use.
