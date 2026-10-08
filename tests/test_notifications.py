"""Reminder consent, scheduling, delivery safety, and private preferences."""

import smtplib
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from flask_migrate import downgrade, upgrade

from app.extensions import db
from app.gamification import application_stats
from app.models import JobApplication, NotificationPreference, ReminderDelivery
from app.notifications import (
    mail_ready,
    run_due_reminders,
    save_preferences,
    send_reminder,
    unsubscribe_token,
)
from tests.helpers import MIGRATIONS, csrf_token

NOW = datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc)


@pytest.fixture
def mail(app, monkeypatch):
    app.config.update(
        EMAIL_REMINDERS_ENABLED=True,
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=587,
        SMTP_SECURITY="starttls",
        SMTP_FROM="tracker@example.com",
        SMTP_USERNAME="fictional-user",
        SMTP_PASSWORD="fictional-secret",
        APP_BASE_URL="https://tracker.example.com",
    )
    transport = MagicMock()
    monkeypatch.setattr("app.notifications.send_reminder", transport)
    return transport


def test_preferences_private_opt_in_and_validation(
    app, users, logged_client, client
):
    assert app.test_client().get("/notifications/settings").status_code == 302
    response = logged_client.get("/notifications/settings")
    assert response.status_code == 200
    assert b"Email delivery is not configured" in response.data
    token = csrf_token(logged_client, "/notifications/settings")
    data = {
        "email_enabled": "y",
        "timezone_name": "Europe/Berlin",
        "reminder_hour": "20",
    }
    assert (
        logged_client.post("/notifications/settings", data=data).status_code
        == 400
    )
    data["csrf_token"] = token
    for changes in (
        {"timezone_name": "Invalid/Zone"},
        {"reminder_hour": "24"},
    ):
        assert (
            logged_client.post(
                "/notifications/settings", data={**data, **changes}
            ).status_code
            == 422
        )
    assert (
        logged_client.post("/notifications/settings", data=data).status_code
        == 302
    )
    with app.app_context():
        preference = db.session.get(NotificationPreference, users[0])
        assert preference.email_enabled
        assert preference.timezone_name == "Europe/Berlin"
        assert db.session.get(NotificationPreference, users[1]) is None
        db.session.add(
            ReminderDelivery(
                user_id=users[1],
                local_date=date(2001, 1, 1),
                timezone_name="UTC",
            )
        )
        db.session.commit()
    assert (
        b"2001-01-01" not in logged_client.get("/notifications/settings").data
    )
    data.pop("email_enabled")
    assert (
        logged_client.post("/notifications/settings", data=data).status_code
        == 302
    )
    with app.app_context():
        assert not db.session.get(
            NotificationPreference, users[0]
        ).email_enabled


def test_due_time_opt_out_and_once_per_day(app, users, mail):
    with app.app_context():
        save_preferences(users[0], True, "Europe/Berlin", 20)
        save_preferences(users[1], False, "Europe/Berlin", 20)
        assert run_due_reminders(NOW - timedelta(hours=2))["sent"] == 0
        assert run_due_reminders(NOW)["sent"] == 1
        assert run_due_reminders(NOW)["sent"] == 0
        assert mail.call_count == 1
        assert ReminderDelivery.query.one().status == "sent"
        assert run_due_reminders(NOW + timedelta(days=1))["sent"] == 1


def test_bounded_reminders_continue_with_remaining_users(app, users, mail):
    with app.app_context():
        for user_id in users:
            save_preferences(user_id, True, "UTC", 18)
        assert run_due_reminders(NOW, limit=1)["sent"] == 1
        assert run_due_reminders(NOW, limit=1)["sent"] == 1
        assert run_due_reminders(NOW, limit=1)["sent"] == 0
        assert mail.call_count == 2
        with pytest.raises(ValueError, match="positive"):
            run_due_reminders(NOW, limit=0)


@pytest.mark.parametrize(
    "status,day,deleted,sends",
    [
        ("applied", date(2026, 10, 7), False, False),
        ("interviewing", date(2026, 10, 7), False, False),
        ("closed", date(2026, 10, 7), False, False),
        ("applied", None, False, True),
        ("shortlisted", date(2026, 10, 7), False, True),
        ("skipped", date(2026, 10, 7), False, True),
        ("applied", date(2026, 10, 8), False, True),
        ("applied", date(2026, 10, 7), True, True),
    ],
)
def test_only_real_applications_suppress_reminder(
    app, users, mail, status, day, deleted, sends
):
    with app.app_context():
        save_preferences(users[0], True, "UTC", 18)
        db.session.add(
            JobApplication(
                user_id=users[0],
                company="Example",
                job_title="Engineer",
                status=status,
                applied_on=day,
                deleted_at=NOW if deleted else None,
            )
        )
        db.session.commit()
        assert run_due_reminders(NOW)["sent"] == int(sends)
        assert mail.call_count == int(sends)


def test_local_date_and_daylight_saving(app, users, mail):
    with app.app_context():
        save_preferences(users[0], True, "Asia/Tokyo", 0)
        run_due_reminders(NOW)
        assert ReminderDelivery.query.one().local_date == date(2026, 10, 8)
        preference = save_preferences(users[0], True, "Europe/Berlin", 2)
        first = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
        assert run_due_reminders(first)["sent"] == 1
        assert run_due_reminders(first + timedelta(hours=1))["sent"] == 0
        assert preference.email_enabled
        spring = datetime(2026, 3, 29, 1, 5, tzinfo=timezone.utc)
        assert run_due_reminders(spring)["sent"] == 1


