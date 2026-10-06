"""One serialized, version-aware write path for browser and device changes."""

from sqlalchemy import update

from app.contracts import (
    ServiceError,
    expected_version,
    iso,
    serialize_application,
)
from app.extensions import db
from app.models import (
    TERMINAL_STATUSES,
    ApplicationMapping,
    ChangeEntry,
    StatusEvent,
    User,
    _utcnow,
)


def lock_account(user_id):
    """Hold the account row until commit; SQLite serializes its writers too."""
    with db.session.no_autoflush:
        sequence = db.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(feed_sequence=User.feed_sequence)
            .returning(User.feed_sequence)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
    if sequence is None:
        raise ServiceError("unauthorized", "Account is unavailable.", 401)
    return sequence


def conflict(job):
    raise ServiceError(
        "version_conflict",
        "This application changed. "
        "Review the current version before retrying.",
        409,
        details=serialize_application(job),
    )


def check_version(job, version):
    expected_version(version)
    if job.id is not None:
        db.session.refresh(job)
    if job.deleted_at or job.version != version:
        conflict(job)


def attach_mapping(job, installation_id, local_record_id):
    if local_record_id is None:
        return False
    existing = ApplicationMapping.query.filter_by(
        user_id=job.user_id,
        installation_id=installation_id,
        local_record_id=local_record_id,
    ).first()
    if existing:
        if existing.application_id != job.id:
            raise ServiceError(
                "mapping_conflict",
                "Local record already maps to another application.",
                409,
            )
        return False
    other = ApplicationMapping.query.filter_by(
        application_id=job.id,
        installation_id=installation_id,
    ).first()
    if other:
        raise ServiceError(
            "mapping_conflict",
            "Application already has a mapping for this installation.",
            409,
        )
    db.session.add(
        ApplicationMapping(
            user_id=job.user_id,
            application_id=job.id,
            installation_id=installation_id,
            local_record_id=local_record_id,
        )
    )
    return True


def import_history(job, events, installation_id):
    changed = False
    for event in events:
        existing = StatusEvent.query.filter_by(
            user_id=job.user_id,
            installation_id=installation_id,
            source_event_id=event["source_event_id"],
        ).first()
        if existing:
            same = existing.application_id == job.id and all(
                iso(getattr(existing, key)) == iso(value)
                if key == "occurred_at"
                else getattr(existing, key) == value
                for key, value in event.items()
            )
            if not same:
                raise ServiceError(
                    "history_conflict",
                    "Source event was already used with different content.",
                    409,
                )
            continue
        db.session.add(
            StatusEvent(
                application_id=job.id,
                user_id=job.user_id,
                source="import",
                installation_id=installation_id,
                **event,
            )
        )
        changed = True
    return changed


def record_change(job, source, mutation_id=None):
    """Allocate a commit-ordered sequence while holding the account lock."""
    db.session.flush()
    db.session.expire(job, ["history", "mappings"])
    sequence = db.session.execute(
        update(User)
        .where(User.id == job.user_id)
        .values(feed_sequence=User.feed_sequence + 1)
        .returning(User.feed_sequence)
        .execution_options(synchronize_session=False)
    ).scalar_one()
    payload = serialize_application(job)
    if job.deleted_at:
        payload = {
            key: value
            for key, value in payload.items()
            if key in {"id", "version", "deletedAt", "updatedAt", "mappings"}
        }
    db.session.add(
        ChangeEntry(
            user_id=job.user_id,
            sequence=sequence,
            application_id=job.public_id,
            payload=payload,
            source=source,
            mutation_id=mutation_id,
        )
    )
    return payload


def write_application(
    job,
    values,
    *,
    version=None,
    source="browser",
    installation_id=None,
    local_record_id=None,
    history=(),
    mutation_id=None,
):
    """Caller holds the account lock and owns the transaction."""
    created = job.id is None
    if not created:
        check_version(job, version)
    previous_status = None if created else job.status
    changed = created or any(
        getattr(job, key) != value for key, value in values.items()
    )
    for key, value in values.items():
        setattr(job, key, value)
    job.status = job.status or "shortlisted"
    if job.status in TERMINAL_STATUSES:
        changed = changed or job.follow_up_on is not None
        job.follow_up_on = None
    if job.posted_at_approximate and job.posted_at is None:
        raise ServiceError(
            "validation_error",
            "An approximate posting time requires postedAt.",
            422,
        )
    if created:
        job.version = 1
        db.session.add(job)
        db.session.flush()
    mapped = attach_mapping(job, installation_id, local_record_id)
    imported = import_history(job, history, installation_id)
    if previous_status != job.status:
        db.session.add(
            StatusEvent(
                application_id=job.id,
                user_id=job.user_id,
                from_status=previous_status,
                status=job.status,
                source=source,
                installation_id=installation_id,
                occurred_at=_utcnow(),
            )
        )
    if not (changed or mapped or imported):
        return serialize_application(job)
    if not created:
        job.version += 1
    job.updated_date = _utcnow()
    return record_change(job, source, mutation_id)


def tombstone_application(job, version, *, source="browser", mutation_id=None):
    check_version(job, version)
    old_resume = job.resume_filename
    job.resume_filename = None
    job.deleted_at = _utcnow()
    job.updated_date = job.deleted_at
    job.follow_up_on = None
    job.version += 1
    return record_change(job, source, mutation_id), old_resume
