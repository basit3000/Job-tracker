"""Private inbox, consent, migrations and durable delivery."""

import smtplib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from flask_migrate import downgrade, upgrade

from app.community import change_friendship, request_friendship
from app.contracts import ServiceError
from app.database import database_transaction
from app.extensions import db
from app.models import (
    Friendship,
    JobApplication,
    Notification,
    NotificationPreference,
    SourceConnection,
    User,
)
from app.notification_center import (
    add_notification,
    refresh_scheduled_notifications,
    run_notification_cycle,
    send_notification_email,
    send_pending_notifications,
    unread_count,
)
from app.notifications import (
    disable_reminders,
    save_preferences,
    unsubscribe_token,
)
from app.source_connections import record_sync_error
from tests.helpers import MIGRATIONS, csrf_token


@pytest.fixture
def email_transport(app, monkeypatch):
    app.config.update(
        EMAIL_REMINDERS_ENABLED=True,
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=587,
        SMTP_SECURITY="starttls",
        SMTP_FROM="tracker@example.com",
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        APP_BASE_URL="https://tracker.example.com",
    )
    transport = MagicMock()
    monkeypatch.setattr(
        "app.notification_center.send_notification_email", transport
    )
    return transport


def seed_notification(user_id, **kwargs):
    with database_transaction():
        return add_notification(
            user_id,
            "social",
            "New friend request",
            "A friend requested to connect.",
            **kwargs,
        )


def test_inbox_default_is_private_and_email_is_opt_in(
    app, users, logged_client
):
    with app.app_context():
        own = seed_notification(users[0])
        other = seed_notification(users[1])
        own_id, other_id = own.id, other.id
        assert own.email_status == other.email_status == "disabled"
    response = logged_client.get("/notifications")
    assert response.status_code == 200
    assert own_id.encode() in response.data
    assert other_id.encode() not in response.data
    assert logged_client.get("/notifications/count").json == {"unread": 1}
    assert (
        "no-store"
        in logged_client.get("/notifications/count").headers["Cache-Control"]
    )
    token = csrf_token(logged_client, "/notifications")
    for action in ("read", "unread", "open", "dismiss"):
        assert (
            logged_client.post(
                f"/notifications/{other_id}/{action}",
                data={"csrf_token": token},
            ).status_code
            == 404
        )
        assert (
            logged_client.post(f"/notifications/{own_id}/{action}").status_code
            == 400
        )
    assert app.test_client().get("/notifications").status_code == 302
    assert app.test_client().get("/notifications/count").status_code == 302
    assert (
        logged_client.post(
            f"/notifications/{own_id}/read", data={"csrf_token": token}
        ).status_code
        == 302
    )
    assert logged_client.get("/notifications/count").json == {"unread": 0}
    assert (
        own_id.encode()
        not in logged_client.get("/notifications?filter=unread").data
    )
    logged_client.post(
        f"/notifications/{own_id}/unread", data={"csrf_token": token}
    )
    assert logged_client.get("/notifications/count").json == {"unread": 1}
    opened = logged_client.post(
        f"/notifications/{own_id}/open", data={"csrf_token": token}
    )
    assert opened.location == "/community"
    logged_client.post(
        f"/notifications/{own_id}/dismiss", data={"csrf_token": token}
    )
    assert own_id.encode() not in logged_client.get("/notifications").data
    with app.app_context():
        assert unread_count(users[1]) == 1


def test_pagination_mark_all_and_escaped_content(app, users, logged_client):
    with app.app_context():
        for _ in range(23):
            seed_notification(users[0])
        seed_notification(users[1])
        with database_transaction():
            add_notification(
                users[0],
                "social",
                "<script>bad()</script>",
                "<img src=x onerror=bad()>",
            )
    response = logged_client.get("/notifications")
    assert response.data.count(b'<article class="notification-card') == 20
    assert b"&lt;script&gt;bad()&lt;/script&gt;" in response.data
    assert b"<img src=x" not in response.data
    assert (
        logged_client.get("/notifications?page=2").data.count(
            b'<article class="notification-card'
        )
        == 4
    )
    assert logged_client.post("/notifications/read-all").status_code == 400
    logged_client.post(
        "/notifications/read-all",
        data={"csrf_token": csrf_token(logged_client, "/notifications")},
    )
    with app.app_context():
        assert unread_count(users[0]) == 0
        assert unread_count(users[1]) == 1


