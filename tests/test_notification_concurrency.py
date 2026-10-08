"""Concurrent workers cannot duplicate emails or daily inbox events."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import MagicMock

from app.database import database_transaction
from app.extensions import db
from app.models import JobApplication, Notification, User
from app.notification_center import (
    add_notification,
    refresh_scheduled_notifications,
    send_pending_notifications,
)
from app.notifications import save_preferences
from tests.test_concurrency import concurrent_app as concurrent_app


def setup_user(app):
    with app.app_context():
        user = User(email="notifications@example.com")
        user.set_password("fictional-password")
        db.session.add(user)
        db.session.commit()
        return user.id


def test_two_workers_claim_one_email(concurrent_app, monkeypatch):
    from app import notification_center

    app = concurrent_app
    app.config.update(
        EMAIL_REMINDERS_ENABLED=True,
        SMTP_HOST="smtp.example.com",
        SMTP_SECURITY="starttls",
        SMTP_FROM="tracker@example.com",
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        APP_BASE_URL="https://tracker.example.com",
    )
    user_id = setup_user(app)
    with app.app_context():
        save_preferences(user_id, False, "UTC", 20, social_email=True)
        with database_transaction():
            add_notification(
                user_id, "social", "New friend request", "Visit People."
            )
    barrier = Barrier(2)
    claim = notification_center._claim_email
    transport = MagicMock()

    def competing_claim(notification_id):
        barrier.wait(timeout=10)
        return claim(notification_id)

    monkeypatch.setattr(notification_center, "_claim_email", competing_claim)
    monkeypatch.setattr(
        notification_center, "send_notification_email", transport
    )

    def run(_):
        with app.app_context():
            return send_pending_notifications()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(result["sent"] for result in results) == 1
    assert transport.call_count == 1


def test_two_workers_generate_one_daily_notification(concurrent_app):
    app = concurrent_app
    user_id = setup_user(app)
    now = datetime.now(timezone.utc)
    with app.app_context():
        db.session.add(
            JobApplication(
                user_id=user_id,
                job_title="Engineer",
                company="Example",
                follow_up_on=now.date(),
            )
        )
        db.session.commit()
    barrier = Barrier(2)

    def run(_):
        with app.app_context():
            barrier.wait(timeout=10)
            refresh_scheduled_notifications(user_id, now)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, range(2)))
    with app.app_context():
        assert Notification.query.count() == 1
