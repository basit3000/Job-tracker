"""HTTP security policy and authentication request limits."""

import logging
import re
from copy import copy

from flask import current_app, request

AUTH_RATE_LIMIT = "10 per minute; 100 per hour"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    ),
}
GOOGLE_FORM_ENDPOINTS = frozenset(
    {
        "auth.login",
        "auth.register",
        "google_auth.account",
        "google_auth.start",
        "imports.index",
        "sources.create",
        "sources.index",
        "sources.read",
    }
)
UNSUBSCRIBE_PATH = re.compile(r"(/notifications/unsubscribe/)[^\s\"?\x1b]+")
REQUEST_QUERY = re.compile(r"(/[^\s\"?\x1b]*)\?[^\s\"\x1b]*")


def redact_request_url(value):
    """Keep query data and unsubscribe credentials out of access logs."""
    value = UNSUBSCRIBE_PATH.sub(r"\1[redacted]", value)
    return REQUEST_QUERY.sub(r"\1", value)


class PrivateRequestLogFilter(logging.Filter):
    """Redact Werkzeug messages and Gunicorn request/referrer atoms."""

    def filter(self, record):
        if isinstance(record.args, dict):
            # Preserve Gunicorn's safe fallback for absent custom log atoms.
            atoms = copy(record.args)
            for key in ("r", "U", "f"):
                if isinstance(atoms.get(key), str):
                    atoms[key] = redact_request_url(atoms[key])
            # A custom Gunicorn format can print the raw query separately.
            atoms["q"] = ""
            record.args = atoms
        message = record.getMessage()
        record.msg = redact_request_url(message)
        record.args = ()
        return True


def register_security_headers(app):
    for name in ("werkzeug", "gunicorn.access"):
        logger = logging.getLogger(name)
        if not any(
            isinstance(item, PrivateRequestLogFilter)
            for item in logger.filters
        ):
            logger.addFilter(PrivateRequestLogFilter())

    @app.after_request
    def security_headers(response):
        response.headers.update(SECURITY_HEADERS)
        if response.status_code == 200 and response.mimetype == "text/html":
            # HTTPS form posts need a same-origin Referer for Flask-WTF.
            # Keep it off external requests and non-page responses, including
            # OAuth callback redirects and private download redirects.
            response.headers["Referrer-Policy"] = "same-origin"
        if (
            current_app.config["GOOGLE_LOGIN_ENABLED"]
            and request.endpoint in GOOGLE_FORM_ENDPOINTS
        ):
            # Chromium also applies form-action to a POST's redirects.
            response.headers["Content-Security-Policy"] = SECURITY_HEADERS[
                "Content-Security-Policy"
            ].replace(
                "form-action 'self'",
                "form-action 'self' https://accounts.google.com",
            )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, private"
        return response