def test_social_events_notify_only_recipient_once(app, users):
    with app.app_context():
        actor, target = [db.session.get(User, id_) for id_ in users]
        actor.handle, target.handle = "actor", "target"
        db.session.commit()
        request_friendship(actor, target)
        request = Notification.query.one()
        assert request.user_id == target.id
        with pytest.raises(ServiceError):
            request_friendship(actor, target)
        assert Notification.query.count() == 1
        link_id = Friendship.query.one().id
        change_friendship(target.id, link_id, "accept")
        assert (
            Notification.query.filter_by(user_id=actor.id).one().title
            == "Friend request accepted"
        )
        with pytest.raises(ServiceError):
            change_friendship(target.id, link_id, "accept")
        assert Notification.query.count() == 2


def test_social_event_rolls_back_with_request(app, users, monkeypatch):
    def failure(*args, **kwargs):
        raise RuntimeError("notification failure")

    with app.app_context():
        actor, target = [db.session.get(User, id_) for id_ in users]
        actor.handle = "actor"
        db.session.commit()
        monkeypatch.setattr("app.community.add_notification", failure)
        with pytest.raises(RuntimeError):
            request_friendship(actor, target)
        assert Friendship.query.count() == 0


def test_channel_preferences_and_no_retroactive_email(
    app, users, email_transport
):
    with app.app_context():
        original = seed_notification(users[0])
        save_preferences(
            users[0], False, "UTC", 20, social_in_app=False, social_email=True
        )
        email_only = seed_notification(users[0])
        assert not email_only.in_app
        assert unread_count(users[0]) == 1
        assert send_pending_notifications()["sent"] == 1
        assert original.email_status == "disabled"
        assert email_transport.call_count == 1
        save_preferences(users[0], False, "UTC", 20, social_email=False)
        assert seed_notification(users[0]) is None


def test_followups_daily_deduplication_scope_and_reminder_timezone(app, users):
    now = datetime(2026, 10, 8, 19, tzinfo=timezone.utc)
    with app.app_context():
        save_preferences(
            users[0], False, "Europe/Berlin", 20, reminders_in_app=True
        )
        db.session.add_all(
            [
                JobApplication(
                    user_id=users[0],
                    job_title="Private job",
                    company="Private company",
                    follow_up_on=now.date(),
                ),
                JobApplication(
                    user_id=users[0],
                    job_title="Deleted",
                    company="Private",
                    follow_up_on=now.date(),
                    deleted_at=now,
                ),
                JobApplication(
                    user_id=users[1],
                    job_title="Other",
                    company="Private",
                    follow_up_on=now.date(),
                ),
            ]
        )
        db.session.commit()
        refresh_scheduled_notifications(users[0], now - timedelta(hours=2))
        assert Notification.query.count() == 1
        followup = Notification.query.one()
        assert "1 follow-up due" in followup.body
        assert "Private" not in followup.body
        refresh_scheduled_notifications(users[0], now)
        refresh_scheduled_notifications(users[0], now)
        assert Notification.query.count() == 2
        assert (
            Notification.query.filter_by(kind="reminders").one().email_status
            == "disabled"
        )
        assert unread_count(users[1]) == 0
        refresh_scheduled_notifications(users[0], now + timedelta(days=1))
        assert Notification.query.count() == 4


def test_sync_failure_notifies_once_per_failure_episode(app, users):
    with app.app_context():
        source = SourceConnection(
            user_id=users[0],
            provider="google_public",
            name="Private sheet name",
            reference={},
        )
        db.session.add(source)
        db.session.commit()
        record_sync_error(users[1], source.id, source.version, "private token")
        assert Notification.query.count() == 0
        record_sync_error(users[0], source.id, source.version, "private token")
        record_sync_error(
            users[0], source.id, source.version, "another private error"
        )
        assert Notification.query.count() == 1
        assert "private" not in Notification.query.one().body
        source.last_error = None
        db.session.commit()
        record_sync_error(users[0], source.id, source.version, "private token")
        assert Notification.query.count() == 2


