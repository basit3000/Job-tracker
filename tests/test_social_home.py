"""The home feed respects consent, friendship changes and private fields."""

from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import Friendship, JobApplication, User
from app.social_home import home_context, shared_feed
from tests.helpers import csrf_token


@pytest.fixture
def feed_people(app, users):
    with app.app_context():
        owner = db.session.get(User, users[0])
        owner.handle = "alice"
        public = db.session.get(User, users[1])
        public.handle = "bob"
        public.display_name = "Bob Example"
        public.profile_visibility = "public"
        public.share_jobs = True
        people = {"public": public}
        for key, visibility, share in (
            ("friend", "private", True),
            ("pending", "private", True),
            ("hidden", "public", False),
            ("stranger", "private", True),
        ):
            person = User(
                email=f"{key}@example.com",
                handle=key,
                profile_visibility=visibility,
                share_jobs=share,
            )
            person.set_password("fictional-password")
            db.session.add(person)
            people[key] = person
        db.session.flush()
        for key, status in (("friend", "accepted"), ("pending", "pending")):
            db.session.add(
                Friendship(
                    user_low_id=owner.id,
                    user_high_id=people[key].id,
                    requested_by_id=people[key].id,
                    status=status,
                )
            )
        today = datetime.now(timezone.utc).date()
        for key, person in people.items():
            db.session.add(
                JobApplication(
                    user_id=person.id,
                    job_title=f"{key} role",
                    company="Example Labs",
                    status="offer" if key == "public" else "applied",
                    applied_on=today,
                    notes="PRIVATE_NOTE_SENTINEL",
                    contact_email="PRIVATE_EMAIL_SENTINEL",
                    salary="PRIVATE_SALARY_SENTINEL",
                    resume_filename="PRIVATE_RESUME_SENTINEL",
                )
            )
        db.session.commit()
        return {key: person.id for key, person in people.items()}


def test_home_projects_only_shared_applications_and_allowed_people(
    app, logged_client, users, feed_people
):
    response = logged_client.get("/")
    assert response.status_code == 200
    for text in (b"Community feed", b"public role", b"friend role"):
        assert text in response.data
    for text in (
        b"pending role",
        b"hidden role",
        b"stranger role",
        b"PRIVATE_",
        b"other@example.com",
        b"friend@example.com",
    ):
        assert text not in response.data
    with app.app_context():
        items = shared_feed(users[0]).items
        assert len(items) == 2
        assert all(not hasattr(item.job, "notes") for item in items)


def test_friends_wins_and_search_filter_the_visible_feed(
    logged_client, feed_people
):
    friends = logged_client.get("/?feed=friends").data
    assert b"friend role" in friends and b"public role" not in friends
    wins = logged_client.get("/?feed=wins").data
    assert b"public role" in wins and b"friend role" not in wins
    search = logged_client.get("/?q=public").data
    assert b"public role" in search and b"friend role" not in search
    literal = logged_client.get("/", query_string={"q": "%"}).data
    assert b"No matching applications" in literal
    assert b"public role" not in literal
    assert b"public role" in logged_client.get("/?feed=invalid&page=-4").data


def test_privacy_changes_remove_feed_access_and_block_stale_save(
    app, logged_client, feed_people
):
    with app.app_context():
        public = db.session.get(User, feed_people["public"])
        public.profile_visibility = "private"
        job = JobApplication.query.filter_by(user_id=public.id).one()
        public_id = job.public_id
        friend = db.session.get(User, feed_people["friend"])
        friend.share_jobs = False
        db.session.commit()
    assert b"public role" not in logged_client.get("/").data
    assert b"friend role" not in logged_client.get("/").data
    response = logged_client.post(
        f"/community/u/bob/jobs/{public_id}/save",
        data={"csrf_token": csrf_token(logged_client, "/")},
    )
    assert response.status_code == 404


