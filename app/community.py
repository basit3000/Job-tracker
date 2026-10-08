"""Profile permissions, friendships, and explicitly shared job projections."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.contracts import ServiceError, validate_fields
from app.database import database_transaction
from app.extensions import db
from app.gamification import application_stats, submitted_query
from app.models import Friendship, JobApplication, User
from app.notification_center import add_notification
from app.record_updates import lock_account, write_application
from app.utils import is_http_url

PROFILE_FIELDS = (
    "handle",
    "display_name",
    "bio",
    "profile_visibility",
    "share_jobs",
    "daily_goal",
)


def friendship_query(user_id):
    return Friendship.query.filter(
        or_(
            Friendship.user_low_id == user_id,
            Friendship.user_high_id == user_id,
        )
    )


def relationship(user_id, other_id):
    low, high = sorted((user_id, other_id))
    return Friendship.query.filter_by(
        user_low_id=low, user_high_id=high
    ).first()


def can_view_profile(viewer_id, profile):
    if viewer_id == profile.id or profile.profile_visibility == "public":
        return True
    link = relationship(viewer_id, profile.id)
    return bool(link and link.status == "accepted")


def save_profile(user, values):
    try:
        with database_transaction():
            for name in PROFILE_FIELDS:
                setattr(user, name, values[name])
    except IntegrityError as error:
        raise ServiceError(
            "username_taken",
            "That username is already taken. Choose another.",
            409,
        ) from error


def request_friendship(actor, target):
    if actor.id == target.id:
        raise ServiceError(
            "invalid_friend", "You cannot add yourself as a friend.", 422
        )
    if not actor.handle:
        raise ServiceError(
            "profile_required",
            "Set up your profile before adding friends.",
            422,
        )
    low, high = sorted((actor.id, target.id))
    try:
        with database_transaction():
            if relationship(actor.id, target.id):
                raise ServiceError(
                    "friendship_exists",
                    "A friendship or request already exists.",
                    409,
                )
            db.session.add(
                Friendship(
                    user_low_id=low,
                    user_high_id=high,
                    requested_by_id=actor.id,
                )
            )
            add_notification(
                target.id,
                "social",
                "New friend request",
                f"{actor.profile_name} sent you a friend request. "
                "Visit People to accept or decline.",
            )
    except IntegrityError as error:
        raise ServiceError(
            "friendship_exists", "A friendship or request already exists.", 409
        ) from error


def change_friendship(user_id, friendship_id, action):
    query = friendship_query(user_id).filter_by(id=friendship_id)
    if action in {"accept", "decline"}:
        query = query.filter(
            Friendship.status == "pending",
            Friendship.requested_by_id != user_id,
        )
    elif action == "cancel":
        query = query.filter_by(status="pending", requested_by_id=user_id)
    elif action == "remove":
        query = query.filter_by(status="accepted")
    else:
        raise ServiceError("invalid_action", "Unknown friendship action.", 422)
    with database_transaction():
        link = query.first() if action == "accept" else None
        changed = (
            query.update({"status": "accepted"}, synchronize_session=False)
            if action == "accept"
            else query.delete(synchronize_session=False)
        )
        if not changed:
            raise ServiceError(
                "friendship_unavailable",
                "That request is no longer available.",
                404,
            )
        if action == "accept" and link:
            actor = db.session.get(User, user_id)
            add_notification(
                link.requested_by_id,
                "social",
                "Friend request accepted",
                f"{actor.profile_name} accepted your friend request. "
                "You can now follow each other's shared progress.",
            )


def friend_lists(user_id):
    links = (
        friendship_query(user_id).order_by(Friendship.created_at.desc()).all()
    )
    ids = {
        link.user_high_id if link.user_low_id == user_id else link.user_low_id
        for link in links
    }
    people = {
        user.id: user for user in User.query.filter(User.id.in_(ids)).all()
    }
    result = {"friends": [], "incoming": [], "outgoing": []}
    for link in links:
        other_id = (
            link.user_high_id
            if link.user_low_id == user_id
            else link.user_low_id
        )
        key = (
            "friends"
            if link.status == "accepted"
            else (
                "outgoing" if link.requested_by_id == user_id else "incoming"
            )
        )
        result[key].append({"link": link, "person": people[other_id]})
    return result


def comparison_rows(viewer, friends, metric):
    people = [viewer, *(item["person"] for item in friends)]
    stats = application_stats([person.id for person in people])
    rows = [{"person": person, "stats": stats[person.id]} for person in people]
    rows.sort(
        key=lambda row: (
            -row["stats"][metric],
            row["person"].profile_name.lower(),
        )
    )
    previous = None
    rank = 0
    for index, row in enumerate(rows, 1):
        value = row["stats"][metric]
        if value != previous:
            rank = index
        row["rank"] = rank
        previous = value
    return rows


def discover_profiles(viewer_id, search):
    query = User.query.filter(User.handle.isnot(None), User.id != viewer_id)
    if search:
        pattern = (
            "%"
            + search.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        query = query.filter(
            or_(
                User.handle == search.lower(),
                (User.profile_visibility == "public")
                & or_(
                    User.handle.ilike(pattern, escape="\\"),
                    User.display_name.ilike(pattern, escape="\\"),
                ),
            )
        )
    else:
        query = query.filter_by(profile_visibility="public")
    return query.order_by(User.handle)


@dataclass(frozen=True)
class SharedJob:
    public_id: str
    job_title: str
    company: str
    job_url: str | None
    status: str
    applied_on: date | None

    @property
    def safe_job_url(self):
        return self.job_url if is_http_url(self.job_url) else None


def shared_jobs(viewer_id, profile):
    if not can_view_profile(viewer_id, profile) or not profile.share_jobs:
        raise ServiceError(
            "private_applications", "These applications are private.", 404
        )
    return submitted_query([profile.id]).with_entities(
        JobApplication.public_id,
        JobApplication.job_title,
        JobApplication.company,
        JobApplication.job_url,
        JobApplication.status,
        JobApplication.applied_on,
    )


def shortlist_shared_job(viewer, profile, public_id):
    row = (
        shared_jobs(viewer.id, profile)
        .filter(JobApplication.public_id == public_id)
        .first()
    )
    if row is None:
        raise ServiceError(
            "application_unavailable",
            "That shared application is unavailable.",
            404,
        )
    if viewer.id == profile.id:
        raise ServiceError(
            "own_application", "This application is already yours.", 422
        )
    job = SharedJob(*row)
    values = validate_fields(
        {
            "title": job.job_title,
            "company": job.company,
            "url": job.safe_job_url,
            "status": "shortlisted",
        },
        create=True,
    )
    with database_transaction():
        # Serialize the duplicate check with tracker/API writes, too.
        lock_account(viewer.id)
        query = JobApplication.for_user(viewer.id)
        existing = (
            query.filter_by(job_url=job.safe_job_url).first()
            if job.safe_job_url
            else None
        )
        existing = (
            existing
            or query.filter_by(
                job_title=job.job_title, company=job.company
            ).first()
        )
        if existing:
            return existing, False
        saved = JobApplication(user_id=viewer.id)
        write_application(saved, values)
    return saved, True
