"""User-scoped application queries and persistence."""

from sqlalchemy import or_

from app.database import database_transaction
from app.extensions import db
from app.models import JOB_STATUSES, JobApplication
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
)
ACTIVE_JOB_STATUSES = ("Applied", "Interviewing", "Offer")
RECENT_APPLICATION_LIMIT = 5
DEFAULT_SORT = "newest"
SORT_OPTIONS = {
    "newest": ("Newest first", JobApplication.applied_date.desc()),
    "oldest": ("Oldest first", JobApplication.applied_date.asc()),
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
        "recent": query.order_by(JobApplication.applied_date.desc())
        .limit(RECENT_APPLICATION_LIMIT)
        .all(),
    }


def list_applications(user_id, *, search="", status="", sort=DEFAULT_SORT):
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
    ordering = SORT_OPTIONS.get(sort, SORT_OPTIONS[DEFAULT_SORT])[1]
    return query.order_by(ordering).all()


def save_application(job, data, resume=None):
    """Persist details and retire files only after a successful commit."""
    old_resume = job.resume_filename
    new_resume = None
    try:
        with database_transaction():
            for field in JOB_FIELDS:
                setattr(job, field, data[field])
            if resume:
                new_resume = save_resume(resume)
                job.resume_filename = new_resume
            db.session.add(job)
    except Exception:
        delete_resume(new_resume)
        raise
    if new_resume:
        delete_resume(old_resume)


def delete_application(job):
    old_resume = job.resume_filename
    with database_transaction():
        db.session.delete(job)
    delete_resume(old_resume)
