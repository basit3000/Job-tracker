"""Consent, privacy boundaries, activity counts, and tracker integration."""

from datetime import date, datetime, timedelta, timezone

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app.community import comparison_rows, friend_lists
from app.extensions import db
from app.gamification import application_stats
from app.models import ChangeEntry, Friendship, JobApplication, User
from app.services import save_application
from tests.helpers import MIGRATIONS, csrf_token, job_data


def login_as(app, user_id):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    return client


@pytest.fixture
def community_people(app, users):
    with app.app_context():
        owner = db.session.get(User, users[0])
        owner.handle = "alice"
        owner.display_name = "Alice Example"
        other = db.session.get(User, users[1])
        other.handle = "bob"
        other.display_name = "Bob Example"
        other.bio = "Private fictional biography"
        other.share_jobs = True
        third = User(email="stranger@example.com", handle="carol")
        third.set_password("fictional-password")
        db.session.add(third)
        db.session.commit()
        return (*users, third.id)


def send_request(client, handle="bob"):
    token = csrf_token(client, "/community")
    return client.post(
        f"/community/u/{handle}/request", data={"csrf_token": token}
    )


def act(client, link_id, action):
    token = csrf_token(client, "/community")
    return client.post(
        f"/community/friendships/{link_id}/{action}",
        data={"csrf_token": token},
    )


def connect_friends(app, owner_client, people):
    assert send_request(owner_client).status_code == 302
    with app.app_context():
        link_id = Friendship.query.one().id
    recipient = login_as(app, people[1])
    assert act(recipient, link_id, "accept").status_code == 302
    return link_id


def shared_record(app, user_id, **overrides):
    with app.app_context():
        item = JobApplication(user_id=user_id)
        save_application(
            item,
            {
                "job_title": "Shared developer role",
                "company": "Shared Example Labs",
                "status": "applied",
                "job_url": "https://example.com/jobs/fictional",
                "applied_on": datetime.now(timezone.utc).date(),
                "notes": "PRIVATE_NOTE_SENTINEL",
                "salary": "PRIVATE_SALARY_SENTINEL",
                "contact_person": "PRIVATE_CONTACT_SENTINEL",
                "contact_email": "private-contact@example.com",
                "contact_phone": "+49-private-phone",
                **overrides,
            },
        )
        item.resume_filename = "PRIVATE_RESUME_SENTINEL.pdf"
        db.session.commit()
        return item.id, item.public_id


