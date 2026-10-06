"""Fictional Google transport with real OAuth state and JWT verification."""

import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.google_login import FLOW_KEY, google_client
from app.models import User
from app.security import GoogleCallbackLogFilter
from tests.google_provider import (
    BASE_URL,
    GOOGLE_CONFIG,
    mock_google_transport,
)
from tests.helpers import MIGRATIONS, csrf_token


@pytest.fixture
def google_app(app_factory):
    return app_factory(**GOOGLE_CONFIG)


@pytest.fixture
def provider(monkeypatch):
    return mock_google_transport(monkeypatch)


def begin(client, *, intent="signin", password=None, next_page=""):
    path = "/account" if intent == "link" else "/login"
    token = csrf_token(client, path)
    data = {"intent": intent, "csrf_token": token, "next": next_page}
    if password is not None:
        data["password"] = password
    response = client.post("/auth/google", data=data, base_url=BASE_URL)
    assert response.status_code == 302
    assert urlsplit(response.location).hostname == "accounts.google.com"
    params = {
        key: value[0]
        for key, value in parse_qs(urlsplit(response.location).query).items()
    }
    assert set(params["scope"].split()) == {"openid", "email"}
    assert params["code_challenge_method"] == "S256"
    return params


def finish(client, provider, params, **changes):
    code = provider.issue(
        params["nonce"], code_challenge=params["code_challenge"], **changes
    )
    return client.get(
        "/auth/google/callback",
        base_url=BASE_URL,
        query_string={"code": code, "state": params["state"]},
    )


def test_google_signup_login_session_rotation_and_password_exclusion(
    google_app,
    provider,
):
    client = google_app.test_client()
    for path in ("/login", "/register"):
        assert b"Continue with Google" in client.get(path).data
    params = begin(client, next_page="/jobs")
    with client.session_transaction() as session:
        session["previous-session"] = "discard"
    response = finish(client, provider, params)
    assert response.location == "/jobs"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    with google_app.app_context():
        user = User.query.one()
        user_id = user.id
        assert user.google_subject == "fictional-google-subject"
        assert user.password_hash is None
        assert not user.check_password("any-password")
    with client.session_transaction() as session:
        assert session["_user_id"] == str(user_id)
        assert "previous-session" not in session
        assert not any(key.startswith("_state_google") for key in session)
        assert FLOW_KEY not in session
        assert "fictional-access-token" not in json.dumps(dict(session))
        session.clear()
    # Repeat sign-in uses the stable subject, even if Google's email changes.
    params = begin(client)
    assert (
        finish(
            client,
            provider,
            params,
            email="changed@example.com",
            iss="accounts.google.com",
        ).location
        == "/dashboard"
    )
    with google_app.app_context():
        assert User.query.count() == 1
        assert User.query.one().email == "google-user@example.com"
    with client.session_transaction() as session:
        session.clear()
    for password in ("any-password", "unused-password-for-timing"):
        response = client.post(
            "/login",
            data={
                "email": "google-user@example.com",
                "password": password,
                "csrf_token": csrf_token(client, "/login"),
            },
        )
        assert response.status_code == 200
        with client.session_transaction() as session:
            assert "_user_id" not in session


@pytest.mark.parametrize(
    "claims",
    [
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": "invalid"},
        {"sub": ""},
        {"sub": "nonascii-\u2603"},
        {"aud": "different-client"},
        {"iss": "https://evil.example.com"},
        {"exp": 1},
        {"nonce": "different-nonce"},
        {"nonce_supported": False, "nonce": "different-nonce"},
        {"bad_signature": True},
        {"omit_id_token": True},
    ],
)
def test_google_rejects_unverified_or_invalid_signed_identities(
    google_app,
    provider,
    claims,
):
    client = google_app.test_client()
    response = finish(client, provider, begin(client), **claims)
    assert response.location == "/login"
    with google_app.app_context():
        assert User.query.count() == 0
    with client.session_transaction() as session:
        assert "_user_id" not in session
        assert FLOW_KEY not in session


def test_google_state_expiry_replay_and_cross_browser_protection(
    google_app,
    provider,
):
    client = google_app.test_client()
    params = begin(client)
    for state in ("forged", "\u2603", ""):
        result = client.get(
            "/auth/google/callback",
            query_string={
                "state": state,
                "code": "not-exchanged",
            },
            base_url=BASE_URL,
        )
        assert result.location == "/login"
    other = google_app.test_client()
    assert (
        other.get(
            "/auth/google/callback",
            query_string={
                "state": params["state"],
                "code": "not-exchanged",
            },
            base_url=BASE_URL,
        ).location
        == "/login"
    )
    assert provider.token_calls == 0
    with client.session_transaction() as session:
        session[FLOW_KEY] = {
            **session[FLOW_KEY],
            "started_at": time.time() - 601,
        }
    assert finish(client, provider, params).location == "/login"
    assert provider.token_calls == 0
    params = begin(client)
    assert finish(client, provider, params).location == "/dashboard"
    assert provider.token_calls == 1
    assert finish(client, provider, params).location == "/login"
    assert provider.token_calls == 1