def test_home_friend_actions_return_home_and_update_access(
    app, logged_client, feed_people
):
    with app.app_context():
        link_id = Friendship.query.filter_by(status="pending").one().id
    response = logged_client.post(
        f"/community/friendships/{link_id}/accept",
        data={
            "csrf_token": csrf_token(logged_client, "/"),
            "return_to": "home",
        },
    )
    assert response.location == "/"
    assert b"pending role" in logged_client.get("/?feed=friends").data
    logged_client.post(
        f"/community/friendships/{link_id}/remove",
        data={
            "csrf_token": csrf_token(logged_client, "/"),
            "return_to": "https://example.com",
        },
    )
    assert b"pending role" not in logged_client.get("/").data


def test_feed_excludes_own_deleted_future_and_unsubmitted_jobs(
    app, logged_client, users, feed_people
):
    with app.app_context():
        today = datetime.now(timezone.utc).date()
        for title, status, day, deleted, user_id in (
            ("My private role", "applied", today, None, users[0]),
            (
                "Future role",
                "applied",
                today + timedelta(days=1),
                None,
                feed_people["public"],
            ),
            (
                "Shortlisted role",
                "shortlisted",
                None,
                None,
                feed_people["public"],
            ),
            (
                "Deleted role",
                "applied",
                today,
                datetime.now(timezone.utc),
                feed_people["public"],
            ),
            (
                "Unknown date role",
                "applied",
                None,
                None,
                feed_people["public"],
            ),
        ):
            db.session.add(
                JobApplication(
                    user_id=user_id,
                    job_title=title,
                    company="Example",
                    status=status,
                    applied_on=day,
                    deleted_at=deleted,
                )
            )
        db.session.commit()
        context = home_context(db.session.get(User, users[0]))
        assert context["active_count"] == 1
        assert context["progress"]["week"] == 1
    html = logged_client.get("/").data
    for title in (
        b"My private role",
        b"Future role",
        b"Shortlisted role",
        b"Deleted role",
    ):
        assert title not in html
    assert b"Unknown date role" in html
    assert b"Application date not provided" in html


def test_feed_is_paginated_with_stable_order(app, users, feed_people):
    with app.app_context():
        for index in range(25):
            db.session.add(
                JobApplication(
                    user_id=feed_people["public"],
                    job_title=f"Role {index}",
                    company="Example",
                    status="applied",
                    applied_on=datetime.now(timezone.utc).date(),
                )
            )
        db.session.commit()
        first = shared_feed(users[0], page=1)
        second = shared_feed(users[0], page=2)
        assert first.total == 27
        assert len(first.items) == len(second.items) == 10
        assert not (
            {item.job.public_id for item in first.items}
            & {item.job.public_id for item in second.items}
        )


def test_guests_keep_the_landing_page_and_members_get_home(
    client, logged_client
):
    assert b"Community feed" in logged_client.get("/").data
    with logged_client.session_transaction() as session:
        session.clear()
    html = client.get("/").data
    assert b"Community feed" not in html
    assert b"Create account" in html


def test_home_due_count_opens_matching_follow_up_queue(
    app, logged_client, users
):
    with app.app_context():
        today = datetime.now(timezone.utc).date()
        for title, offset, owner in (
            ("Overdue role", -1, users[0]),
            ("Today role", 0, users[0]),
            ("Later role", 1, users[0]),
            ("Another person's role", 0, users[1]),
        ):
            db.session.add(
                JobApplication(
                    user_id=owner,
                    job_title=title,
                    company="Example",
                    status="applied",
                    follow_up_on=today + timedelta(days=offset),
                )
            )
        db.session.commit()
        assert home_context(db.session.get(User, users[0]))["due_count"] == 2
    html = logged_client.get("/follow-ups?due=due").data
    assert b"Overdue role" in html and b"Today role" in html
    assert b"Later role" not in html and b"Another person" not in html
    assert b"/follow-ups?due=due" in logged_client.get("/").data
