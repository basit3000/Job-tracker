"""Bounded background polling; credentials and provider errors stay private."""

from sqlalchemy.exc import SQLAlchemyError

from app.contracts import ServiceError
from app.extensions import db
from app.import_service import commit_batch, options_digest
from app.models import ImportBatch, SourceConnection, _utcnow
from app.source_connections import (
    claim_due,
    connection_batch,
    record_sync_error,
)


def run_due_syncs(limit=20):
    due = (
        SourceConnection.query.filter(
            SourceConnection.active.is_(True),
            SourceConnection.interval_minutes > 0,
            SourceConnection.next_sync_at <= _utcnow(),
        )
        .order_by(SourceConnection.next_sync_at)
        .limit(limit)
        .all()
    )
    candidates = [(source.user_id, source.id) for source in due]
    outcomes = {"synced": 0, "failed": 0}
    for user_id, connection_id in candidates:
        connection, batch = None, None
        try:
            connection = claim_due(user_id, connection_id)
            if not connection:
                continue
            version = connection.version
            batch = connection_batch(connection)
            commit_batch(user_id, batch.id, options_digest(batch.options))
            outcomes["synced"] += 1
        except (ServiceError, SQLAlchemyError) as error:
            db.session.rollback()
            if connection:
                message = (
                    str(error)
                    if isinstance(error, ServiceError)
                    else "Sync could not be saved. Try again later."
                )
                record_sync_error(user_id, connection_id, version, message)
            outcomes["failed"] += 1
        finally:
            if batch:
                # Automated runs retain only the aggregate connection result.
                # They never leave source rows sitting in preview drafts.
                ImportBatch.query.filter_by(
                    id=batch.id, user_id=user_id
                ).delete(synchronize_session=False)
                db.session.commit()
    return outcomes


def watch_sources(app, *, stop=None, poll_seconds=30):
    """One polling worker; account locks arbitrate overlapping workers."""
    from threading import Event

    stop = stop or Event()
    while not stop.is_set():
        try:
            with app.app_context():
                run_due_syncs()
        except Exception:
            # This is the worker isolation boundary. Provider/driver exception
            # details may contain credentials or private data; never log them.
            app.logger.warning(
                "Source syncing is unavailable; retrying later."
            )
        stop.wait(poll_seconds)