def test_google_existing_password_account_needs_explicit_link(
    google_app,
    provider,
):
    client = google_app.test_client()
    with google_app.app_context():
        user = User(email="google-user@example.com")
        user.set_password("fictional-local-password")
        db.session.add(user)
        db.session.commit()
        original_id = user.id
    assert finish(client, provider, begin(client)).location == "/login"
    with google_app.app_context():
        assert User.query.one().google_subject is None
    with client.session_transaction() as session:
        session["_user_id"] = str(original_id)
        session["_fresh"] = True
    wrong = client.post(
        "/auth/google",
        base_url=BASE_URL,
        data={
            "csrf_token": csrf_token(client, "/account"),
            "intent": "link",
            "password": "wrong",
        },
    )
    assert wrong.location == "/account"
    params = begin(client, intent="link", password="fictional-local-password")
    assert finish(client, provider, params).location == "/account"
    with google_app.app_context():
        user = User.query.one()
        assert user.id == original_id
        assert user.google_subject == "fictional-google-subject"
        assert user.check_password("fictional-local-password")
    assert b"Google is connected" in client.get("/account").data


def test_google_link_cannot_change_account_or_use_other_email(
    google_app,
    provider,
):
    with google_app.app_context():
        first = User(email="google-user@example.com")
        second = User(email="other@example.com")
        for user in (first, second):
            user.set_password("fictional-password")
        db.session.add_all([first, second])
        db.session.commit()
        first_id, second_id = first.id, second.id
    client = google_app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(first_id)
        session["_fresh"] = True
    params = begin(client, intent="link", password="fictional-password")
    assert (
        finish(client, provider, params, email="other@example.com").location
        == "/login"
    )
    params = begin(client, intent="link", password="fictional-password")
    with client.session_transaction() as session:
        session["_user_id"] = str(second_id)
    assert finish(client, provider, params).location == "/login"
    with google_app.app_context():
        assert not User.query.filter(User.google_subject.isnot(None)).count()


def test_google_closed_signup_keeps_existing_google_login(
    google_app,
    provider,
):
    client = google_app.test_client()
    google_app.config["PUBLIC_SIGNUP_ENABLED"] = False
    assert finish(client, provider, begin(client)).location == "/login"
    with google_app.app_context():
        assert User.query.count() == 0
    google_app.config["PUBLIC_SIGNUP_ENABLED"] = True
    assert finish(client, provider, begin(client)).location == "/dashboard"
    google_app.config["PUBLIC_SIGNUP_ENABLED"] = False
    with client.session_transaction() as session:
        session.clear()
    assert finish(client, provider, begin(client)).location == "/dashboard"


def test_google_csrf_disabled_config_transport_and_safe_redirect(
    app,
    google_app,
    provider,
):
    disabled = app.test_client()
    assert b"Continue with Google" not in disabled.get("/login").data
    assert disabled.get("/auth/google/callback").status_code == 404
    client = google_app.test_client()
    policy = client.get("/login").headers["Content-Security-Policy"]
    assert "form-action 'self' https://accounts.google.com" in policy
    assert (
        "accounts.google.com"
        not in disabled.get("/login").headers["Content-Security-Policy"]
    )
    assert client.get("/auth/google").status_code == 405
    assert (
        client.post("/auth/google", data={"intent": "signin"}).status_code
        == 400
    )
    response = client.post(
        "/auth/google",
        base_url="http://untrusted.example.com",
        data={
            "intent": "signin",
            "csrf_token": csrf_token(
                client, "/login", base_url="http://untrusted.example.com"
            ),
        },
        environ_overrides={"REMOTE_ADDR": "198.51.100.4"},
    )
    assert response.location == "/login"
    params = begin(client, next_page="https://evil.example.com")
    assert finish(client, provider, params).location == "/dashboard"
    assert client.get("/account").status_code == 200
    assert app.test_client().get("/account").location.startswith("/login")