def test_preferences_cancel_queued_email_and_unsubscribe_all(
    app, users, logged_client, email_transport
):
    with app.app_context():
        preference = save_preferences(
            users[0],
            True,
            "UTC",
            20,
            social_email=True,
            followups_email=True,
            sources_email=True,
        )
        token = unsubscribe_token(preference)
        seed_notification(users[0])
    path = f"/notifications/unsubscribe/{token}"
    assert b"Turn off all notification emails?" in logged_client.get(path).data
    assert logged_client.post(path).status_code == 400
    with app.app_context():
        assert db.session.get(NotificationPreference, users[0]).social_email
    result = logged_client.post(
        path, data={"csrf_token": csrf_token(logged_client, path)}
    )
    assert b"Email notifications turned off" in result.data
    with app.app_context():
        preference = db.session.get(NotificationPreference, users[0])
        assert not any(
            (
                preference.email_enabled,
                preference.social_email,
                preference.followups_email,
                preference.sources_email,
            )
        )
        assert preference.social_in_app
        assert Notification.query.one().email_status == "skipped"
        save_preferences(users[0], False, "UTC", 20, social_email=True)
        assert send_pending_notifications()["sent"] == 0
    assert logged_client.get(path).status_code == 404
    email_transport.assert_not_called()


@pytest.mark.parametrize(
    "mode", ["disabled", "expired", "old", "dismissed", "failure", "success"]
)
def test_email_delivery_claims_and_failures(app, users, email_transport, mode):
    now = datetime.now(timezone.utc)
    with app.app_context():
        preference = save_preferences(
            users[0], False, "UTC", 20, social_email=True
        )
        notification = seed_notification(users[0])
        if mode == "disabled":
            preference.social_email = False
        elif mode == "expired":
            notification.expires_at = now - timedelta(minutes=1)
        elif mode == "old":
            notification.created_at = now - timedelta(days=2)
        elif mode == "dismissed":
            notification.dismissed_at = now
        elif mode == "failure":
            email_transport.side_effect = smtplib.SMTPException(
                "private credentials"
            )
        db.session.commit()
        outcome = (
            "sent"
            if mode == "success"
            else "failed"
            if mode == "failure"
            else "skipped"
        )
        assert send_pending_notifications(now)[outcome] == 1
        assert notification.email_status == outcome
        assert sum(send_pending_notifications(now).values()) == 0
        assert email_transport.call_count == (
            1 if mode in {"success", "failure"} else 0
        )


def test_consent_rechecked_after_claim(
    app, users, email_transport, monkeypatch
):
    from app import notification_center

    claim = notification_center._claim_email
    with app.app_context():
        preference = save_preferences(
            users[0], False, "UTC", 20, social_email=True
        )
        seed_notification(users[0])

        def opt_out_after_claim(notification_id):
            result = claim(notification_id)
            disable_reminders(preference)
            return result

        monkeypatch.setattr(
            notification_center, "_claim_email", opt_out_after_claim
        )
        assert send_pending_notifications()["skipped"] == 1
        email_transport.assert_not_called()


def test_email_content_and_bounded_queue(
    app, users, email_transport, monkeypatch
):
    message_transport = MagicMock()
    monkeypatch.setattr(
        "app.notification_center.send_message", message_transport
    )
    with app.app_context():
        preference = save_preferences(
            users[0], False, "UTC", 20, social_email=True
        )
        notification = seed_notification(users[0])
        seed_notification(users[0])
        send_notification_email(notification, preference)
        message = message_transport.call_args.args[0]
        assert message["To"] == "owner@example.com"
        assert "https://tracker.example.com/community" in message.get_content()
        assert "/notifications/unsubscribe/" in message.get_content()
        assert send_pending_notifications(limit=1)["sent"] == 1
        assert send_pending_notifications(limit=1)["sent"] == 1
        assert send_pending_notifications(limit=1)["sent"] == 0


def test_worker_creates_in_app_events_without_smtp(app, users):
    with app.app_context():
        save_preferences(users[0], False, "UTC", 0, reminders_in_app=True)
        result = run_notification_cycle()
        assert result["notifications"]["sent"] == 0
        assert Notification.query.one().kind == "reminders"
    result = app.test_cli_runner().invoke(args=["process-notifications"])
    assert result.exit_code == 0


def test_migration_preserves_existing_consent(app, users):
    with app.app_context():
        save_preferences(users[0], True, "Europe/Berlin", 21)
        downgrade(directory=MIGRATIONS, revision="b24f08d93c71")
        upgrade(directory=MIGRATIONS)
        db.session.remove()
        preference = db.session.get(NotificationPreference, users[0])
        assert preference.email_enabled
        assert preference.timezone_name == "Europe/Berlin"
        assert preference.reminder_hour == 21
        assert preference.social_in_app and preference.followups_in_app
        assert not any(
            (
                preference.social_email,
                preference.followups_email,
                preference.sources_email,
            )
        )
