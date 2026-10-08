"""Opt-in reminders with durable, at-most-once daily sending attempts."""

import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from email_validator import EmailNotValidError, validate_email
from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database import database_transaction
from app.extensions import db
from app.gamification import submitted_query
from app.models import (
    NotificationPreference,
    ReminderDelivery,
    User,
    public_id,
)


def mail_ready():
    config = current_app.config
    if not config.get("EMAIL_REMINDERS_ENABLED") or not config.get(
        "SMTP_HOST"
    ):
        return False
    if config.get("SMTP_SECURITY") not in {"starttls", "ssl"}:
        return False
    if not 1 <= config.get("SMTP_PORT", 587) <= 65535:
        return False
    if bool(config.get("SMTP_USERNAME")) != bool(config.get("SMTP_PASSWORD")):
        return False
    try:
        validate_email(config.get("SMTP_FROM", ""), check_deliverability=False)
        base = urlsplit(config.get("APP_BASE_URL", ""))
        return bool(
            base.hostname
            and (
                base.scheme == "https"
                or (
                    base.scheme == "http"
                    and base.hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
            and not (
                base.username or base.password or base.query or base.fragment
            )
            and base.path in {"", "/"}
        )
    except (EmailNotValidError, ValueError):
        return False


def save_preferences(user_id, enabled, timezone_name, hour, **channels):
    from app.models import Notification
    from app.notification_center import CHANNEL_FIELDS

    with database_transaction():
        preference = db.session.get(NotificationPreference, user_id)
        if preference is None:
            preference = NotificationPreference(user_id=user_id)
            db.session.add(preference)
        if (enabled and not preference.email_enabled) or any(
            name.endswith("_email") and value and not getattr(preference, name)
            for name, value in channels.items()
            if name in CHANNEL_FIELDS
        ):
            preference.unsubscribe_key = public_id()
        preference.email_enabled = enabled
        preference.timezone_name = timezone_name
        preference.reminder_hour = hour
        for name in CHANNEL_FIELDS:
            if name in channels:
                setattr(preference, name, bool(channels[name]))
        # Opting out cancels queued mail permanently, even if re-enabled later.
        for kind in ("social", "followups", "sources"):
            if not getattr(preference, f"{kind}_email"):
                Notification.query.filter_by(
                    user_id=user_id, kind=kind, email_status="pending"
                ).update({"email_status": "skipped"})
    return preference


def disable_reminders(preference):
    from app.models import Notification

    with database_transaction():
        preference.email_enabled = False
        preference.social_email = False
        preference.followups_email = False
        preference.sources_email = False
        Notification.query.filter_by(
            user_id=preference.user_id, email_status="pending"
        ).update({"email_status": "skipped"})


def _signer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="application-reminders"
    )


def unsubscribe_token(preference):
    return _signer().dumps([preference.user_id, preference.unsubscribe_key])


def preference_from_token(token):
    try:
        user_id, key = _signer().loads(token, max_age=90 * 24 * 60 * 60)
    except (BadSignature, ValueError, TypeError):
        return None
    preference = db.session.get(NotificationPreference, user_id)
    return (
        preference
        if preference and preference.unsubscribe_key == key
        else None
    )


def send_reminder(preference, day):
    """Transport only; the scheduler owns consent, eligibility, and claims."""
    config = current_app.config
    base = config["APP_BASE_URL"].rstrip("/")
    user = db.session.get(User, preference.user_id)
    message = EmailMessage()
    message["Subject"] = "A little momentum for your job search"
    message["From"] = config["SMTP_FROM"]
    message["To"] = user.email
    message.set_content(
        f"You haven't recorded an application for {day} yet "
        f"({preference.timezone_name}).\n\n"
        "If today is a job-search day, one application is a good start. "
        "Already applied? Add it to your tracker. "
        "Taking a break is okay too.\n\n"
        f"Open Job Tracker: {base}/dashboard\n\n"
        "You received this because you enabled daily application reminders.\n"
        f"Manage reminders: {base}/notifications/settings\n"
        f"Unsubscribe: {base}/notifications/unsubscribe/"
        f"{unsubscribe_token(preference)}\n"
    )
    send_message(message)


def send_message(message):
    """Shared TLS-only SMTP transport for explicitly opted-in mail."""
    config = current_app.config
    context = ssl.create_default_context()
    kwargs = {
        "host": config["SMTP_HOST"],
        "port": config["SMTP_PORT"],
        "timeout": 20,
    }
    if config["SMTP_SECURITY"] == "ssl":
        client = smtplib.SMTP_SSL(**kwargs, context=context)
    else:
        client = smtplib.SMTP(**kwargs)
    with client:
        if config["SMTP_SECURITY"] == "starttls":
            client.starttls(context=context)
        if config.get("SMTP_USERNAME"):
            client.login(config["SMTP_USERNAME"], config["SMTP_PASSWORD"])
        client.send_message(message)


def _has_applied(user_id, day):
    return (
        submitted_query([user_id], day).filter_by(applied_on=day).first()
        is not None
    )


def _claim(user_id, day, zone):
    delivery = ReminderDelivery(
        user_id=user_id, local_date=day, timezone_name=zone
    )
    db.session.add(delivery)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None
    return delivery


def run_due_reminders(now=None, *, limit=None):
    result = {"sent": 0, "failed": 0, "skipped": 0}
    if not mail_ready():
        return result
    if limit is not None and limit < 1:
        raise ValueError("The reminder attempt limit must be positive.")
    if now is not None and now.tzinfo is None:
        raise ValueError("The reminder clock must be timezone aware.")
    ids = db.session.scalars(
        db.select(NotificationPreference.user_id).where(
            NotificationPreference.email_enabled.is_(True)
        )
    ).all()
    for user_id in ids:
        instant = now or datetime.now(timezone.utc)
        preference = db.session.get(
            NotificationPreference, user_id, populate_existing=True
        )
        local = instant.astimezone(ZoneInfo(preference.timezone_name))
        if (
            not preference.email_enabled
            or local.hour < preference.reminder_hour
        ):
            continue
        if ReminderDelivery.query.filter_by(
            user_id=user_id, local_date=local.date()
        ).first() or _has_applied(user_id, local.date()):
            continue
        delivery = _claim(user_id, local.date(), preference.timezone_name)
        if delivery is None:
            continue
        status = _deliver_claimed_reminder(preference, delivery, now)
        result[status] += 1
        if limit is not None and sum(result.values()) >= limit:
            break
    return result


def _deliver_claimed_reminder(preference, delivery, now):
    """Recheck consent after the durable claim, then record one attempt."""
    db.session.refresh(preference)
    local = (now or datetime.now(timezone.utc)).astimezone(
        ZoneInfo(preference.timezone_name)
    )
    with database_transaction():
        if (
            not preference.email_enabled
            or local.date() != delivery.local_date
            or preference.timezone_name != delivery.timezone_name
            or local.hour < preference.reminder_hour
            or _has_applied(preference.user_id, delivery.local_date)
        ):
            delivery.status = "skipped"
        else:
            _send_claimed_reminder(preference, delivery, now)
    return delivery.status


def _send_claimed_reminder(preference, delivery, now):
    try:
        send_reminder(preference, delivery.local_date)
    except (smtplib.SMTPException, OSError, ValueError):
        # SMTP failure can follow acceptance. Never retry an uncertain send.
        delivery.status = "failed"
        current_app.logger.warning("Application reminder transport failed.")
    else:
        delivery.status = "sent"
        delivery.sent_at = now or datetime.now(timezone.utc)


def watch_reminders(app):
    from app.notification_center import run_notification_cycle

    while True:
        with app.app_context():
            try:
                run_notification_cycle()
            except (SQLAlchemyError, ValueError, KeyError):
                db.session.rollback()
                app.logger.warning(
                    "Reminder worker could not complete this poll."
                )
            finally:
                db.session.remove()
        time.sleep(60)