def test_failures_and_crashed_claims_are_not_retried(app, users, mail):
    mail.side_effect = smtplib.SMTPServerDisconnected("fictional SMTP error")
    with app.app_context():
        save_preferences(users[0], True, "UTC", 18)
        assert run_due_reminders(NOW)["failed"] == 1
        assert run_due_reminders(NOW)["failed"] == 0
        assert mail.call_count == 1
        assert ReminderDelivery.query.one().status == "failed"
        db.session.add(
            ReminderDelivery(
                user_id=users[0],
                local_date=NOW.date() + timedelta(days=1),
                timezone_name="UTC",
            )
        )
        db.session.commit()
        assert run_due_reminders(NOW + timedelta(days=1))["sent"] == 0
        assert mail.call_count == 1


def test_consent_and_activity_rechecked_after_claim(
    app, users, mail, monkeypatch
):
    from app import notifications

    original = notifications._claim

    def changed_consent(*args):
        delivery = original(*args)
        save_preferences(users[0], False, "UTC", 18)
        return delivery

    monkeypatch.setattr(notifications, "_claim", changed_consent)
    with app.app_context():
        save_preferences(users[0], True, "UTC", 18)
        assert run_due_reminders(NOW)["skipped"] == 1
        mail.assert_not_called()


def test_unsubscribe_requires_signed_link_and_post(app, users, mail, client):
    with app.app_context():
        preference = save_preferences(users[0], True, "UTC", 18)
        token = unsubscribe_token(preference)
    path = f"/notifications/unsubscribe/{token}"
    assert client.get(path + "bad").status_code == 404
    assert client.get(path).status_code == 200
    with app.app_context():
        assert db.session.get(NotificationPreference, users[0]).email_enabled
    assert client.post(path).status_code == 400
    assert (
        client.post(
            path, data={"csrf_token": csrf_token(client, path)}
        ).status_code
        == 200
    )
    with app.app_context():
        assert run_due_reminders(NOW)["sent"] == 0
        save_preferences(users[0], True, "UTC", 18)
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("security", ["starttls", "ssl"])
def test_smtp_uses_tls_and_contains_unsubscribe(
    app, users, mail, monkeypatch, security
):
    smtp = MagicMock()
    monkeypatch.setattr(
        "app.notifications.smtplib."
        + ("SMTP_SSL" if security == "ssl" else "SMTP"),
        smtp,
    )
    app.config["SMTP_SECURITY"] = security
    with app.app_context():
        preference = save_preferences(users[0], True, "UTC", 18)
        send_reminder(preference, NOW.date())
    client = smtp.return_value
    assert client.starttls.call_count == int(security == "starttls")
    client.login.assert_called_once_with("fictional-user", "fictional-secret")
    message = client.send_message.call_args.args[0]
    assert message["To"] == "owner@example.com"
    assert "/notifications/unsubscribe/" in message.get_content()
    assert "fictional-secret" not in message.as_string()
    assert smtp.call_args.kwargs["timeout"] == 20


def test_delivery_disabled_without_complete_secure_configuration(
    app, users, mail
):
    with app.app_context():
        save_preferences(users[0], True, "UTC", 18)
        assert mail_ready()
        for setting, bad in [
            ("EMAIL_REMINDERS_ENABLED", False),
            ("SMTP_SECURITY", "none"),
            ("SMTP_FROM", "bad"),
            ("SMTP_PASSWORD", ""),
            ("APP_BASE_URL", "http://public.example.com"),
        ]:
            original = app.config[setting]
            app.config[setting] = bad
            assert not mail_ready()
            assert run_due_reminders(NOW)["sent"] == 0
            app.config[setting] = original
        assert ReminderDelivery.query.count() == 0
    mail.assert_not_called()


def test_chart_dates_streak_and_zero_filled_days(app, users):
    with app.app_context():
        for offset in (0, 0, 1, 2, 8):
            db.session.add(
                JobApplication(
                    user_id=users[0],
                    company="Example",
                    job_title="Engineer",
                    status="applied",
                    applied_on=NOW.date() - timedelta(days=offset),
                )
            )
        db.session.add(
            JobApplication(
                user_id=users[1],
                company="Other",
                job_title="Private",
                status="applied",
                applied_on=NOW.date(),
            )
        )
        db.session.commit()
        progress = application_stats([users[0]], today=NOW.date())[users[0]]
        assert len(progress["chart_days"]) == 28
        assert progress["chart_days"][-1]["count"] == 2
        assert progress["chart_days"][0]["count"] == 0
        assert progress["chart_total"] == 5
        assert progress["active_days"] == 4
        assert progress["streak"] == progress["best_streak"] == 3
        assert progress["week_change"] == 3
        assert len(progress["calendar_weeks"]) == 12
        assert progress["calendar_weeks"][0][0]["day"].weekday() == 0


def test_notification_migration_roundtrip_preserves_jobs(app, users, job):
    with app.app_context():
        downgrade(directory=MIGRATIONS, revision="a93e7d4b620f")
        upgrade(directory=MIGRATIONS)
        assert db.session.get(JobApplication, job).user_id == users[0]
        assert NotificationPreference.query.count() == 0
        assert ReminderDelivery.query.count() == 0
