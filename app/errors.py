"""Consistent HTML responses for application errors."""

from flask import jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from app.contracts import ServiceError
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
    if request.path.startswith("/api/v1/"):
        return jsonify(
            error={"code": f"http_{code}", "message": error.name}
        ), code
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
    app.register_error_handler(ServiceError, render_service_error)
    app.register_error_handler(SQLAlchemyError, render_database_error)
    app.register_error_handler(HTTPException, render_http_error)


def render_service_error(error):
    db.session.rollback()
    if request.path.startswith("/api/v1/"):
        return jsonify(
            error={"code": error.code, "message": str(error)}
        ), error.status
    return render_template(
        "errors/error.html", code=error.status, message=str(error)
    ), error.status


def render_database_error(error):
    db.session.rollback()
    # Driver error details can contain entire private rows; never log them.
    if request.path.startswith("/api/v1/"):
        return jsonify(
            error={
                "code": "temporarily_unavailable",
                "message": "Database unavailable. Retry the same mutation ID.",
            }
        ), 503
    return render_template(
        "errors/error.html", code=500, message=ERROR_MESSAGES[500]
    ), 500


def render_http_error(error):
    if request.path.startswith("/api/v1/"):
        return jsonify(
            error={"code": f"http_{error.code}", "message": error.name}
        ), error.code
    return error.get_response()
