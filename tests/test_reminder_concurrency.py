"""Real database races must not produce duplicate reminder sends."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import MagicMock

from app.extensions import db
from app.models import ReminderDelivery, User
from app.notifications import run_due_reminders, save_preferences
from tests.test_concurrency import concurrent_app as concurrent_app
from tests.test_notifications import NOW


def test_two_workers_claim_one_daily_email(concurrent_app, monkeypatch):
    from app import notifications

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
    with app.app_context():
        user = User(email="reminder@example.com")
        user.set_password("fictional-password")
        db.session.add(user)
        db.session.commit()
        save_preferences(user.id, True, "UTC", 18)
    claim = notifications._claim
    barrier = Barrier(2)
    transport = MagicMock()

    def competing_claim(*args):
        barrier.wait(timeout=10)
        return claim(*args)

    monkeypatch.setattr(notifications, "_claim", competing_claim)
    monkeypatch.setattr(notifications, "send_reminder", transport)

    def run(_):
        with app.app_context():
            return run_due_reminders(NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(result["sent"] for result in results) == 1
    assert transport.call_count == 1
    with app.app_context():
        assert ReminderDelivery.query.count() == 1
        assert ReminderDelivery.query.one().status == "sent"
