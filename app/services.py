"""User-scoped application queries and persistence."""

from datetime import datetime, timezone

from sqlalchemy import or_

from app.contracts import FIELD_SPECS, iso, validate_fields
from app.database import database_transaction
from app.extensions import db
from app.models import JOB_STATUSES, JobApplication
from app.record_updates import (
    lock_account,
    tombstone_application,
    write_application,
)
from app.uploads import delete_resume, save_resume

JOB_FIELDS = (
    "job_title",
    "company",
    "location",
    "salary",
    "job_url",
    "contact_person",
    "status",
    "notes",
    "board",
    "contact_email",
    "contact_phone",
    "applied_on",
    "follow_up_on",
)
ACTIVE_JOB_STATUSES = ("applied", "interviewing", "offer")
RECENT_APPLICATION_LIMIT = 5
DEFAULT_SORT = "newest"
SORT_OPTIONS = {
    "newest": ("Newest first", JobApplication.created_at.desc()),
    "oldest": ("Oldest first", JobApplication.created_at.asc()),
    "company": ("Company A–Z", JobApplication.company.asc()),
    "title": ("Job title A–Z", JobApplication.job_title.asc()),
}


def dashboard_summary(user_id):
    """Count applications in SQL and load only the displayed recent rows."""
    query = JobApplication.for_user(user_id)
    counts = dict.fromkeys(JOB_STATUSES, 0)
    counts.update(
        query.with_entities(
            JobApplication.status, db.func.count(JobApplication.id)
        )
        .group_by(JobApplication.status)
        .all()
    )
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "active": sum(counts.get(status, 0) for status in ACTIVE_JOB_STATUSES),
        "recent": query.order_by(
            JobApplication.created_at.desc(), JobApplication.id.desc()
        )
        .limit(RECENT_APPLICATION_LIMIT)
        .all(),
        "by_date": query.with_entities(
            JobApplication.applied_on, db.func.count(JobApplication.id)
        )
        .filter(JobApplication.applied_on.isnot(None))
        .group_by(JobApplication.applied_on)
        .order_by(JobApplication.applied_on.desc())
        .limit(30)
        .all(),
        "unknown_dates": query.filter(
            JobApplication.applied_on.is_(None)
        ).count(),
        "overdue": follow_up_query(user_id, "overdue").limit(10).all(),
        "upcoming": follow_up_query(user_id, "upcoming").limit(10).all(),
    }


def application_query(
    user_id,
    *,
    search="",
    status="",
    sort=DEFAULT_SORT,
    company="",
    board="",
    due="",
):
    query = JobApplication.for_user(user_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                JobApplication.company.ilike(pattern),
                JobApplication.job_title.ilike(pattern),
                JobApplication.location.ilike(pattern),
                JobApplication.contact_person.ilike(pattern),
            )
        )
    if status in JOB_STATUSES:
        query = query.filter_by(status=status)
    if company:
        query = query.filter_by(company=company)
    if board:
        query = query.filter_by(board=board)
    if due in {"overdue", "today", "upcoming"}:
        query = filter_follow_ups(query, due)
    ordering = SORT_OPTIONS.get(sort, SORT_OPTIONS[DEFAULT_SORT])[1]
    return query.order_by(ordering, JobApplication.id.desc())


def list_applications(user_id, **filters):
    return application_query(user_id, **filters).all()


def application_filter_choices(user_id):
    """Build filter menus using only the account's active applications."""
    query = JobApplication.for_user(user_id)
    return {
        name: [
            row[0]
            for row in query.with_entities(column)
            .filter(column.isnot(None))
            .distinct()
            .order_by(column)
        ]
        for name, column in (
            ("companies", JobApplication.company),
            ("boards", JobApplication.board),
        )
    }


def filter_follow_ups(query, due):
    today = datetime.now(timezone.utc).date()
    if due == "overdue":
        return query.filter(JobApplication.follow_up_on < today)
    if due == "today":
        return query.filter(JobApplication.follow_up_on == today)
    return query.filter(JobApplication.follow_up_on >= today)


def follow_up_query(user_id, due):
    return filter_follow_ups(JobApplication.for_user(user_id), due).order_by(
        JobApplication.follow_up_on, JobApplication.id
    )


def save_application(job, data, resume=None, *, version=None):
    """Persist details and retire files only after a successful commit."""
    fields = {
        name: iso(data[attr]) if kind == "date" else data[attr]
        for name, (attr, kind, _) in FIELD_SPECS.items()
        if attr in data
    }
    values = validate_fields(fields, create=job.id is None)
    old_resume = None
    new_resume = None
    try:
        with database_transaction():
            lock_account(job.user_id)
            if job.id is not None:
                db.session.refresh(job)
            old_resume = job.resume_filename
            if resume:
                new_resume = save_resume(resume)
                values["resume_filename"] = new_resume
            write_application(job, values, version=version)
    except Exception:
        delete_resume(new_resume)
        raise
    if new_resume:
        delete_resume(old_resume)


def delete_application(job, *, version):
    with database_transaction():
        lock_account(job.user_id)
        _, old_resume = tombstone_application(job, version)
    delete_resume(old_resume)
