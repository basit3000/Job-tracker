import csv
import io
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask_migrate import upgrade
from sqlalchemy import text

from app.extensions import db
from app.models import ChangeEntry, Device, JobApplication, User
from app.services import save_application
from tests.helpers import (
    MIGRATIONS,
    create_record,
    csrf_token,
    job_data,
    pair_device,
)


def test_observation_links_are_safe_on_browser_and_api_reads(
    app,
    logged_client,
    job,
    paired,
):
    with app.app_context():
        record = db.session.get(JobApplication, job)
        record.applicants = {
            "count": None,
            "relation": None,
            "label": None,
            "source": "Fictional source",
            "observedAt": None,
            "url": "javascript:alert('fictional')",
        }
        db.session.commit()
        public_id = record.public_id
    response = logged_client.get(f"/jobs/{job}")
    assert response.status_code == 200
    assert b"javascript:" not in response.data
    payload = logged_client.get(
        f"/api/v1/applications/{public_id}", headers=paired
    ).json
    assert payload["applicants"]["url"] is None
    assert payload["applicants"]["count"] is None


def test_private_signup_default_and_account_bootstrap(app_factory):
    app = app_factory(PUBLIC_SIGNUP_ENABLED=False)
    client = app.test_client()
    assert client.get("/register").status_code == 404
    assert client.post("/register", data={}).status_code == 400
    assert b'href="/register"' not in client.get("/").data
    assert b'href="/register"' not in client.get("/login").data
    result = app.test_cli_runner().invoke(
        args=["create-user", "--email", "bootstrap@example.com"],
        input="fictional-password\nfictional-password\n",
    )
    assert result.exit_code == 0, result.output
    assert "fictional-password" not in result.output
    with app.app_context():
        assert User.query.one().check_password("fictional-password")


def test_legacy_upgrade_preserves_identity_files_and_unknown_dates(
    app_factory,
):
    app = app_factory(migrate=False)
    with app.app_context():
        upgrade(directory=MIGRATIONS, revision="894a267eb935")
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user (id,email,password_hash) "
                    "VALUES (7,'legacy@example.com','fictional-hash')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO job_application "
                    "(id,job_title,company,status,user_id,resume_filename,"
                    "applied_date,updated_date) VALUES (9,'Legacy role',"
                    "'Example','Wishlist',7,'fictional.pdf',"
                    "'2026-01-02 12:00:00','2026-01-03 12:00:00')"
                )
            )
        upgrade(directory=MIGRATIONS)
        job = db.session.get(JobApplication, 9)
        assert job.user_id == 7
        assert job.status == "shortlisted"
        assert job.applied_on is None
        assert job.created_at.date().isoformat() == "2026-01-02"
        assert job.applied_date.date().isoformat() == "2026-01-02"
        assert job.resume_filename == "fictional.pdf"
        assert job.history == []
        assert job.public_id and job.version == 1
        assert ChangeEntry.query.one().payload["appliedDate"] is None


def test_unknown_legacy_status_aborts_upgrade_without_replacing_data(
    app_factory,
):
    app = app_factory(migrate=False)
    with app.app_context():
        upgrade(directory=MIGRATIONS, revision="894a267eb935")
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user (id,email,password_hash) "
                    "VALUES (1,'legacy@example.com','fictional-hash')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO job_application "
                    "(id,job_title,company,status,user_id) "
                    "VALUES (1,'Legacy role','Example','unexpected',1)"
                )
            )
        import pytest

        with pytest.raises(SystemExit):
            upgrade(directory=MIGRATIONS)
        with db.engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM job_application WHERE id=1")
                ).scalar_one()
                == "unexpected"
            )


def test_browser_version_checks_cover_edits_and_deletes(
    client, logged_client, app, users, job
):
    headers, _ = pair_device(client, app, users[0])
    with app.app_context():
        public_id = db.session.get(JobApplication, job).public_id
    token = csrf_token(logged_client, f"/jobs/{job}/edit")
    mutation = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": public_id,
        "expectedVersion": 1,
        "fields": {"status": "interviewing"},
    }
    assert (
        client.post(
            "/api/v1/mutations", headers=headers, json=mutation
        ).status_code
        == 200
    )
    edit = logged_client.post(
        f"/jobs/{job}/edit", data=job_data(csrf_token=token, version=1)
    )
    assert edit.status_code == 409
    assert b"Reload the current version" in edit.data
    deletion = logged_client.post(
        f"/jobs/{job}/delete", data={"csrf_token": token, "version": 1}
    )
    assert deletion.status_code == 409
    with app.app_context():
        item = db.session.get(JobApplication, job)
        assert item.status == "interviewing" and item.deleted_at is None
    assert (
        logged_client.post(
            f"/jobs/{job}/edit", data=job_data(csrf_token=token, version=None)
        ).status_code
        == 422
    )
    assert (
        logged_client.post(
            f"/jobs/{job}/edit", data=job_data(csrf_token=token, version="")
        ).status_code
        == 422
    )


