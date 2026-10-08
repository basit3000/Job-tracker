"""Hosting safety, release commands, CDN builds and maintenance boundaries."""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask, request
from sqlalchemy.exc import OperationalError

from app.deployment import client_address, configure_deployment
from app.extensions import db
from config import Config
from ops import build_vercel, migrate, serve


def production_app(**overrides):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.update(
        PRODUCTION=True,
        DEPLOYMENT_PLATFORM="vercel",
        DEBUG=False,
        ALLOW_INSECURE_LOCAL_API=False,
        SESSION_COOKIE_SECURE=True,
        REMEMBER_COOKIE_SECURE=True,
        SQLALCHEMY_DATABASE_URI="postgresql+psycopg2://db/jobtracker",
        RATELIMIT_STORAGE_URI="rediss://redis.example.com/0",
        APP_BASE_URL="https://tracker.example.com",
        UPLOAD_STORAGE="s3",
        S3_BUCKET="private-test-resumes",
        S3_ENDPOINT_URL=None,
        S3_ACCESS_KEY_ID=None,
        S3_SECRET_ACCESS_KEY=None,
        PROXY_FOR_COUNT=0,
        PROXY_PROTO_COUNT=1,
        CRON_SECRET="",
    )
    app.config.update(overrides)
    return app


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"DEBUG": True}, "debug"),
        ({"ALLOW_INSECURE_LOCAL_API": True}, "insecure"),
        ({"SQLALCHEMY_DATABASE_URI": "sqlite:///private.db"}, "PostgreSQL"),
        ({"RATELIMIT_STORAGE_URI": "memory://"}, "Redis"),
        ({"SESSION_COOKIE_SECURE": False}, "cookies"),
        ({"APP_BASE_URL": "http://tracker.example.com"}, "HTTPS origin"),
        ({"UPLOAD_STORAGE": "filesystem"}, "Vercel"),
        ({"UPLOAD_STORAGE": "unknown"}, "UPLOAD_STORAGE"),
        ({"S3_BUCKET": ""}, "S3_BUCKET"),
        ({"S3_ENDPOINT_URL": "http://storage.example.com"}, "HTTPS endpoint"),
        ({"S3_ACCESS_KEY_ID": "test-key"}, "both S3"),
        ({"CRON_SECRET": "short"}, "CRON_SECRET"),
        ({"PROXY_FOR_COUNT": -1}, "nonnegative"),
    ],
)
def test_cloud_rejects_unsafe_or_ephemeral_config(overrides, message):
    with pytest.raises(ValueError, match=message):
        configure_deployment(production_app(**overrides))


def test_cloud_proxy_trust_is_limited_to_configured_headers():
    app = production_app()
    configure_deployment(app)

    @app.get("/")
    def view():
        return {
            "secure": request.is_secure,
            "ip": request.remote_addr,
            "host": request.host,
            "client": client_address(),
        }

    response = app.test_client().get(
        "/",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "192.0.2.11",
            "X-Forwarded-Host": "evil.example.com",
            "X-Real-IP": "192.0.2.20",
        },
    )
    assert response.json == {
        "secure": True,
        "ip": "127.0.0.1",
        "host": "localhost",
        "client": "192.0.2.20",
    }
    app.config["DEPLOYMENT_PLATFORM"] = ""
    with app.test_request_context(headers={"X-Real-IP": "192.0.2.20"}):
        assert client_address() == "127.0.0.1"


def test_railway_requires_explicit_volume_or_object_storage():
    app = production_app(
        DEPLOYMENT_PLATFORM="railway",
        UPLOAD_STORAGE="filesystem",
        UPLOAD_FOLDER_EXPLICIT=False,
    )
    with pytest.raises(ValueError, match="persistent volume"):
        configure_deployment(app)
    app.config["UPLOAD_FOLDER_EXPLICIT"] = True
    configure_deployment(app)


def test_s3_cold_start_does_not_create_upload_directory(app_factory, tmp_path):
    folder = tmp_path / "read-only" / "uploads"
    app_factory(
        migrate=False,
        UPLOAD_STORAGE="s3",
        S3_BUCKET="test-resumes",
        UPLOAD_FOLDER=str(folder),
    )
    assert not folder.exists()


