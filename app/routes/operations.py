"""Minimal readiness check and authenticated, bounded maintenance hooks."""

import hmac

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db, limiter

operations = Blueprint("operations", __name__)


@operations.get("/healthz")
@limiter.exempt
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(status="unavailable"), 503
    return jsonify(status="ok")


@operations.get("/internal/cron/<task>")
@limiter.exempt
def maintenance(task):
    secret = current_app.config.get("CRON_SECRET", "")
    supplied = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(
        supplied.encode(), f"Bearer {secret}".encode()
    ):
        return jsonify(error="unauthorized"), 401
    from app.import_service import cleanup_imports
    from app.notifications import run_due_reminders
    from app.source_scheduler import run_due_syncs

    tasks = {
        "cleanup": lambda: {"removed": cleanup_imports()},
        "sources": lambda: run_due_syncs(limit=1),
        "reminders": lambda: run_due_reminders(limit=10),
    }
    operation = tasks.get(task)
    if operation is None:
        return jsonify(error="not_found"), 404
    try:
        result = operation()
    except Exception:
        # Provider exceptions can contain private URLs and credentials.
        db.session.rollback()
        current_app.logger.warning("Scheduled maintenance could not complete.")
        return jsonify(error="unavailable"), 503
    return jsonify(result)
