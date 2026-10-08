"""Real migrations, routes and transactions with fictional external records."""

import io
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from cryptography.fernet import Fernet

from app.contracts import ServiceError
from app.extensions import db
from app.import_readers import read_file
from app.import_service import (
    commit_batch,
    initial_options,
    options_digest,
    preview,
    save_options,
)
from app.models import (
    ChangeEntry,
    ImportBatch,
    JobApplication,
    SourceConnection,
    SourceRecord,
    StatusEvent,
    _utcnow,
)
from app.record_updates import (
    lock_account,
    tombstone_application,
    write_application,
)
from app.source_connections import (
    connection_batch,
    create_connection,
    fetch_tables,
    get_connection,
    remove_connection,
    set_schedule,
)
from app.source_credentials import decrypt_credential
from app.source_scheduler import run_due_syncs
from tests.google_provider import (
    BASE_URL,
    GOOGLE_CONFIG,
    mock_google_transport,
)
from tests.helpers import csrf_token

REFERENCE = {"id": "fictionalSheet12345", "published": False, "gid": "42"}
CSV = (
    b"ID,Role,Company,Stage,Notes,Link\n"
    b"job-1,Engineer,Example,Applied,Source note,https://example.com/job\n"
)


def fixture_response(value, status=200):
    result = requests.Response()
    result.status_code = status
    result.raw = io.BytesIO(
        value if isinstance(value, bytes) else json.dumps(value).encode()
    )
    return result


def new_source(user_id):
    return create_connection(
        user_id, "Fictional sheet", "google_public", dict(REFERENCE)
    )


def batch_for(connection, data=CSV):
    batch = connection_batch(
        connection,
        tables=read_file(data, "jobs.csv"),
        remap=not connection.options,
    )
    options = (
        dict(connection.options)
        if connection.options
        else initial_options(batch)
    )
    options["identity_column"] = 0
    save_options(batch, options)
    return batch


def confirm(batch):
    return commit_batch(batch.user_id, batch.id, options_digest(batch.options))


def test_repeat_sync_updates_reordered_rows_without_duplicates_and_emits_feed(
    app, users
):
    with app.app_context():
        source = new_source(users[0])
        batch = batch_for(source)
        digest = options_digest(batch.options)
        assert confirm(batch)["created"] == 1
        assert commit_batch(users[0], batch.id, digest)["created"] == 1
        assert confirm(batch_for(source))["unchanged"] == 1
        assert JobApplication.query.count() == 1
        assert ChangeEntry.query.count() == 1
        updated = CSV.replace(b"Engineer", b"Senior engineer").replace(
            b"Applied", b"Interview"
        )
        result = confirm(batch_for(source, updated))
        assert result["updated"] == 1
        job = JobApplication.query.one()
        assert (
            job.job_title == "Senior engineer" and job.status == "interviewing"
        )
        assert job.version == 2
        assert SourceRecord.query.count() == 1
        assert {entry.source for entry in ChangeEntry.query.all()} == {
            "source_sync"
        }
        assert (
            StatusEvent.query.order_by(StatusEvent.id.desc()).first().source
            == "source_sync"
        )
        assert db.session.get(ImportBatch, batch.id).payload is None


def test_conflicting_local_edits_are_preserved_while_other_fields_update(
    app, users
):
    with app.app_context():
        source = new_source(users[0])
        confirm(batch_for(source))
        job = JobApplication.query.one()
        lock_account(users[0])
        write_application(
            job,
            {"notes": "My private local note", "status": "offer"},
            version=job.version,
        )
        db.session.commit()
        changed = (
            CSV.replace(b"Engineer", b"Senior engineer")
            .replace(b"Applied", b"Interview")
            .replace(b"Source note", b"New source note")
        )
        batch = batch_for(source, changed)
        rows, counts = preview(batch, batch.options)
        assert counts["conflicts"] == 1 and counts["updated"] == 1
        assert set(rows[0]["conflicts"]) == {"Status", "Notes"}
        assert confirm(batch)["conflicts"] == 1
        assert job.notes == "My private local note" and job.status == "offer"
        assert job.job_title == "Senior engineer"
        assert confirm(batch_for(source, changed))["conflicts"] == 1


def test_blanks_clear_mapped_fields_but_unmapped_fields_stay_local(app, users):
    with app.app_context():
        source = new_source(users[0])
        data = b"ID,Role,Company,Notes\njob-1,Engineer,Example,Source note\n"
        confirm(batch_for(source, data))
        job = JobApplication.query.one()
        lock_account(users[0])
        write_application(
            job,
            {"status": "applied", "salary": "Local salary"},
            version=job.version,
        )
        db.session.commit()
        confirm(batch_for(source, data.replace(b"Source note", b"")))
        assert job.notes is None
        assert job.status == "applied" and job.salary == "Local salary"