@pytest.mark.parametrize(
    "path", ["/community", "/community/settings", "/community/u/bob"]
)
def test_community_requires_login(client, community_people, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.location


def test_profile_defaults_and_settings_validation(app, users, logged_client):
    with app.app_context():
        person = db.session.get(User, users[0])
        assert person.handle is None
        assert person.profile_visibility == "private"
        assert person.share_jobs is False
        assert person.daily_goal == 5
    token = csrf_token(logged_client, "/community/settings")
    data = {
        "csrf_token": token,
        "handle": "  ALICE_DEV  ",
        "daily_goal": 7,
        "profile_visibility": "private",
    }
    assert (
        logged_client.post("/community/settings", data=data).status_code == 302
    )
    with app.app_context():
        assert db.session.get(User, users[0]).handle == "alice_dev"
    for changes in (
        {"handle": "a"},
        {"handle": "a/bad"},
        {"daily_goal": 0},
        {"daily_goal": 101},
        {"profile_visibility": "invalid"},
    ):
        assert (
            logged_client.post(
                "/community/settings", data={**data, **changes}
            ).status_code
            == 422
        )
    with app.app_context():
        assert db.session.get(User, users[0]).daily_goal == 7
    assert (
        logged_client.post(
            "/community/settings", data=data | {"csrf_token": ""}
        ).status_code
        == 400
    )


def test_username_conflict_preserves_profile(
    app, logged_client, community_people
):
    token = csrf_token(logged_client, "/community/settings")
    response = logged_client.post(
        "/community/settings",
        data={
            "csrf_token": token,
            "handle": "BOB",
            "daily_goal": 9,
            "profile_visibility": "public",
            "share_jobs": "y",
        },
    )
    assert response.status_code == 409
    assert b"already taken" in response.data
    with app.app_context():
        owner = db.session.get(User, community_people[0])
        assert owner.handle == "alice" and owner.daily_goal == 5
        assert owner.profile_visibility == "private" and not owner.share_jobs


def test_private_discovery_does_not_search_email_or_partial_handle(
    logged_client, community_people
):
    assert b"Bob Example" not in logged_client.get("/community").data
    assert b"Bob Example" not in logged_client.get("/community?q=bo").data
    assert (
        b"Bob Example"
        not in logged_client.get("/community?q=other@example.com").data
    )
    assert b"Bob Example" in logged_client.get("/community?q=BOB").data
    page = logged_client.get("/community/u/bob")
    assert b"A private profile" in page.data
    assert b"Private fictional biography" not in page.data
    assert b"Personal best" not in page.data


def test_friend_request_consent_and_removal_revoke_access(
    app, logged_client, community_people
):
    shared_record(app, community_people[1])
    assert send_request(logged_client).status_code == 302
    with app.app_context():
        link_id = Friendship.query.one().id
    assert (
        b"Shared Example Labs"
        not in logged_client.get("/community/u/bob").data
    )
    assert act(logged_client, link_id, "accept").status_code == 404
    stranger = login_as(app, community_people[2])
    assert act(stranger, link_id, "accept").status_code == 404
    recipient = login_as(app, community_people[1])
    assert act(recipient, link_id, "cancel").status_code == 404
    assert act(recipient, link_id, "accept").status_code == 302
    assert b"Shared Example Labs" in logged_client.get("/community/u/bob").data
    assert b"Bob Example" in logged_client.get("/community").data
    assert act(stranger, link_id, "remove").status_code == 404
    assert act(logged_client, link_id, "remove").status_code == 302
    assert (
        b"Shared Example Labs"
        not in logged_client.get("/community/u/bob").data
    )
    with app.app_context():
        assert Friendship.query.count() == 0


@pytest.mark.parametrize(
    "action,recipient", [("cancel", False), ("decline", True)]
)
def test_pending_requests_can_be_cancelled_or_declined(
    app, logged_client, community_people, action, recipient
):
    assert send_request(logged_client).status_code == 302
    with app.app_context():
        link_id = Friendship.query.one().id
    client = login_as(app, community_people[1]) if recipient else logged_client
    assert act(client, link_id, action).status_code == 302
    with app.app_context():
        assert Friendship.query.count() == 0
    assert send_request(logged_client).status_code == 302


def test_duplicate_reverse_and_self_requests_are_rejected(
    app, logged_client, community_people
):
    assert send_request(logged_client, "alice").status_code == 422
    assert send_request(logged_client).status_code == 302
    assert send_request(logged_client).status_code == 409
    recipient = login_as(app, community_people[1])
    assert send_request(recipient, "alice").status_code == 409
    with app.app_context():
        assert Friendship.query.count() == 1
        assert Friendship.query.one().status == "pending"
    assert (
        logged_client.post("/community/u/bob/request", data={}).status_code
        == 400
    )


def test_shared_projection_never_exposes_private_details_or_owner_routes(
    app, logged_client, community_people
):
    job_id, _ = shared_record(app, community_people[1])
    connect_friends(app, logged_client, community_people)
    response = logged_client.get("/community/u/bob")
    assert response.status_code == 200
    assert b"Shared developer role" in response.data
    assert b"https://example.com/jobs/fictional" in response.data
    for private in (
        b"PRIVATE_",
        b"other@example.com",
        b"private-contact@example.com",
        b"+49-private-phone",
        b"resume_filename",
        b"password_hash",
    ):
        assert private not in response.data
    for path in (
        f"/jobs/{job_id}",
        f"/jobs/{job_id}/edit",
        f"/jobs/{job_id}/resume",
    ):
        assert logged_client.get(path).status_code == 404
    token = csrf_token(logged_client, "/community")
    assert (
        logged_client.post(
            f"/jobs/{job_id}/delete", data={"csrf_token": token, "version": 1}
        ).status_code
        == 404
    )


def test_public_and_job_sharing_switches_take_effect_immediately(
    app, logged_client, community_people
):
    _, public_id = shared_record(app, community_people[1])
    recipient = login_as(app, community_people[1])
    token = csrf_token(recipient, "/community/settings")
    data = {
        "csrf_token": token,
        "handle": "bob",
        "daily_goal": 5,
        "profile_visibility": "public",
        "share_jobs": "y",
    }
    assert recipient.post("/community/settings", data=data).status_code == 302
    assert b"Bob Example" in logged_client.get("/community").data
    assert b"Shared Example Labs" in logged_client.get("/community/u/bob").data
    data.pop("share_jobs")
    assert recipient.post("/community/settings", data=data).status_code == 302
    assert b"Personal best" in logged_client.get("/community/u/bob").data
    assert (
        b"Shared Example Labs"
        not in logged_client.get("/community/u/bob").data
    )
    copy_token = csrf_token(logged_client, "/community")
    assert (
        logged_client.post(
            f"/community/u/bob/jobs/{public_id}/save",
            data={"csrf_token": copy_token},
        ).status_code
        == 404
    )
    data["profile_visibility"] = "private"
    assert recipient.post("/community/settings", data=data).status_code == 302
    assert b"Personal best" not in logged_client.get("/community/u/bob").data


def test_copy_to_shortlist_is_private_safe_and_replay_safe(
    app, logged_client, community_people
):
    source_id, public_id = shared_record(app, community_people[1])
    connect_friends(app, logged_client, community_people)
    token = csrf_token(logged_client, "/community")
    path = f"/community/u/bob/jobs/{public_id}/save"
    for _ in range(2):
        response = logged_client.post(path, data={"csrf_token": token})
        assert response.status_code == 302
    with app.app_context():
        copy = JobApplication.for_user(community_people[0]).one()
        assert response.location.endswith(f"/jobs/{copy.id}")
        assert copy.status == "shortlisted" and copy.applied_on is None
        assert copy.job_url == "https://example.com/jobs/fictional"
        assert (
            copy.notes
            is copy.salary
            is copy.contact_person
            is copy.resume_filename
            is None
        )
        assert (
            ChangeEntry.query.filter_by(user_id=community_people[0]).count()
            == 1
        )
        assert (
            application_stats([community_people[0]])[community_people[0]][
                "total"
            ]
            == 0
        )
        assert db.session.get(JobApplication, source_id).status == "applied"
    assert logged_client.post(path, data={}).status_code == 400


def test_unauthorized_job_copy_and_unsubmitted_records_are_hidden(
    app, logged_client, community_people
):
    _, public_id = shared_record(app, community_people[1])
    token = csrf_token(logged_client, "/community")
    assert (
        logged_client.post(
            f"/community/u/bob/jobs/{public_id}/save",
            data={"csrf_token": token},
        ).status_code
        == 404
    )
    connect_friends(app, logged_client, community_people)
    for status in ("shortlisted", "skipped"):
        _, private_id = shared_record(
            app,
            community_people[1],
            job_title=f"Hidden {status}",
            status=status,
        )
        assert (
            logged_client.post(
                f"/community/u/bob/jobs/{private_id}/save",
                data={"csrf_token": token},
            ).status_code
            == 404
        )
        assert (
            f"Hidden {status}".encode()
            not in logged_client.get("/community/u/bob").data
        )


def test_activity_counts_real_dates_streaks_best_day_and_unknowns(app, users):
    today = date(2026, 10, 7)
    with app.app_context():
        for offset, count in [(0, 2), (1, 3), (2, 1), (7, 4), (8, 1)]:
            for _ in range(count):
                save_application(
                    JobApplication(user_id=users[0]),
                    {
                        "job_title": "Fictional role",
                        "company": "Example",
                        "status": "applied",
                        "applied_on": today - timedelta(days=offset),
                    },
                )
        for status, applied_on, deleted in [
            ("interviewing", None, False),
            ("shortlisted", today, False),
            ("skipped", today, False),
            ("closed", None, False),
            ("applied", today + timedelta(days=1), False),
            ("applied", today, True),
        ]:
            item = JobApplication(
                user_id=users[0],
                job_title="Excluded role",
                company="Example",
                status=status,
                applied_on=applied_on,
            )
            if deleted:
                item.deleted_at = datetime.now(timezone.utc)
            db.session.add(item)
        db.session.commit()
        stats = application_stats(users, today=today)
        owner = stats[users[0]]
        assert owner["total"] == 12 and owner["unknown_dates"] == 1
        assert owner["today"] == 2 and owner["week"] == 6
        assert owner["best_day"] == 4 and owner[
            "best_date"
        ] == today - timedelta(days=7)
        assert owner["streak"] == owner["best_streak"] == 3
        assert owner["xp"] == 120 and owner["level"] == 2
        assert owner["level_progress"] == 20 and owner["to_next_level"] == 8
        assert stats[users[1]]["total"] == 0
        assert sum(day["count"] for day in owner["activity"]) == 11


def test_yesterday_streak_keeps_momentum_until_today_ends(app, users):
    today = date(2026, 10, 7)
    with app.app_context():
        for offset in range(1, 8):
            db.session.add(
                JobApplication(
                    user_id=users[0],
                    job_title="Fictional role",
                    company="Example",
                    status="applied",
                    applied_on=today - timedelta(days=offset),
                )
            )
        db.session.commit()
        progress = application_stats([users[0]], today=today)[users[0]]
        assert progress["streak"] == progress["best_streak"] == 7
        assert next(
            item for item in progress["badges"] if item["name"] == "On a roll"
        )["earned"]
        assert (
            application_stats([users[0]], today=today + timedelta(days=1))[
                users[0]
            ]["streak"]
            == 0
        )


def test_comparison_only_includes_accepted_friends_and_handles_ties(
    app, logged_client, community_people
):
    connect_friends(app, logged_client, community_people)
    with app.app_context():
        owner = db.session.get(User, community_people[0])
        lists = friend_lists(owner.id)
        rows = comparison_rows(owner, lists["friends"], "week")
        assert {row["person"].id for row in rows} == set(community_people[:2])
        assert [row["rank"] for row in rows] == [1, 1]
    assert logged_client.get("/community?metric=invalid").status_code == 200


def test_shared_pagination_and_html_escaping(
    app, logged_client, community_people
):
    connect_friends(app, logged_client, community_people)
    for index in range(21):
        shared_record(
            app, community_people[1], job_title=f"Role <script> {index}"
        )
    response = logged_client.get("/community/u/bob")
    assert b"Page 1 of 2" in response.data
    assert (
        b"&lt;script&gt;" in response.data
        and b"Role <script>" not in response.data
    )
    assert logged_client.get("/community/u/bob?page=2").status_code == 200


def test_community_migration_preserves_existing_accounts_and_jobs(app_factory):
    app = app_factory(migrate=False)
    with app.app_context():
        upgrade(directory=MIGRATIONS, revision="c82b4f7d901a")
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user (id,email,password_hash,feed_sequence) "
                    "VALUES (7,'legacy@example.com','preserved-hash',42)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO job_application "
                    "(id,public_id,job_title,company,status,user_id,version,"
                    "resume_filename,applied_on,posted_at_approximate,"
                    "created_at) VALUES (9,'preserved-public-id',"
                    "'Keep title','Keep company',"
                    "'applied',7,3,'preserved.pdf','2026-10-01',false,"
                    "'2026-10-01 12:00:00')"
                )
            )
        upgrade(directory=MIGRATIONS)
        person = db.session.get(User, 7)
        assert (
            person.password_hash == "preserved-hash"
            and person.feed_sequence == 42
        )
        assert person.handle is None and person.profile_visibility == "private"
        assert person.share_jobs is False and person.daily_goal == 5
        job = db.session.get(JobApplication, 9)
        assert job.version == 3 and job.resume_filename == "preserved.pdf"
        assert job.public_id == "preserved-public-id"
        db.session.remove()
        downgrade(directory=MIGRATIONS, revision="c82b4f7d901a")
        with db.engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT job_title FROM job_application WHERE id=9")
                ).scalar_one()
                == "Keep title"
            )


def test_existing_dashboard_and_job_updates_remain_available(
    logged_client, app, users
):
    page = logged_client.get("/dashboard")
    assert page.status_code == 200 and b"Your progress" in page.data
    token = csrf_token(logged_client, "/jobs/add")
    response = logged_client.post(
        "/jobs/add",
        data=job_data(
            csrf_token=token,
            applied_on=datetime.now(timezone.utc).date().isoformat(),
        ),
    )
    assert response.status_code == 302
    assert logged_client.get(response.location).status_code == 200
    with app.app_context():
        assert application_stats([users[0]])[users[0]]["today"] == 1
