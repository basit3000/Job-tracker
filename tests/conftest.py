from pathlib import Path

import pytest
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import JobApplication, User
from config import Config
from tests.helpers import MIGRATIONS


@pytest.fixture
def app_factory(tmp_path):
    apps = []

    def make_app(migrate=True, **overrides):
        folder = tmp_path / str(len(apps))
        folder.mkdir()
        database_path = (folder / "test.db").as_posix()
        options = {
            "TESTING": True,
            "PUBLIC_SIGNUP_ENABLED": True,
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "SYNC_ENCRYPTION_KEY": "",
            "GOOGLE_REDIRECT_URI": "http://localhost:5000/auth/google/callback",
            "ALLOW_INSECURE_LOCAL_API": True,
            "PROPAGATE_EXCEPTIONS": False,
            "SECRET_KEY": "a-private-test-secret-with-more-than-32-characters",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "UPLOAD_FOLDER": str(folder / "uploads"),
            "SESSION_COOKIE_SECURE": False,
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URI": "memory://",
        }
        options.update(overrides)
        app = create_app(type("TestConfig", (Config,), options))
        apps.append(app)
        if migrate:
            with app.app_context():
                upgrade(directory=MIGRATIONS)
        return app

    yield make_app
    for app in apps:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


@pytest.fixture
def app(app_factory):
    return app_factory()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def users(app):
    with app.app_context():
        owner = User(email="owner@example.com")
        owner.set_password("correct-password")
        other = User(email="other@example.com")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.commit()
        return owner.id, other.id


@pytest.fixture
def logged_client(client, users):
    with client.session_transaction() as session:
        session["_user_id"] = str(users[0])
        session["_fresh"] = True
    return client


@pytest.fixture
def job(app, users):
    Path(app.config["UPLOAD_FOLDER"], "existing.pdf").write_bytes(
        b"original resume"
    )
    with app.app_context():
        job = JobApplication(
            job_title="Engineer",
            company="Example",
            status="applied",
            user_id=users[0],
            resume_filename="existing.pdf",
        )
        db.session.add(job)
        db.session.commit()
        return job.id


@pytest.fixture
def paired(client, app, users):
    from tests.helpers import pair_device

    return pair_device(client, app, users[0])[0]
