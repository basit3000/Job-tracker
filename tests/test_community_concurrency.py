"""Database-backed friendship races and shared-job integration."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.community import (
    change_friendship,
    request_friendship,
    shared_jobs,
    shortlist_shared_job,
)
from app.contracts import ServiceError
from app.extensions import db
from app.gamification import application_stats
from app.models import Friendship, JobApplication, User
from app.services import save_application
from tests.test_concurrency import concurrent_app as concurrent_app


def make_people(app):
    with app.app_context():
        people = []
        for name in ("alice", "bob"):
            user = User(
                email=f"{name}@example.com", handle=name, share_jobs=True
            )
            user.set_password("fictional-password")
            db.session.add(user)
            people.append(user)
        db.session.commit()
        return tuple(person.id for person in people)


def test_simultaneous_reverse_requests_keep_one_pending_pair(concurrent_app):
    app = concurrent_app
    people = make_people(app)

    def request(actor_id, target_id):
        with app.app_context():
            try:
                request_friendship(
                    db.session.get(User, actor_id),
                    db.session.get(User, target_id),
                )
            except ServiceError as error:
                return error.status
            return 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda pair: request(*pair), [people, people[::-1]])
        )
    assert sorted(results) == [200, 409]
    with app.app_context():
        assert Friendship.query.count() == 1
        assert Friendship.query.one().status == "pending"


def test_shared_jobs_and_schema_work_on_both_databases(concurrent_app):
    app = concurrent_app
    alice_id, bob_id = make_people(app)
    with app.app_context():
        alice = db.session.get(User, alice_id)
        bob = db.session.get(User, bob_id)
        request_friendship(alice, bob)
        link_id = Friendship.query.one().id
        change_friendship(bob_id, link_id, "accept")
        item = JobApplication(user_id=bob_id)
        save_application(
            item,
            {
                "job_title": "Fictional shared role",
                "company": "Example",
                "status": "applied",
                "applied_on": date(2026, 1, 1),
                "notes": "Never copied",
            },
        )
        assert shared_jobs(alice_id, bob).count() == 1
        saved, created = shortlist_shared_job(alice, bob, item.public_id)
        assert (
            created and saved.status == "shortlisted" and saved.notes is None
        )
        assert application_stats([alice_id])[alice_id]["total"] == 0
        with db.engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, db.metadata) == []
        change_friendship(alice_id, link_id, "remove")
        with pytest.raises(ServiceError, match="private"):
            shared_jobs(alice_id, bob)


def test_simultaneous_shortlist_saves_create_one_synced_record(concurrent_app):
    app = concurrent_app
    alice_id, bob_id = make_people(app)
    with app.app_context():
        bob = db.session.get(User, bob_id)
        bob.profile_visibility = "public"
        item = JobApplication(user_id=bob_id)
        save_application(
            item,
            {
                "job_title": "Fictional role",
                "company": "Example",
                "status": "applied",
                "applied_on": date(2026, 1, 1),
            },
        )
        public_id = item.public_id

    def save():
        with app.app_context():
            job, created = shortlist_shared_job(
                db.session.get(User, alice_id),
                db.session.get(User, bob_id),
                public_id,
            )
            return job.id, created

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: save(), range(2)))
    assert len({job_id for job_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    with app.app_context():
        assert JobApplication.for_user(alice_id).count() == 1
        assert db.session.get(User, alice_id).feed_sequence == 1