def test_google_local_callback_allows_container_peer_but_public_needs_https(
    google_app, provider
):
    client = google_app.test_client()
    response = client.post(
        "/auth/google",
        base_url=BASE_URL,
        data={
            "intent": "signin",
            "csrf_token": csrf_token(client, "/login"),
        },
        environ_overrides={"REMOTE_ADDR": "172.18.0.1"},
    )
    assert urlsplit(response.location).hostname == "accounts.google.com"
    google_app.config["GOOGLE_REDIRECT_URI"] = (
        "https://tracker.example.com/auth/google/callback"
    )
    response = client.post(
        "/auth/google",
        base_url="http://tracker.example.com",
        data={
            "intent": "signin",
            "csrf_token": csrf_token(
                client, "/login", base_url="http://tracker.example.com"
            ),
        },
    )
    assert response.location == "/login"
    assert (
        b"Use HTTPS for Google sign-in"
        in client.get("/login", base_url="http://tracker.example.com").data
    )


def test_google_provider_failure_cancel_and_logging_are_safe(
    google_app,
    provider,
    caplog,
):
    client = google_app.test_client()
    provider.unavailable = True
    result = client.post(
        "/auth/google",
        base_url=BASE_URL,
        data={
            "intent": "signin",
            "csrf_token": csrf_token(client, "/login"),
        },
        follow_redirects=True,
    )
    assert b"Google is temporarily unavailable" in result.data
    assert b"fictional provider details" not in result.data
    provider.unavailable = False
    params = begin(client)
    cancelled = client.get(
        "/auth/google/callback",
        base_url=BASE_URL,
        query_string={
            "state": params["state"],
            "error": "access_denied",
            "error_description": "private-provider-description",
        },
        follow_redirects=True,
    )
    assert b"cancelled or could not be verified" in cancelled.data
    assert b"private-provider-description" not in cancelled.data
    assert "private-provider-description" not in caplog.text
    assert "fictional-client-secret" not in caplog.text


@pytest.mark.parametrize(
    "logger_name,args,message",
    [
        (
            "werkzeug",
            (
                "GET /auth/google/callback?code=private-code"
                "&state=private-state HTTP/1.1",
            ),
            "%s",
        ),
        (
            "gunicorn.access",
            {
                "r": "GET /auth/google/callback?code=private-code HTTP/1.1",
                "q": "code=private-code",
            },
            "%(r)s %(q)s",
        ),
    ],
)
def test_google_access_log_redaction(logger_name, args, message):
    record = logging.LogRecord(
        logger_name, logging.INFO, "", 0, message, (), None
    )
    record.args = args
    GoogleCallbackLogFilter().filter(record)
    assert "private-code" not in record.getMessage()
    assert "private-state" not in record.getMessage()
    assert "/auth/google/callback" in record.getMessage()


def test_google_factory_clients_do_not_share_credentials(app_factory):
    first = app_factory(**GOOGLE_CONFIG)
    second = app_factory(
        **{**GOOGLE_CONFIG, "GOOGLE_CLIENT_ID": "other-client"}
    )
    with first.app_context():
        assert google_client().client_id == "fictional-client-id"
    with second.app_context():
        assert google_client().client_id == "other-client"


@pytest.mark.parametrize(
    "settings",
    [
        {"GOOGLE_CLIENT_SECRET": ""},
        {
            "GOOGLE_REDIRECT_URI": "http://tracker.example.com/auth/google/callback"
        },
        {
            "GOOGLE_REDIRECT_URI": "https://tracker.example.com/auth/google/callback?next=evil"
        },
        {
            "GOOGLE_REDIRECT_URI": "https://user:password@tracker.example.com/auth/google/callback"
        },
    ],
)
def test_google_partial_or_unsafe_configuration_fails(app_factory, settings):
    with pytest.raises(ValueError, match="GOOGLE_"):
        app_factory(migrate=False, **{**GOOGLE_CONFIG, **settings})


def test_google_migration_preserves_passwords_and_refuses_identity_loss(
    app_factory,
):
    app = app_factory(migrate=False)
    with app.app_context():
        upgrade(directory=MIGRATIONS, revision="c61e92ad7401")
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    'INSERT INTO "user" '
                    "(id,email,password_hash,feed_sequence) "
                    "VALUES (41,'legacy@example.com','preserved-hash',7)"
                )
            )
        upgrade(directory=MIGRATIONS)
        user = db.session.get(User, 41)
        assert user.password_hash == "preserved-hash"
        assert user.google_subject is None and user.feed_sequence == 7
        user.google_subject = "fictional-identity"
        db.session.commit()
        with pytest.raises((RuntimeError, SystemExit)):
            downgrade(directory=MIGRATIONS, revision="c61e92ad7401")
        db.session.rollback()
        assert db.session.get(User, 41).google_subject == "fictional-identity"
        empty = User(email="invalid-empty-account@example.com")
        db.session.add(empty)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
