"""Consistent HTML responses for application errors."""

from flask import render_template
from flask_wtf.csrf import CSRFError

from app.extensions import db
from app.uploads import upload_size_label

ERROR_MESSAGES = {
    400: (
        "The form expired or its security token is missing. "
        "Reload the page and try again."
    ),
    403: "You don't have access to that page.",
    404: "That page could not be found.",
    429: "Too many attempts. Please wait before trying again.",
    500: "Something went wrong on our end.",
}


def render_error(error):
    code = error.code
    if code == 500:
        db.session.rollback()
    message = (
        f"That file is too large (max {upload_size_label()})."
        if code == 413
        else ERROR_MESSAGES[code]
    )
    return render_template(
        "errors/error.html", code=code, message=message
    ), code


def register_error_handlers(app):
    app.register_error_handler(CSRFError, render_error)
    for code in (403, 404, 413, 429, 500):
        app.register_error_handler(code, render_error)
