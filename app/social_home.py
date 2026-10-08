"""Bounded, permission-filtered projections for the signed-in home feed."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select

from app.community import SharedJob, discover_profiles
from app.extensions import db
from app.gamification import application_stats, submitted_query
from app.models import Friendship, JobApplication, User
from app.services import ACTIVE_JOB_STATUSES

FEEDS = {"discover": "Discover", "friends": "Friends", "wins": "Career wins"}


def relationship_exists(viewer_id, *, accepted=False):
    condition = and_(
        or_(
            and_(
                Friendship.user_low_id == viewer_id,
                Friendship.user_high_id == User.id,
            ),
            and_(
                Friendship.user_high_id == viewer_id,
                Friendship.user_low_id == User.id,
            ),
        ),
    )
    query = select(Friendship.id).where(condition)
    if accepted:
        query = query.where(Friendship.status == "accepted")
    return query.exists()


@dataclass(frozen=True)
class FeedItem:
    handle: str
    display_name: str | None
    visibility: str
    job: SharedJob

    @property
    def name(self):
        return self.display_name or self.handle


def shared_feed(viewer_id, *, feed="discover", search="", page=1):
    friends = relationship_exists(viewer_id, accepted=True)
    audience = (
        friends
        if feed == "friends"
        else or_(User.profile_visibility == "public", friends)
    )
    people = select(User.id).where(
        User.id != viewer_id,
        User.handle.isnot(None),
        User.share_jobs.is_(True),
        audience,
    )
    # Select only the fields already allowed on shared profiles. Private notes,
    # contacts, attachments and private edit timestamps never enter this view.
    query = (
        submitted_query(people)
        .join(User, User.id == JobApplication.user_id)
        .with_entities(
            User.handle,
            User.display_name,
            User.profile_visibility,
            JobApplication.public_id,
            JobApplication.job_title,
            JobApplication.company,
            JobApplication.job_url,
            JobApplication.status,
            JobApplication.applied_on,
        )
    )
    if feed == "wins":
        query = query.filter(
            JobApplication.status.in_(("interviewing", "offer", "accepted"))
        )
    if search:
        pattern = (
            "%"
            + search.replace("/", "//").replace("%", "/%").replace("_", "/_")
            + "%"
        )
        query = query.filter(
            or_(
                JobApplication.job_title.ilike(pattern, escape="/"),
                JobApplication.company.ilike(pattern, escape="/"),
                User.handle.ilike(pattern, escape="/"),
                User.display_name.ilike(pattern, escape="/"),
            )
        )
    pagination = query.order_by(
        JobApplication.applied_on.desc().nullslast(),
        JobApplication.id.desc(),
    ).paginate(page=page, per_page=10, error_out=False)
    pagination.items = [
        FeedItem(*row[:3], job=SharedJob(*row[3:])) for row in pagination.items
    ]
    return pagination


def home_context(viewer):
    today = datetime.now(timezone.utc).date()
    jobs = JobApplication.for_user(viewer.id)
    due = jobs.filter(JobApplication.follow_up_on <= today)
    incoming = (
        db.session.query(Friendship, User)
        .join(User, User.id == Friendship.requested_by_id)
        .filter(
            or_(
                Friendship.user_low_id == viewer.id,
                Friendship.user_high_id == viewer.id,
            ),
            Friendship.status == "pending",
            Friendship.requested_by_id != viewer.id,
        )
        .order_by(Friendship.created_at.desc(), Friendship.id.desc())
    )
    return {
        "progress": application_stats([viewer.id])[viewer.id],
        "active_count": jobs.filter(
            JobApplication.status.in_(ACTIVE_JOB_STATUSES)
        ).count(),
        "due_count": due.count(),
        "due_jobs": due.order_by(
            JobApplication.follow_up_on, JobApplication.id
        )
        .limit(3)
        .all(),
        "incoming_count": incoming.count(),
        "requests": incoming.limit(3).all(),
        "suggestions": discover_profiles(viewer.id, "")
        .filter(~relationship_exists(viewer.id))
        .limit(3)
        .all(),
    }
