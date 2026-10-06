"""HTTP security policy and authentication request limits."""

from flask import request

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


def register_security_headers(app):
    @app.after_request
    def security_headers(response):
        response.headers.update(SECURITY_HEADERS)
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, private"
        return response