def test_missing_source_rows_and_deleted_tracker_jobs_are_never_resurrected(
    app, users
):
    with app.app_context():
        source = new_source(users[0])
        confirm(batch_for(source))
        job = JobApplication.query.one()
        lock_account(users[0])
        tombstone_application(job, job.version)
        db.session.commit()
        assert confirm(batch_for(source))["deleted"] == 1
        header = CSV.splitlines(keepends=True)[0]
        assert confirm(batch_for(source, header))["missing"] == 1
        assert job.deleted_at and JobApplication.query.count() == 1


def test_initial_sync_links_existing_account_job_without_overwriting_it(
    app, users
):
    with app.app_context():
        job = JobApplication(
            user_id=users[0],
            job_title="Engineer",
            company="Example",
            job_url="https://example.com/job",
            status="offer",
            notes="Local",
        )
        other = JobApplication(
            user_id=users[1],
            job_title="Engineer",
            company="Example",
            job_url="https://example.com/job",
            status="rejected",
        )
        db.session.add_all([job, other])
        db.session.commit()
        result = confirm(batch_for(new_source(users[0])))
        assert result["linked"] == 1 and result["conflicts"] == 1
        assert job.notes == "Local" and job.status == "offer"
        assert SourceRecord.query.one().application_id == job.id
        assert JobApplication.query.count() == 2


def test_duplicate_or_empty_source_ids_block_atomic_sync(app, users):
    with app.app_context():
        source = new_source(users[0])
        batch = batch_for(source, CSV + CSV.splitlines(keepends=True)[1])
        assert preview(batch, batch.options)[1]["invalid"] == 2
        with pytest.raises(ServiceError, match="invalid rows"):
            confirm(batch)
        assert JobApplication.query.count() == SourceRecord.query.count() == 0
        empty = batch_for(source, CSV.replace(b"job-1", b""))
        with pytest.raises(ServiceError):
            confirm(empty)
        assert JobApplication.query.count() == 0


def test_distinct_source_ids_cannot_attach_to_the_same_existing_job(
    app, users
):
    with app.app_context():
        job = JobApplication(
            user_id=users[0],
            job_title="Engineer",
            company="Example",
            job_url="https://example.com/job",
            status="applied",
        )
        db.session.add(job)
        db.session.commit()
        data = CSV + CSV.splitlines(keepends=True)[1].replace(
            b"job-1", b"job-2"
        )
        result = confirm(batch_for(new_source(users[0]), data))
        assert result["linked"] == 1 and result["created"] == 1
        assert (
            len({record.application_id for record in SourceRecord.query.all()})
            == 2
        )


def test_source_sync_feed_matches_the_published_schema(
    app, users, client, paired
):
    from tests.test_api_schema import validator

    with app.app_context():
        confirm(batch_for(new_source(users[0])))
    document = client.get("/api/v1/openapi.json").json
    result = client.get("/api/v1/changes", headers=paired)
    assert result.status_code == 200
    validator(document, "FeedPage").validate(result.json)
    assert result.json["entries"][0]["source"] == "source_sync"


