import os

from sqlalchemy.pool import NullPool

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() == "true"


def normalize_database_url(url):
    scheme, separator, remainder = url.partition("://")
    if scheme in {"postgres", "postgresql"} and separator:
        return f"postgresql+psycopg2://{remainder}"
    return url


class Config:
    DEPLOYMENT_PLATFORM = (
        "vercel"
        if os.environ.get("VERCEL") == "1"
        else "railway"
        if os.environ.get("RAILWAY_ENVIRONMENT_ID")
        else ""
    )
    PRODUCTION = (
        bool(DEPLOYMENT_PLATFORM) or os.environ.get("APP_ENV") == "production"
    )
    # Only enable for an ingress which overwrites these headers.
    PROXY_PROTO_COUNT = int(
        os.environ.get(
            "PROXY_PROTO_COUNT", "1" if DEPLOYMENT_PLATFORM else "0"
        )
    )
    PROXY_FOR_COUNT = int(os.environ.get("PROXY_FOR_COUNT", "0"))
    CRON_SECRET = os.environ.get("CRON_SECRET", "")
    # Every worker must use the same private signing key.
    SECRET_KEY = os.environ.get("SECRET_KEY")
    DEBUG = env_bool("FLASK_DEBUG")
    PUBLIC_SIGNUP_ENABLED = env_bool("PUBLIC_SIGNUP_ENABLED", default=True)
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    SYNC_ENCRYPTION_KEY = os.environ.get("SYNC_ENCRYPTION_KEY", "")
    GOOGLE_REDIRECT_URI = os.environ.get(
        "GOOGLE_REDIRECT_URI",
        os.environ.get("APP_BASE_URL", "http://localhost:5000").rstrip("/")
        + "/auth/google/callback",
    )
    ALLOW_INSECURE_LOCAL_API = env_bool("ALLOW_INSECURE_LOCAL_API")
    API_MAX_CONTENT_LENGTH = 128 * 1024
    API_PAGE_SIZE = 50
    EMAIL_REMINDERS_ENABLED = env_bool("EMAIL_REMINDERS_ENABLED")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls")
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "")
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

    # Normalize the legacy "postgres://" scheme used by some providers.
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.environ.get(
            "DATABASE_URL",
            "sqlite:///" + os.path.join(BASE_DIR, "jobtracker.db"),
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "hide_parameters": True,
        "pool_pre_ping": True,
    }
    if DEPLOYMENT_PLATFORM == "vercel":
        SQLALCHEMY_ENGINE_OPTIONS["poolclass"] = NullPool

    # File uploads (resumes).
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads")
    )
    UPLOAD_FOLDER_EXPLICIT = bool(os.environ.get("UPLOAD_FOLDER"))
    UPLOAD_STORAGE = os.environ.get("UPLOAD_STORAGE", "filesystem")
    S3_BUCKET = os.environ.get("S3_BUCKET", "")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None
    S3_REGION = os.environ.get("S3_REGION", "us-east-1")
    S3_ADDRESSING_STYLE = os.environ.get("S3_ADDRESSING_STYLE", "virtual")
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID") or None
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY") or None
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "doc", "docx", "rtf", "txt"}
    MAX_CONTENT_LENGTH = (
        (4 if DEPLOYMENT_PLATFORM == "vercel" else 5) * 1024 * 1024
    )

    # Session / cookie hardening.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", PRODUCTION)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # Use shared storage when running multiple processes (Redis in Compose).
    RATELIMIT_STORAGE_URI = os.environ.get(
        "RATELIMIT_STORAGE_URI", "memory://"
    )
    RATELIMIT_HEADERS_ENABLED = True
