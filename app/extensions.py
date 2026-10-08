import logging
from urllib.parse import urlsplit

from authlib.integrations.flask_client import OAuth
from flask_limiter import Limiter
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from app.deployment import client_address

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=client_address)


def init_google_oauth(app):
    """Keep OAuth clients isolated between application factory instances."""
    credentials = (
        app.config.get("GOOGLE_CLIENT_ID"),
        app.config.get("GOOGLE_CLIENT_SECRET"),
    )
    if any(credentials) and not all(credentials):
        raise ValueError("Set both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
    app.config["GOOGLE_LOGIN_ENABLED"] = all(credentials)
    registry = OAuth(app)
    if not all(credentials):
        return
    callback = urlsplit(app.config.get("GOOGLE_REDIRECT_URI") or "")
    local_http = callback.scheme == "http" and callback.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        not callback.hostname
        or callback.scheme != "https"
        and not local_http
        or callback.username
        or callback.password
        or callback.query
        or callback.fragment
        or callback.path != "/auth/google/callback"
    ):
        raise ValueError(
            "GOOGLE_REDIRECT_URI must be an HTTPS callback URL "
            "(HTTP is permitted only on loopback for development)."
        )
    registry.register(
        "google",
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid email",
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": "client_secret_post",
            "default_timeout": 10,
        },
    )
    # Authlib debug messages include tokens and PKCE verifiers.
    logging.getLogger("authlib.integrations.base_client.sync_app").setLevel(
        logging.WARNING
    )