def test_private_google_refresh_cannot_redirect_credentials(
    app, users, monkeypatch
):
    from app.source_credentials import encrypt_credential

    app.config["SYNC_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return fixture_response({"message": "fictional-sensitive-token"}, 302)

    monkeypatch.setattr(requests, "post", post)
    with app.app_context():
        source = create_connection(
            users[0], "Private", "google_private", dict(REFERENCE)
        )
        source.credential_ciphertext = encrypt_credential(
            source, "fictional-sensitive-token"
        )
        db.session.commit()
        with pytest.raises(ServiceError) as error:
            fetch_tables(source)
        assert "fictional-sensitive-token" not in str(error.value)
    assert len(calls) == 1
    assert calls[0][0] == "https://oauth2.googleapis.com/token"
    assert calls[0][1]["allow_redirects"] is False


def test_sync_failure_rolls_back_jobs_links_feed_and_receipt(
    app, users, monkeypatch
):
    from app import source_merge

    with app.app_context():
        source = new_source(users[0])
        data = CSV + CSV.splitlines(keepends=True)[1].replace(
            b"job-1", b"job-2"
        ).replace(b"Engineer", b"Developer")
        batch = batch_for(source, data)
        original, calls = source_merge.write_application, []

        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("fictional failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(source_merge, "write_application", fail_second)
        with pytest.raises(RuntimeError):
            confirm(batch)
        assert (
            JobApplication.query.count()
            == SourceRecord.query.count()
            == ChangeEntry.query.count()
            == 0
        )
        assert batch.payload and not batch.result and not source.active
        monkeypatch.setattr(source_merge, "write_application", original)
        assert confirm(batch)["created"] == 2


def test_stale_preview_and_layout_drift_require_review(app, users):
    with app.app_context():
        source = new_source(users[0])
        first, second = batch_for(source), batch_for(source)
        confirm(first)
        with pytest.raises(ServiceError, match="source changed"):
            confirm(second)
        with pytest.raises(ServiceError, match="columns changed"):
            connection_batch(
                source,
                tables=read_file(
                    CSV.replace(b"Role", b"New title"), "jobs.csv"
                ),
            )


def test_row_reordering_follows_explicit_ids(app, users):
    with app.app_context():
        source = new_source(users[0])
        header, first = CSV.splitlines(keepends=True)
        second = first.replace(b"job-1", b"job-2").replace(
            b"Engineer", b"Developer"
        )
        confirm(batch_for(source, header + first + second))
        ids = {job.job_title: job.id for job in JobApplication.query.all()}
        result = confirm(
            batch_for(
                source, header + second + first.replace(b"Engineer", b"Senior")
            )
        )
        assert result["updated"] == 1 and result["created"] == 0
        assert (
            JobApplication.query.filter_by(job_title="Senior").one().id
            == ids["Engineer"]
        )


def test_notion_stable_ids_and_credentials_are_encrypted_bound_and_removed(
    app, users
):
    app.config["SYNC_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    token = "fictional-private-notion-token"
    with app.app_context():
        source = create_connection(
            users[0],
            "Notion",
            "notion",
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "kind": "data_source",
            },
            token=token,
        )
        assert token not in source.credential_ciphertext
        assert decrypt_credential(source) == token
        other = create_connection(
            users[1],
            "Other",
            "notion",
            source.reference,
            token="fictional-other-token",
        )
        other.credential_ciphertext = source.credential_ciphertext
        db.session.commit()
        with pytest.raises(ServiceError, match="Reconnect"):
            decrypt_credential(other)
        tables = read_file(b"Role,Company\nEngineer,Example", "jobs.csv")
        tables[0]["row_ids"] = [None, "fictional-stable-page-id"]
        batch = connection_batch(source, tables=tables)
        save_options(batch, initial_options(batch))
        confirm(batch)
        tables[0]["rows"][1][0] = "Senior engineer"
        batch = connection_batch(source, tables=tables)
        assert confirm(batch)["updated"] == 1
        remove_connection(users[0], source.id)
        assert JobApplication.query.count() == 1
        assert SourceRecord.query.filter_by(user_id=users[0]).count() == 0
        assert ImportBatch.query.filter_by(user_id=users[0]).count() == 0


def test_ownership_csrf_and_private_credentials_missing_configuration(
    app, logged_client, users
):
    with app.app_context():
        source = new_source(users[1])
        source_id = source.id
        with pytest.raises(ServiceError, match="encryption key"):
            create_connection(
                users[0],
                "Private",
                "notion",
                {"id": "irrelevant"},
                token="fictional-token",
            )
        with pytest.raises(ServiceError) as error:
            get_connection(users[0], source_id)
        assert error.value.status == 404
    assert logged_client.post("/sources", data={}).status_code == 400
    token = csrf_token(logged_client, "/sources")
    for action in ("read", "schedule", "disconnect"):
        result = logged_client.post(
            f"/sources/{source_id}/{action}", data={"csrf_token": token}
        )
        assert result.status_code == 404


def test_due_worker_runs_only_opted_in_sources_and_leaves_no_source_previews(
    app, users, monkeypatch
):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: fixture_response(CSV.replace(b"Engineer", b"Senior")),
    )
    with app.app_context():
        source = new_source(users[0])
        confirm(batch_for(source))
        set_schedule(users[0], source.id, 15)
        source.next_sync_at = _utcnow() - timedelta(minutes=1)
        db.session.commit()
        manual = new_source(users[1])
        confirm(batch_for(manual))
        assert run_due_syncs() == {"synced": 1, "failed": 0}
        assert run_due_syncs() == {"synced": 0, "failed": 0}
        assert JobApplication.for_user(users[0]).one().job_title == "Senior"
        assert JobApplication.for_user(users[1]).one().job_title == "Engineer"
        assert all(batch.payload is None for batch in ImportBatch.query.all())


def test_worker_bad_rows_leave_jobs_unchanged_and_clear_failed_preview(
    app, users, monkeypatch
):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: fixture_response(
            CSV.replace(b"https://example.com/job", b"javascript:evil")
        ),
    )
    with app.app_context():
        source = new_source(users[0])
        confirm(batch_for(source))
        set_schedule(users[0], source.id, 15)
        source.next_sync_at = _utcnow() - timedelta(minutes=1)
        db.session.commit()
        assert run_due_syncs() == {"synced": 0, "failed": 1}
        assert source.last_error and JobApplication.query.one().version == 1
        assert all(batch.payload is None for batch in ImportBatch.query.all())


