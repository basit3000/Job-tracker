import os
import secrets

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    # In production SECRET_KEY must be provided via the environment. The random
    # fallback keeps local development working but invalidates sessions on every
    # restart, which is a deliberate nudge to set a real value.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    # Normalise the old-style "postgres://" scheme that some providers still emit.
    _database_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(basedir, "jobtracker.db"))
    if _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File uploads (resumes).
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(basedir, "uploads"))
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "doc", "docx", "rtf", "txt"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB max upload size

    # Session / cookie hardening.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
