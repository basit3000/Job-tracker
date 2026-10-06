"""Real database transactions; PostgreSQL runs in a disposable schema only."""

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.contracts import ServiceError
from app.database import database_transaction
from app.devices import approve_pairing, redeem_pairing, start_pairing
from app.extensions import db
from app.models import (
    ApplicationMapping,
    ChangeEntry,
    Device,
    JobApplication,
    MutationReceipt,
    StatusEvent,
    User,
)
from app.record_updates import lock_account, write_application
from app.sync import feed_page, mutate
from config import normalize_database_url


@pytest.fixture(params=["sqlite", "postgresql"])
def concurrent_app(request, app_factory):
    if request.param == "sqlite":
        yield app_factory()
        return
    uri = os.environ.get("TEST_POSTGRES_URL")
    if not uri:
        pytest.skip("Set TEST_POSTGRES_URL for PostgreSQL integration checks.")
    uri = normalize_database_url(uri)
    if not uri.startswith("postgresql+"):
        pytest.fail("TEST_POSTGRES_URL must name PostgreSQL.")
    engine = create_engine(uri, hide_parameters=True)
    schema = "tracker_test_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        app = app_factory(
            SQLALCHEMY_DATABASE_URI=uri,
            SQLALCHEMY_ENGINE_OPTIONS={
                "hide_parameters": True,
                "connect_args": {"options": f"-csearch_path={schema}"},
            },
        )
        yield app
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
    finally:
        assert re.fullmatch(r"tracker_test_[a-f0-9]{32}", schema)
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def setup_device(app):
    with app.app_context():
        user = User(email="concurrency@example.com")
        user.set_password("fictional-password")
        db.session.add(user)
        db.session.commit()
        pairing = start_pairing(
            "fictional-concurrent-installation", "Concurrent client"
        )
        approve_pairing(user.id, pairing["userCode"], [])
        result = redeem_pairing(pairing["pairingId"], pairing["pairingSecret"])
        return user.id, result["deviceId"]


def execute(app, device_id, body, gate=None):
    if gate:
        assert gate.wait(5)
    with app.app_context():
        device = db.session.get(Device, device_id)
        try:
            return 200, mutate(body, device)
        except ServiceError as error:
            return error.status, error.code


def test_concurrent_duplicate_mutations_have_one_durable_outcome(
    concurrent_app,
):
    app = concurrent_app
    _, device_id = setup_device(app)
    body = {
        "mutationId": str(uuid4()),
        "operation": "create",
        "localRecordId": "opaque-local-record",
        "fields": {"title": "Role", "company": "Example", "status": "applied"},
    }
    gate = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(execute, app, device_id, body, gate) for _ in range(2)
        ]
        gate.set()
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    assert results[0][0] == 200
    with app.app_context():
        assert JobApplication.query.count() == 1
        assert StatusEvent.query.count() == 1
        assert ChangeEntry.query.count() == 1
        assert MutationReceipt.query.count() == 1


def test_competing_edits_have_one_winner_and_one_conflict(concurrent_app):
    app = concurrent_app
    _, device_id = setup_device(app)
    created = execute(
        app,
        device_id,
        {
            "mutationId": str(uuid4()),
            "operation": "create",
            "fields": {
                "title": "Role",
                "company": "Example",
                "status": "applied",
            },
        },
    )[1]["application"]
    gate = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                execute,
                app,
                device_id,
                {
                    "mutationId": str(uuid4()),
                    "operation": "update",
                    "applicationId": created["id"],
                    "expectedVersion": 1,
                    "fields": {"status": status},
                },
                gate,
            )
            for status in ("interviewing", "offer")
        ]
        gate.set()
        results = [future.result(timeout=10) for future in futures]
    assert sorted(result[0] for result in results) == [200, 409]
    with app.app_context():
        assert JobApplication.query.one().version == 2
        assert StatusEvent.query.count() == 2
        assert [
            row.sequence
            for row in ChangeEntry.query.order_by(ChangeEntry.sequence)
        ] == [1, 2]


def test_change_sequence_cannot_commit_out_of_order(concurrent_app):
    app = concurrent_app
    owner, device_id = setup_device(app)
    execute(
        app,
        device_id,
        {
            "mutationId": str(uuid4()),
            "operation": "create",
            "fields": {"title": "Initial", "company": "Example"},
        },
    )
    ready = threading.Event()
    release = threading.Event()
    attempted = threading.Event()

    def held_write():
        with app.app_context(), database_transaction():
            lock_account(owner)
            write_application(
                JobApplication(user_id=owner),
                {"job_title": "Held", "company": "Example"},
            )
            ready.set()
            assert release.wait(5)

    def next_write():
        attempted.set()
        return execute(
            app,
            device_id,
            {
                "mutationId": str(uuid4()),
                "operation": "create",
                "fields": {"title": "Next", "company": "Example"},
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(held_write)
        assert ready.wait(5)
        second = pool.submit(next_write)
        assert attempted.wait(5)
        try:
            with app.app_context():
                device = db.session.get(Device, device_id)
                page = feed_page(device)
                assert [row["sequence"] for row in page["entries"]] == [1]
                cursor = page["cursor"]
            assert not second.done()
        finally:
            release.set()
        first.result(timeout=10)
        assert second.result(timeout=10)[0] == 200
    with app.app_context():
        page = feed_page(db.session.get(Device, device_id), token=cursor)
        assert [row["sequence"] for row in page["entries"]] == [2, 3]


def test_revocation_blocks_a_mutation_that_authenticated_before_revocation(
    concurrent_app,
):
    app = concurrent_app
    owner, device_id = setup_device(app)
    from app.devices import revoke_device

    with app.app_context():
        device = db.session.get(Device, device_id)
        # Another session revokes the device after this session read it.
        with ThreadPoolExecutor(max_workers=1) as pool:

            def revoke():
                with app.app_context():
                    revoke_device(owner, device_id)

            pool.submit(revoke).result(timeout=10)
        with pytest.raises(ServiceError, match="revoked"):
            mutate(
                {
                    "mutationId": str(uuid4()),
                    "operation": "create",
                    "fields": {"title": "Role", "company": "Example"},
                },
                device,
            )
        assert JobApplication.query.count() == 0


def test_database_constraints_reject_duplicate_identity_and_invalid_state(
    concurrent_app,
):
    app = concurrent_app
    owner, device_id = setup_device(app)
    execute(
        app,
        device_id,
        {
            "mutationId": "constraint-create",
            "operation": "create",
            "localRecordId": "constraint-local",
            "fields": {"title": "Role", "company": "Example"},
        },
    )
    with app.app_context():
        job = JobApplication.query.one()
        job_id, public_id = job.id, job.public_id
        duplicates = [
            ApplicationMapping(
                user_id=owner,
                application_id=job_id,
                installation_id="fictional-concurrent-installation",
                local_record_id="constraint-local",
            ),
            ChangeEntry(
                user_id=owner,
                sequence=1,
                application_id=public_id,
                payload={},
                source="device",
            ),
            MutationReceipt(
                user_id=owner,
                device_id=device_id,
                mutation_id="constraint-create",
                request_hash="f" * 64,
                response={},
            ),
            JobApplication(
                user_id=owner,
                public_id=public_id,
                job_title="Duplicate",
                company="Example",
            ),
        ]
        for row in duplicates:
            db.session.add(row)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        for key, value in (("status", "invalid"), ("version", 0)):
            job = db.session.get(JobApplication, job_id)
            setattr(job, key, value)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        assert JobApplication.query.one().version == 1