def test_public_source_routes_connect_map_review_confirm_disconnect(
    app, logged_client, users, monkeypatch
):
    monkeypatch.setattr(requests, "get", lambda *a, **k: fixture_response(CSV))
    result = logged_client.post(
        "/sources",
        data={
            "name": "My sheet",
            "provider": "google_public",
            "interval": "0",
            "sheet_url": "https://docs.google.com/spreadsheets/d/fictionalSheet12345/edit#gid=42",
            "csrf_token": csrf_token(logged_client, "/sources"),
        },
    )
    assert result.status_code == 302 and result.location.endswith("/map")
    assert b"unique ID" in logged_client.get(result.location).data
    with app.app_context():
        batch = ImportBatch.query.one()
        options = initial_options(batch)
        options["identity_column"] = 0
        save_options(batch, options)
        batch_id, source_id = batch.id, batch.connection_id
    review = logged_client.get(f"/imports/{batch_id}/review")
    assert b"Review source sync" in review.data and b"Create" in review.data
    with app.app_context():
        digest = options_digest(db.session.get(ImportBatch, batch_id).options)
    result = logged_client.post(
        f"/imports/{batch_id}/confirm",
        data={
            "digest": digest,
            "csrf_token": csrf_token(
                logged_client, f"/imports/{batch_id}/review"
            ),
        },
        follow_redirects=True,
    )
    assert b"Sync complete" in result.data
    result = logged_client.post(
        f"/sources/{source_id}/disconnect",
        data={"csrf_token": csrf_token(logged_client, "/sources")},
    )
    assert result.status_code == 302
    with app.app_context():
        assert (
            SourceConnection.query.count() == 0
            and JobApplication.query.count() == 1
        )


@pytest.mark.parametrize("setup_path", ["/sources", "/imports"])
def test_google_sync_requests_offline_scope_and_never_saves_tokens_in_cookie(
    app_factory, monkeypatch, setup_path
):
    app = app_factory(
        **GOOGLE_CONFIG, SYNC_ENCRYPTION_KEY=Fernet.generate_key().decode()
    )
    from app.models import User

    with app.app_context():
        user = User(email="fictional-sync@example.com")
        user.set_password("fictional-password")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
    provider = mock_google_transport(monkeypatch)
    start = client.post(
        setup_path,
        base_url=BASE_URL,
        data={
            "name": "Private sheet",
            "provider": "google_private",
            "source": "google",
            "sheet_access": "private",
            "import_mode": "sync",
            "interval": "0",
            "sheet_url": "https://docs.google.com/spreadsheets/d/fictionalSheet12345/edit#gid=42",
            "cell_range": "B4:C5",
            "intent": "signin",
            "csrf_token": csrf_token(client, "/sources"),
        },
    )
    params = {
        key: value[0]
        for key, value in parse_qs(urlsplit(start.location).query).items()
    }
    assert params["access_type"] == "offline" and "consent" in params["prompt"]
    assert "spreadsheets.readonly" in params["scope"]
    code = provider.issue(
        params["nonce"], code_challenge=params["code_challenge"]
    )
    provider.codes[code]["refresh_token"] = "fictional-google-refresh-token"

    def sheets_get(url, **kwargs):
        if "/values/" not in url:
            return fixture_response(
                {"sheets": [{"properties": {"sheetId": 42, "title": "Jobs"}}]}
            )
        return fixture_response(
            {"values": [["Role", "Company"], ["Engineer", "Example"]]}
        )

    monkeypatch.setattr(requests, "get", sheets_get)
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: fixture_response(
            {"access_token": "fictional-access-token"}
        ),
    )
    result = client.get(
        "/auth/google/callback",
        base_url=BASE_URL,
        query_string={"state": params["state"], "code": code},
    )
    assert result.status_code == 302 and result.location.endswith("/map")
    with client.session_transaction() as session:
        assert session["_user_id"] == str(user_id)
        assert "fictional-google-refresh-token" not in json.dumps(
            dict(session)
        )
        assert "fictional-access-token" not in json.dumps(dict(session))
    with app.app_context():
        connection = SourceConnection.query.one()
        assert (
            decrypt_credential(connection) == "fictional-google-refresh-token"
        )
        assert (
            "fictional-google-refresh-token"
            not in connection.credential_ciphertext
        )
        assert ImportBatch.query.one().payload[0]["start_row"] == 4
