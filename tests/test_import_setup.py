"""Shared setup preserves one-time imports and explicit sync connections."""

import io

import pytest
import requests

from app.models import ImportBatch, JobApplication, SourceConnection
from tests.helpers import csrf_token


@pytest.mark.parametrize("mode", ["once", "sync"])
def test_google_setup_selects_import_or_connection(
    app, logged_client, users, monkeypatch, mode
):
    def sheet_response(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.raw = io.BytesIO(b"Role,Company\nEngineer,Example\n")
        return response

    monkeypatch.setattr(requests, "get", sheet_response)
    response = logged_client.post(
        "/imports",
        data={
            "csrf_token": csrf_token(logged_client, "/imports"),
            "source": "google",
            "sheet_access": "public",
            "import_mode": mode,
            "sheet_url": (
                "https://docs.google.com/spreadsheets/d/fictionalSheet12345"
                "/edit#gid=42"
            ),
            "name": "My tracker",
            "interval": "60",
        },
    )
    assert response.status_code == 302
    assert response.location.endswith("/map")
    with app.app_context():
        batch = ImportBatch.query.one()
        assert batch.user_id == users[0]
        assert JobApplication.query.count() == 0
        if mode == "once":
            assert batch.connection_id is None
            assert SourceConnection.query.count() == 0
        else:
            connection = SourceConnection.query.one()
            assert batch.connection_id == connection.id
            assert connection.user_id == users[0]
            assert connection.provider == "google_public"
            assert connection.interval_minutes == 60
            assert not connection.active


def test_setup_error_keeps_choices_and_does_not_create_connection(
    app, logged_client
):
    response = logged_client.post(
        "/imports",
        data={
            "csrf_token": csrf_token(logged_client, "/imports"),
            "source": "google",
            "sheet_access": "public",
            "import_mode": "sync",
            "name": "My tracker",
            "sheet_url": "https://example.com/invalid-sheet",
        },
    )
    assert response.status_code == 200
    assert b'value="google" selected' in response.data
    assert b'value="sync" selected' in response.data
    assert b'value="My tracker"' in response.data
    with app.app_context():
        assert SourceConnection.query.count() == 0
        assert ImportBatch.query.count() == 0


@pytest.mark.parametrize(
    "fields",
    [
        {"source": "google", "sheet_access": "invalid"},
        {"source": "google", "import_mode": "invalid"},
        {"source": "file", "import_mode": "sync"},
    ],
)
def test_invalid_setup_choices_do_not_create_previews(
    app, logged_client, fields
):
    response = logged_client.post(
        "/imports",
        data={"csrf_token": csrf_token(logged_client, "/imports"), **fields},
    )
    assert response.status_code == 200
    with app.app_context():
        assert ImportBatch.query.count() == 0
        assert SourceConnection.query.count() == 0