def test_health_response_has_no_database_details(client, monkeypatch):
    assert client.get("/healthz").json == {"status": "ok"}
    failure = OperationalError("private query", {}, Exception("private DSN"))
    monkeypatch.setattr(db.session, "execute", Mock(side_effect=failure))
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json == {"status": "unavailable"}
    assert "no-store" in response.headers["Cache-Control"]


def test_cron_is_disabled_without_secret_and_never_uses_query_auth(client):
    for path in (
        "/internal/cron/cleanup",
        "/internal/cron/cleanup?token=private",
    ):
        assert client.get(path).status_code == 401


def test_cron_uses_bearer_auth_and_bounded_services(app, client, monkeypatch):
    secret = "test-cron-secret-with-at-least-32-characters"
    app.config["CRON_SECRET"] = secret
    sources = Mock(return_value={"synced": 1, "failed": 0})
    reminders = Mock(return_value={"sent": 1, "failed": 0, "skipped": 0})
    monkeypatch.setattr("app.source_scheduler.run_due_syncs", sources)
    monkeypatch.setattr("app.notifications.run_due_reminders", reminders)
    assert client.get("/internal/cron/sources").status_code == 401
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/internal/cron/sources", headers=headers).json == {
        "synced": 1,
        "failed": 0,
    }
    sources.assert_called_once_with(limit=1)
    assert (
        client.get("/internal/cron/reminders", headers=headers).status_code
        == 200
    )
    reminders.assert_called_once_with(limit=10)
    assert (
        client.get("/internal/cron/unknown", headers=headers).status_code
        == 404
    )
    sources.side_effect = RuntimeError("private provider token")
    response = client.get("/internal/cron/sources", headers=headers)
    assert response.status_code == 503
    assert response.json == {"error": "unavailable"}


def test_release_migrates_as_owner_without_touching_volume(monkeypatch):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://owner/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime/db")
    monkeypatch.setenv("UPLOAD_FOLDER", "/persistent/private")
    monkeypatch.delenv("GRANT_RUNTIME_ROLE", raising=False)
    run = Mock()
    monkeypatch.setattr(migrate.subprocess, "run", run)
    migrate.main()
    run.assert_called_once()
    args, kwargs = run.call_args
    assert args[0][-2:] == ["db", "upgrade"]
    assert kwargs["env"]["DATABASE_URL"] == "postgresql://owner/db"
    assert kwargs["env"]["UPLOAD_FOLDER"] != "/persistent/private"
    assert os.environ["DATABASE_URL"] == "postgresql://runtime/db"
    assert not Path(kwargs["env"]["UPLOAD_FOLDER"]).exists()
    monkeypatch.setenv("GRANT_RUNTIME_ROLE", "true")
    run.reset_mock()
    migrate.main()
    assert run.call_count == 2
    assert run.call_args.args[0][-1] == "grant-runtime"


def test_start_uses_platform_port_and_discards_migration_key(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://owner/db")
    run, execute = Mock(), Mock()
    monkeypatch.setattr(serve.subprocess, "run", run)
    monkeypatch.setattr(serve.os, "execvpe", execute)
    serve.main(skip_migrations=True)
    run.assert_not_called()
    executable, args, env = execute.call_args.args
    assert executable == "gunicorn"
    assert "0.0.0.0:8080" in args
    assert args[args.index("--workers") + 1] == "2"
    assert args[-1] == "wsgi:app"
    assert "MIGRATION_DATABASE_URL" not in env
    assert env["PYTHON_DOTENV_DISABLED"] == "1"
    monkeypatch.setenv("PORT", "invalid")
    with pytest.raises(ValueError, match="PORT"):
        serve.main()


def test_cdn_build_copies_assets_without_private_data(tmp_path):
    static = tmp_path / "app" / "static" / "css"
    static.mkdir(parents=True)
    (static / "app.css").write_text("body { color: black; }")
    (tmp_path / ".env").write_text("private configuration")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "private.pdf").write_bytes(b"private resume")
    build_vercel.build_static(tmp_path)
    files = [
        file.relative_to(tmp_path / "public").as_posix()
        for file in (tmp_path / "public").rglob("*")
        if file.is_file()
    ]
    assert files == ["static/css/app.css"]
