import pytest
from flask_login import login_user
from flask_sqlalchemy.query import Query

from app.extensions import db
from app.models import User
from tests.helpers import csrf_token


@pytest.mark.parametrize("path", ["/login", "/register"])
def test_authenticated_users_skip_account_forms(logged_client, path):
    assert logged_client.get(path).location == "/dashboard"


@pytest.mark.parametrize(
    "path,fields",
    [
        ("/login", ["email", "password"]),
        ("/register", ["email", "password", "confirm"]),
    ],
)
def test_shared_account_templates_render_each_input_once(client, path, fields):
    response = client.get(path)
    assert response.status_code == 200
    for field in fields:
        assert response.data.count(f'name="{field}"'.encode()) == 1
    assert response.data.count(b'name="csrf_token"') == 1
    assert b"you@example.com" in response.data


def test_login_blocks_browser_normalized_redirect(client, users):
    token = csrf_token(client, "/login")
    response = client.post(
        "/login",
        query_string={"next": "/\\evil.example"},
        data={
            "email": "owner@example.com",
            "password": "correct-password",
            "csrf_token": token,
        },
    )
    assert response.status_code == 302
    assert response.location == "/dashboard"


def test_login_redirect_and_session_rotation(client, users):
    token = csrf_token(client, "/login")
    with client.session_transaction() as session:
        session["old_session_data"] = "discard me"
        old_csrf = session["csrf_token"]
    response = client.post(
        "/login?next=/jobs",
        data={
            "email": "  OWNER@example.com  ",
            "password": "correct-password",
            "csrf_token": token,
        },
    )
    assert response.location == "/jobs"
    with client.session_transaction() as session:
        assert session["_user_id"] == str(users[0])
        assert "old_session_data" not in session
        assert "csrf_token" not in session
    csrf_token(client, "/jobs")
    with client.session_transaction() as session:
        assert session["csrf_token"] != old_csrf


def test_logout_requires_post_and_csrf(logged_client):
    assert logged_client.get("/logout").status_code == 405
    assert logged_client.post("/logout").status_code == 400
    with logged_client.session_transaction() as session:
        assert "_user_id" in session
    token = csrf_token(logged_client, "/dashboard")
    assert (
        logged_client.post(
            "/logout", data={"csrf_token": token, "version": 1}
        ).location
        == "/login"
    )
    with logged_client.session_transaction() as session:
        assert "_user_id" not in session


def test_logout_clears_existing_remember_cookie(app, client, users):
    @app.route("/test-remember-login")
    def remember_login():
        login_user(db.session.get(User, users[0]), remember=True)
        return "logged in"

    assert client.get("/test-remember-login").status_code == 200
    assert client.get_cookie("remember_token") is not None
    token = csrf_token(client, "/dashboard")
    assert (
        client.post(
            "/logout", data={"csrf_token": token, "version": 1}
        ).status_code
        == 302
    )
    assert client.get_cookie("remember_token") is None
    assert client.get("/dashboard").status_code == 302


@pytest.mark.parametrize("value", ["not-an-integer", "9" * 100, None])
def test_invalid_session_user_does_not_crash(client, value):
    with client.session_transaction() as session:
        session["_user_id"] = value
    assert client.get("/dashboard").status_code == 302


def test_authentication_rate_limit(app_factory):
    app = app_factory(RATELIMIT_ENABLED=True)
    client = app.test_client()
    token = csrf_token(client, "/login")
    for _ in range(10):
        response = client.post(
            "/login",
            data={
                "email": "missing@example.com",
                "password": "invalid-password",
                "csrf_token": token,
            },
        )
        assert response.status_code == 200
    response = client.post(
        "/login",
        data={
            "email": "missing@example.com",
            "password": "invalid-password",
            "csrf_token": token,
        },
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert client.get("/login").status_code == 200


def test_registration_normalizes_email_and_hashes_password(client, app):
    response = client.post(
        "/register",
        data={
            "email": " New@example.com ",
            "password": "a-new-password",
            "confirm": "a-new-password",
            "csrf_token": csrf_token(client, "/register"),
        },
    )
    assert response.location == "/login"
    with app.app_context():
        user = User.query.filter_by(email="new@example.com").one()
        assert user.password_hash != "a-new-password"
        assert user.check_password("a-new-password")


def test_registration_duplicate_race_is_handled(
    client, app, users, monkeypatch
):
    token = csrf_token(client, "/register")
    original_first = Query.first
    calls = 0

    def first(query):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original_first(query)

    monkeypatch.setattr(Query, "first", first)
    response = client.post(
        "/register",
        data={
            "email": "owner@example.com",
            "password": "a-new-password",
            "confirm": "a-new-password",
            "csrf_token": token,
        },
    )
    assert response.status_code == 200
    assert b"already exists" in response.data
    with app.app_context():
        assert User.query.count() == 2


def test_oversized_password_is_rejected(client, users, monkeypatch):
    def must_not_hash(*args):
        pytest.fail(
            "Oversized passwords must be rejected before password hashing"
        )

    monkeypatch.setattr(User, "check_password", must_not_hash)
    token = csrf_token(client, "/login")
    response = client.post(
        "/login",
        data={
            "email": "owner@example.com",
            "password": "a" * 1025,
            "csrf_token": token,
        },
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "_user_id" not in session


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/jobs",
        "/jobs/add",
        "/jobs/1",
        "/jobs/1/edit",
        "/jobs/1/resume",
    ],
)
def test_job_pages_require_authentication(client, path):
    assert client.get(path).status_code == 302


@pytest.mark.parametrize("secret", [None, "", "dev-secret-change-me"])
def test_missing_or_weak_secret_fails_at_startup(app_factory, secret):
    with pytest.raises(ValueError, match="SECRET_KEY"):
        app_factory(migrate=False, SECRET_KEY=secret)
