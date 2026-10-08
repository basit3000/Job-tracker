"""Validate durable hosting configuration without exposing secret values."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from flask import current_app, request
from werkzeug.middleware.proxy_fix import ProxyFix


class DeploymentConfigurationError(ValueError):
    """An actionable startup message which never includes configured values."""


def configure_deployment(app):
    config = app.config
    if config["UPLOAD_STORAGE"] not in {"filesystem", "s3"}:
        raise DeploymentConfigurationError(
            "UPLOAD_STORAGE must be filesystem or s3."
        )
    if config["UPLOAD_STORAGE"] == "s3":
        _validate_s3(config)
    secret = config.get("CRON_SECRET")
    if secret and len(secret) < 32:
        raise DeploymentConfigurationError(
            "CRON_SECRET must contain at least 32 characters."
        )
    if config.get("PRODUCTION"):
        _validate_production(config)
    counts = (config["PROXY_FOR_COUNT"], config["PROXY_PROTO_COUNT"])
    if any(count < 0 for count in counts):
        raise DeploymentConfigurationError(
            "Proxy header counts must be nonnegative."
        )
    if any(counts):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=counts[0],
            x_proto=counts[1],
            x_host=0,
            x_port=0,
            x_prefix=0,
        )


def client_address():
    """Use the hosting ingress's client IP only on its managed platform."""
    if current_app.config["DEPLOYMENT_PLATFORM"] in {"vercel", "railway"}:
        try:
            return str(ip_address(request.headers.get("X-Real-IP", "")))
        except ValueError:
            pass
    return request.remote_addr or "127.0.0.1"


def _validate_s3(config):
    if not config.get("S3_BUCKET"):
        raise DeploymentConfigurationError(
            "Set S3_BUCKET for private resume storage."
        )
    if config["S3_ADDRESSING_STYLE"] not in {"virtual", "path", "auto"}:
        raise DeploymentConfigurationError(
            "S3_ADDRESSING_STYLE must be virtual, path or auto."
        )
    endpoint = config.get("S3_ENDPOINT_URL")
    if endpoint:
        url = urlsplit(endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise DeploymentConfigurationError(
                "S3_ENDPOINT_URL must be an HTTPS endpoint."
            )
    credentials = (
        config.get("S3_ACCESS_KEY_ID"),
        config.get("S3_SECRET_ACCESS_KEY"),
    )
    if any(credentials) and not all(credentials):
        raise DeploymentConfigurationError(
            "Set both S3 credential variables or use an IAM role."
        )


def _validate_production(config):
    if config.get("DEBUG") or config.get("ALLOW_INSECURE_LOCAL_API"):
        raise DeploymentConfigurationError(
            "Disable debug mode and insecure API access in production."
        )
    if not config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql"):
        raise DeploymentConfigurationError(
            "Set DATABASE_URL to a durable PostgreSQL database."
        )
    if not config["RATELIMIT_STORAGE_URI"].startswith(
        ("redis://", "rediss://")
    ):
        raise DeploymentConfigurationError(
            "Set RATELIMIT_STORAGE_URI to shared Redis storage."
        )
    if (
        not config["SESSION_COOKIE_SECURE"]
        or not config["REMEMBER_COOKIE_SECURE"]
    ):
        raise DeploymentConfigurationError(
            "Enable secure session and remember cookies in production."
        )
    url = urlsplit(config["APP_BASE_URL"])
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise DeploymentConfigurationError(
            "Set APP_BASE_URL to the public HTTPS origin."
        )
    if config["UPLOAD_STORAGE"] == "filesystem":
        if config["DEPLOYMENT_PLATFORM"] == "vercel":
            raise DeploymentConfigurationError(
                "Vercel requires UPLOAD_STORAGE=s3 for durable resumes."
            )
        if not config["UPLOAD_FOLDER_EXPLICIT"]:
            raise DeploymentConfigurationError(
                "Set UPLOAD_FOLDER to an attached persistent volume."
            )
