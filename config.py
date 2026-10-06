import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() == "true"


def normalize_database_url(url):
    scheme, separator, remainder = url.partition("://")
    if scheme in {"postgres", "postgresql"} and separator:
        return f"postgresql+psycopg2://{remainder}"
    return url


class Config:
    # Every worker must use the same private signing key.
    SECRET_KEY = os.environ.get("SECRET_KEY")
    DEBUG = env_bool("FLASK_DEBUG")

    # Normalize the legacy "postgres://" scheme used by some providers.
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.environ.get(
            "DATABASE_URL",
            "sqlite:///" + os.path.join(BASE_DIR, "jobtracker.db"),
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File uploads (resumes).
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads")
    )
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "doc", "docx", "rtf", "txt"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB max upload size

    # Session / cookie hardening.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # Use shared storage when running multiple processes (Redis in Compose).
    RATELIMIT_STORAGE_URI = os.environ.get(
        "RATELIMIT_STORAGE_URI", "memory://"
    )
    RATELIMIT_HEADERS_ENABLED = True
