"""Transaction boundaries shared by application services."""

from contextlib import contextmanager

from app.extensions import db


@contextmanager
def database_transaction():
    """Commit once on success and roll back before propagating failures."""
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
