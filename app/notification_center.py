"""Private inbox operations and durable, opt-in email delivery."""

import smtplib
from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from flask import current_app, url_for
from sqlalchemy.exc import IntegrityError

from app.database import database_transaction
from app.extensions import db
from app.models import (
    JobApplication,
    Notification,
    NotificationPreference,
    User,
    public_id,
)
from app.notifications import (
    _has_applied,
    mail_ready,
    send_message,
    unsubscribe_token,
)
from app.record_updates import lock_account

CATEGORIES = {
    "social": ("People", "people", "community.index", {}),
    "followups": (
        "Follow-ups",
        "calendar-check",
        "jobs.follow_ups",
        {"due": "due"},
    ),
    "sources": ("Import & sync", "arrow-repeat", "imports.index", {}),
    "reminders": ("Daily reminder", "briefcase", "jobs.add_job", {}),
}
CHANNEL_FIELDS = tuple(
    f"{kind}_{channel}"
    for kind in ("social", "followups", "sources")
    for channel in ("in_app", "email")
) + ("reminders_in_app",)


def channel_enabled(preference, kind, channel):
    if kind == "reminders" and channel == "email":
        return bool(preference and preference.email_enabled)
    if preference is None:
        return channel == "in_app" and kind != "reminders"
    return bool(getattr(preference, f"{kind}_{channel}"))


def notification_url(notification):
    _, _, endpoint, values = CATEGORIES[notification.kind]
    return url_for(endpoint, **values)


def inbox_query(user_id):
    return Notification.query.filter_by(
        user_id=user_id, in_app=True, dismissed_at=None
    )


def unread_count(user_id):
    return inbox_query(user_id).filter_by(read_at=None).count()


def add_notification(
    user_id, kind, title, body, *, event_key=None, expires_at=None
):
    """Join the caller's transaction; never send email from a web request."""
    if kind not in CATEGORIES:
        raise ValueError("Unknown notification category.")
    preference = db.session.get(NotificationPreference, user_id)
    in_app = channel_enabled(preference, kind, "in_app")
    # Daily reminder email already has its own durable delivery ledger.
    email = kind != "reminders" and channel_enabled(preference, kind, "email")
    if not in_app and not email:
        return None
    notification = Notification(
        user_id=user_id,
        kind=kind,
        title=title[:120],
        body=body[:500],
        event_key=event_key or public_id(),
        in_app=in_app,
        email_status="pending" if email else "disabled",
        expires_at=expires_at,
    )
    # A savepoint keeps a duplicate event from rolling back its caller's work.
    try:
        with db.session.begin_nested():
            db.session.add(notification)
            db.session.flush()
    except IntegrityError:
        if (
            event_key
            and Notification.query.filter_by(
                user_id=user_id, event_key=event_key
            ).first()
        ):
            return None
        raise
    return notification


def refresh_scheduled_notifications(user_id, now=None):
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("The notification clock must be timezone aware.")
    with database_transaction():
        lock_account(user_id)
        preference = db.session.get(
            NotificationPreference, user_id, populate_existing=True
        )
        day = instant.astimezone(timezone.utc).date()
        end = datetime.combine(day + timedelta(days=1), time(), timezone.utc)
        if channel_enabled(
            preference, "followups", "in_app"
        ) or channel_enabled(preference, "followups", "email"):
            count = (
                JobApplication.for_user(user_id)
                .filter(JobApplication.follow_up_on <= day)
                .count()
            )
            if count:
                add_notification(
                    user_id,
                    "followups",
                    "Your follow-ups are ready",
                    f"You have {count} follow-up{'s' if count != 1 else ''} "
                    "due or overdue. Open your list to plan your next step.",
                    event_key=f"followups:{day}",
                    expires_at=end,
                )
        if channel_enabled(preference, "reminders", "in_app"):
            local = instant.astimezone(ZoneInfo(preference.timezone_name))
            if local.hour >= preference.reminder_hour and not _has_applied(
                user_id, local.date()
            ):
                add_notification(
                    user_id,
                    "reminders",
                    "A little momentum for your job search",
                    "No application recorded today. If today is a "
                    "job-search day, one application is a good start. "
                    "Taking a break is okay too.",
                    event_key=f"reminders:{local.date()}",
                )


def send_notification_email(notification, preference):
    """Send a minimal email without including private tracker or sync data."""
    base = current_app.config["APP_BASE_URL"].rstrip("/")
    user = db.session.get(User, notification.user_id)
    # url_for needs a request context when invoked from the worker.
    with current_app.test_request_context():
        destination = notification_url(notification)
    message = EmailMessage()
    message["Subject"] = f"Job Tracker: {notification.title}"
    message["From"] = current_app.config["SMTP_FROM"]
    message["To"] = user.email
    message.set_content(
        f"{notification.body}\n\nOpen Job Tracker: {base}{destination}\n\n"
        "You received this because you opted in to email notifications.\n"
        f"Manage notifications: {base}/notifications/settings\n"
        "Unsubscribe from all notification emails: "
        f"{base}/notifications/unsubscribe/{unsubscribe_token(preference)}\n"
    )
    send_message(message)


def _claim_email(notification_id):
    with database_transaction():
        changed = Notification.query.filter_by(
            id=notification_id, email_status="pending"
        ).update({"email_status": "claimed"}, synchronize_session=False)
    return bool(changed)


def send_pending_notifications(now=None, *, limit=100):
    """Commit a claim before SMTP; uncertain sends are never retried."""
    if limit < 1:
        raise ValueError("The notification attempt limit must be positive.")
    result = {"sent": 0, "failed": 0, "skipped": 0}
    if not mail_ready():
        return result
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("The notification clock must be timezone aware.")
    ids = db.session.scalars(
        db.select(Notification.id)
        .where(Notification.email_status == "pending")
        .order_by(Notification.created_at, Notification.id)
        .limit(limit)
    ).all()
    for notification_id in ids:
        if not _claim_email(notification_id):
            continue
        notification = db.session.get(
            Notification, notification_id, populate_existing=True
        )
        preference = db.session.get(
            NotificationPreference,
            notification.user_id,
            populate_existing=True,
        )
        expired = (
            notification.expires_at
            and notification.expires_at.replace(tzinfo=timezone.utc) <= instant
        )
        # Do not send an old backlog when an administrator enables SMTP later.
        stale = notification.created_at.replace(
            tzinfo=timezone.utc
        ) < instant - timedelta(days=1)
        with database_transaction():
            if (
                expired
                or stale
                or notification.dismissed_at
                or not channel_enabled(preference, notification.kind, "email")
            ):
                notification.email_status = "skipped"
            else:
                try:
                    send_notification_email(notification, preference)
                except (smtplib.SMTPException, OSError, ValueError):
                    notification.email_status = "failed"
                    current_app.logger.warning(
                        "Notification email transport failed."
                    )
                else:
                    notification.email_status = "sent"
                    notification.email_sent_at = instant
        result[notification.email_status] += 1
    return result


def run_notification_cycle(now=None):
    """Refresh scheduled inbox events in bounded pages, then drain email."""
    from app.notifications import run_due_reminders

    last_id = 0
    while True:
        ids = db.session.scalars(
            db.select(User.id)
            .where(User.id > last_id)
            .order_by(User.id)
            .limit(100)
        ).all()
        if not ids:
            break
        for user_id in ids:
            refresh_scheduled_notifications(user_id, now)
        last_id = ids[-1]
    return {
        "notifications": send_pending_notifications(now),
        "reminders": run_due_reminders(now, limit=100),
    }
