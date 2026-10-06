"""HTTP security policy and authentication request limits."""

import logging
import re

from flask import current_app, request

AUTH_RATE_LIMIT = "10 per minute; 100 per hour"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://fonts.googleapis.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
        "img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    ),
}


def redact_google_callback(value):
    return re.sub(r"(/auth/google/callback)\?[^\s\"\x1b]*", r"\1", value)


class GoogleCallbackLogFilter(logging.Filter):
    """Keep authorization codes/state out of default server access logs."""

    def filter(self, record):
        if isinstance(record.args, dict):
            atoms = dict(record.args)
            if "/auth/google/callback" in atoms.get("r", ""):
                atoms["r"] = redact_google_callback(atoms["r"])
                atoms["q"] = ""
                record.args = atoms
        message = record.getMessage()
        record.msg = redact_google_callback(message)
        record.args = ()
        return True


def register_security_headers(app):
    for name in ("werkzeug", "gunicorn.access"):
        logger = logging.getLogger(name)
        if not any(
            isinstance(item, GoogleCallbackLogFilter)
            for item in logger.filters
        ):
            logger.addFilter(GoogleCallbackLogFilter())

    @app.after_request
    def security_headers(response):
        response.headers.update(SECURITY_HEADERS)
        if current_app.config["GOOGLE_LOGIN_ENABLED"] and request.endpoint in {
            "auth.login",
            "auth.register",
            "google_auth.account",
            "google_auth.start",
            "imports.index",
            "sources.create",
            "sources.index",
            "sources.read",
        }:
            # Chromium also applies form-action to a POST's redirects.
            response.headers["Content-Security-Policy"] = SECURITY_HEADERS[
                "Content-Security-Policy"
            ].replace(
                "form-action 'self'",
                "form-action 'self' https://accounts.google.com",
            )
        if request.endpoint == "google_auth.callback":
            response.headers["Referrer-Policy"] = "no-referrer"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, private"
        return response