def test_dates_followups_board_filters_and_pagination(
    logged_client, app, users
):
    today = datetime.now(timezone.utc).date()
    with app.app_context():
        for index in range(27):
            save_application(
                JobApplication(user_id=users[0]),
                {
                    "job_title": f"Role {index}",
                    "company": "Example",
                    "board": "Fictional board",
                    "status": "applied",
                    "applied_on": None,
                    "follow_up_on": today - timedelta(days=1),
                },
            )
        save_application(
            JobApplication(user_id=users[1]),
            {
                "job_title": "Other owner's role",
                "company": "Other private company",
                "status": "offer",
            },
        )
    for path in (
        "/dashboard",
        "/board",
        "/follow-ups",
        "/exports",
        "/integrations",
    ):
        result = logged_client.get(path)
        assert result.status_code == 200
        assert b"Other private company" not in result.data
    page = logged_client.get(
        "/jobs?company=Example&board=Fictional+board&due=overdue"
    )
    assert b"27 matching" in page.data
    assert b"Page 1 of 2" in page.data
    assert logged_client.get("/jobs?page=2").status_code == 200
    assert (
        b"No applications match"
        in logged_client.get("/jobs?board=Missing").data
    )
    assert b"Unknown dates: 27" in logged_client.get("/dashboard").data


def test_export_ownership_field_selection_and_formula_safety(
    logged_client, app, users
):
    with app.app_context():
        save_application(
            JobApplication(user_id=users[0]),
            {
                "job_title": "=1+1",
                "company": "Example",
                "status": "applied",
                "notes": "Fictional private note",
            },
        )
        save_application(
            JobApplication(user_id=users[1]),
            {
                "job_title": "Other private role",
                "company": "Example",
                "status": "applied",
            },
        )
    response = logged_client.get("/exports/json")
    records = json.loads(response.data)["applications"]
    assert len(records) == 1 and "note" not in records[0]
    assert records[0]["title"] == "=1+1"
    assert not {"resume_filename", "user_id", "token", "password_hash"} & set(
        records[0]
    )
    assert (
        json.loads(logged_client.get("/exports/json?fields=note").data)[
            "applications"
        ][0]["note"]
        == "Fictional private note"
    )
    rows = list(
        csv.DictReader(
            io.StringIO(
                logged_client.get("/exports/csv?fields=title").data.decode()
            )
        )
    )
    assert rows[0]["title"] == "'=1+1"
    assert (
        logged_client.get("/exports/json?fields=resume_filename").status_code
        == 422
    )


def test_pairing_ui_requires_csrf_and_cross_account_revocation_is_denied(
    logged_client, client, app, users
):
    pairing = client.post(
        "/api/v1/pairings",
        json={
            "installationId": "fictional-installation",
            "name": "Example client",
        },
    ).json
    assert (
        logged_client.post(
            "/integrations",
            data={"code": pairing["userCode"], "action": "approve"},
        ).status_code
        == 400
    )
    token = csrf_token(logged_client, "/integrations")
    inspected = logged_client.post(
        "/integrations",
        data={"code": pairing["userCode"], "csrf_token": token},
    )
    assert b"Example client" in inspected.data
    approved = logged_client.post(
        "/integrations",
        data={
            "code": pairing["userCode"],
            "csrf_token": token,
            "action": "approve",
            "optional_fields": ["note"],
        },
    )
    assert approved.status_code == 302
    result = client.post(
        "/api/v1/pairings/redeem",
        json={key: pairing[key] for key in ("pairingId", "pairingSecret")},
    )
    assert result.json["optionalFields"] == ["note"]
    other = app.test_client()
    with other.session_transaction() as session:
        session["_user_id"] = str(users[1])
        session["_fresh"] = True
    other_token = csrf_token(other, "/integrations")
    assert (
        other.post(
            f"/integrations/devices/{result.json['deviceId']}/revoke",
            data={"csrf_token": other_token},
        ).status_code
        == 404
    )
    assert (
        logged_client.post(
            f"/integrations/devices/{result.json['deviceId']}/revoke",
            data={"csrf_token": token},
        ).status_code
        == 302
    )
    assert (
        client.get(
            "/api/v1/device",
            headers={"Authorization": f"Bearer {result.json['token']}"},
        ).status_code
        == 401
    )


def test_server_observed_errors_are_codes_and_success_clears_them(
    client, app, users, logged_client
):
    headers, device_id = pair_device(client, app, users[0])
    record, _ = create_record(client, headers)
    body = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": record["id"],
        "expectedVersion": 2,
        "fields": {"status": "offer"},
    }
    assert (
        client.post(
            "/api/v1/mutations", headers=headers, json=body
        ).status_code
        == 409
    )
    with app.app_context():
        assert (
            db.session.get(Device, device_id).last_error_code
            == "version_conflict"
        )
    assert b"version_conflict" in logged_client.get("/integrations").data
    assert client.get("/api/v1/device", headers=headers).status_code == 200
    with app.app_context():
        assert db.session.get(Device, device_id).last_error_code is None


def test_seed_refuses_existing_and_production_databases(app_factory):
    app = app_factory()
    result = app.test_cli_runner().invoke(
        args=["seed-demo", "--confirm-fictional"]
    )
    assert result.exit_code != 0
    with app.app_context():
        assert User.query.count() == 0
