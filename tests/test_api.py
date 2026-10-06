from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.contracts import DEFAULT_FIELDS, OPTIONAL_FIELDS
from app.devices import approve_pairing
from app.extensions import db
from app.models import (
    ApplicationMapping,
    ChangeEntry,
    Device,
    JobApplication,
    MutationReceipt,
    PairingRequest,
    StatusEvent,
)
from tests.helpers import create_record, pair_device


def test_device_api_does_not_accept_browser_sessions(logged_client):
    for path in ("/applications", "/changes", "/device"):
        result = logged_client.get("/api/v1" + path)
        assert result.status_code == 401
        assert result.is_json
    assert logged_client.post("/api/v1/mutations", json={}).status_code == 401


def test_pairing_pending_single_use_hashes_and_expiry(client, app, users):
    result = client.post(
        "/api/v1/pairings",
        json={"installationId": "fictional", "name": "Client"},
    ).json
    redeem = {key: result[key] for key in ("pairingId", "pairingSecret")}
    assert (
        client.post("/api/v1/pairings/redeem", json=redeem).json["error"][
            "code"
        ]
        == "approval_pending"
    )
    wrong = {**redeem, "pairingSecret": "x" * 43}
    assert (
        client.post("/api/v1/pairings/redeem", json=wrong).status_code == 401
    )
    with app.app_context():
        row = db.session.get(PairingRequest, result["pairingId"])
        assert row.secret_hash != result["pairingSecret"]
        assert row.code_hash != result["userCode"]
        approve_pairing(users[0], result["userCode"], [])
    token = client.post("/api/v1/pairings/redeem", json=redeem).json["token"]
    with app.app_context():
        assert Device.query.one().token_hash != token
    assert (
        client.post("/api/v1/pairings/redeem", json=redeem).status_code == 410
    )


def test_api_requires_https_outside_explicit_loopback(client, app):
    app.config["ALLOW_INSECURE_LOCAL_API"] = False
    result = client.post(
        "/api/v1/pairings",
        json={"installationId": "fictional", "name": "Client"},
    )
    assert result.status_code == 400
    app.config["ALLOW_INSECURE_LOCAL_API"] = True
    result = client.post(
        "/api/v1/pairings",
        json={"installationId": "fictional", "name": "Client"},
        environ_overrides={"REMOTE_ADDR": "198.51.100.4"},
    )
    assert result.status_code == 400


def test_retry_is_idempotent_and_changed_payload_is_rejected(
    client, app, paired
):
    record, body = create_record(client, paired)
    replay = client.post("/api/v1/mutations", json=body, headers=paired)
    assert replay.json["application"] == record
    changed = {**body, "fields": {**body["fields"], "title": "Changed"}}
    assert (
        client.post(
            "/api/v1/mutations", json=changed, headers=paired
        ).status_code
        == 409
    )
    with app.app_context():
        assert JobApplication.query.count() == 1
        assert StatusEvent.query.count() == 1
        assert ChangeEntry.query.count() == 1
        assert MutationReceipt.query.count() == 1


def test_api_dates_status_history_conflict_and_followups(client, app, paired):
    record, _ = create_record(
        client, paired, appliedDate=None, followUpDate="2026-12-01"
    )
    assert record["appliedDate"] is None
    update = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": record["id"],
        "expectedVersion": 1,
        "fields": {"status": "accepted", "appliedDate": "2026-10-06"},
    }
    changed = client.post("/api/v1/mutations", json=update, headers=paired)
    assert changed.status_code == 200
    assert changed.json["application"]["followUpDate"] is None
    assert changed.json["application"]["version"] == 2
    assert len(changed.json["application"]["statusHistory"]) == 2
    stale = {
        **update,
        "mutationId": str(uuid4()),
        "fields": {"status": "offer"},
    }
    result = client.post("/api/v1/mutations", json=stale, headers=paired)
    assert result.status_code == 409
    assert result.json["error"]["current"]["status"] == "accepted"
    with app.app_context():
        assert StatusEvent.query.count() == 2
        assert JobApplication.query.one().status == "accepted"


@pytest.mark.parametrize(
    "name",
    [
        "note",
        "contactName",
        "contactEmail",
        "contactPhone",
        "salary",
        "memory",
        "answers",
        "resume_filename",
        "user_id",
        "prepPath",
        "attachments",
    ],
)
def test_default_scope_rejects_private_and_unknown_fields(
    client, paired, name
):
    response = client.post(
        "/api/v1/mutations",
        headers=paired,
        json={
            "mutationId": str(uuid4()),
            "operation": "create",
            "fields": {
                "title": "Engineer",
                "company": "Example",
                name: "fictional",
            },
        },
    )
    assert response.status_code == 422


def test_scope_applies_to_reads_conflicts_and_changes(
    client, app, users, paired
):
    full, _ = pair_device(
        client,
        app,
        users[0],
        optional=OPTIONAL_FIELDS,
        installation="another-fictional-installation",
    )
    record, _ = create_record(
        client,
        full,
        note="Fictional private detail",
        contactEmail="contact@example.com",
        salary="Example salary",
    )
    fetched = client.get(
        f"/api/v1/applications/{record['id']}", headers=paired
    ).json
    assert not OPTIONAL_FIELDS & set(fetched)
    snapshot = client.get("/api/v1/applications", headers=paired).json
    assert not OPTIONAL_FIELDS & set(snapshot["entries"][0]["application"])
    stale = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": record["id"],
        "expectedVersion": 2,
        "fields": {"status": "offer"},
    }
    result = client.post("/api/v1/mutations", json=stale, headers=paired)
    assert not OPTIONAL_FIELDS & set(result.json["error"]["current"])


def test_omitted_optional_field_is_preserved_and_explicit_null_clears(
    client, app, users
):
    headers, _ = pair_device(client, app, users[0], optional=["note"])
    record, _ = create_record(client, headers, note="Fictional note")
    body = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": record["id"],
        "expectedVersion": 1,
        "fields": {"status": "offer"},
    }
    result = client.post("/api/v1/mutations", json=body, headers=headers).json[
        "application"
    ]
    assert result["note"] == "Fictional note"
    body.update(
        mutationId=str(uuid4()), expectedVersion=2, fields={"note": None}
    )
    assert (
        client.post("/api/v1/mutations", json=body, headers=headers).json[
            "application"
        ]["note"]
        is None
    )


def test_cross_account_ids_mappings_devices_and_cursors_are_isolated(
    client, app, users, paired
):
    record, _ = create_record(client, paired)
    other, _ = pair_device(client, app, users[1])
    assert (
        client.get(
            f"/api/v1/applications/{record['id']}", headers=other
        ).status_code
        == 404
    )
    mutation = {
        "mutationId": str(uuid4()),
        "operation": "delete",
        "applicationId": record["id"],
        "expectedVersion": 1,
    }
    assert (
        client.post(
            "/api/v1/mutations", json=mutation, headers=other
        ).status_code
        == 404
    )
    assert client.get("/api/v1/changes", headers=other).json["entries"] == []
    cursor = client.get("/api/v1/changes", headers=paired).json["cursor"]
    assert (
        client.get(
            "/api/v1/changes", query_string={"cursor": cursor}, headers=other
        ).status_code
        == 422
    )
    forged = {
        "mutationId": str(uuid4()),
        "operation": "create",
        "user_id": users[0],
        "fields": {"title": "Role", "company": "Example"},
    }
    assert (
        client.post(
            "/api/v1/mutations", json=forged, headers=other
        ).status_code
        == 422
    )


def test_stable_snapshot_then_concurrent_changes_resume_without_gaps(
    client, paired
):
    first, _ = create_record(client, paired)
    second, _ = create_record(client, paired, title="Second")
    page = client.get("/api/v1/applications?limit=1", headers=paired).json
    assert page["hasMore"]
    third, _ = create_record(client, paired, title="Third")
    body = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": first["id"],
        "expectedVersion": 1,
        "fields": {"status": "interviewing"},
    }
    assert (
        client.post("/api/v1/mutations", headers=paired, json=body).status_code
        == 200
    )
    resumed = client.get(
        "/api/v1/applications",
        query_string={"cursor": page["cursor"], "limit": 1},
        headers=paired,
    ).json
    assert not resumed["hasMore"]
    assert {
        page["entries"][0]["application"]["id"],
        resumed["entries"][0]["application"]["id"],
    } == {first["id"], second["id"]}
    delta = client.get(
        "/api/v1/changes",
        query_string={"cursor": resumed["changesCursor"], "limit": 1},
        headers=paired,
    ).json
    retry = client.get(
        "/api/v1/changes",
        query_string={"cursor": resumed["changesCursor"], "limit": 1},
        headers=paired,
    ).json
    assert retry["entries"] == delta["entries"]
    assert delta["hasMore"]
    end = client.get(
        "/api/v1/changes",
        query_string={"cursor": delta["cursor"], "limit": 1},
        headers=paired,
    ).json
    assert not end["hasMore"]
    assert {
        delta["entries"][0]["application"]["id"],
        end["entries"][0]["application"]["id"],
    } == {first["id"], third["id"]}


def test_deletion_retry_tombstone_and_mapping_prevent_resurrection(
    client, app, paired
):
    body = {
        "mutationId": str(uuid4()),
        "operation": "create",
        "localRecordId": "manual:application:fictional",
        "fields": {"title": "Role", "company": "Example"},
    }
    record = client.post("/api/v1/mutations", headers=paired, json=body).json[
        "application"
    ]
    deletion = {
        "mutationId": str(uuid4()),
        "operation": "delete",
        "applicationId": record["id"],
        "expectedVersion": 1,
    }
    deleted = client.post("/api/v1/mutations", headers=paired, json=deletion)
    assert deleted.json["application"]["deletedAt"]
    assert "title" not in deleted.json["application"]
    assert (
        client.post("/api/v1/mutations", headers=paired, json=deletion).json
        == deleted.json
    )
    assert (
        client.post(
            "/api/v1/mutations",
            headers=paired,
            json={**body, "mutationId": str(uuid4())},
        ).status_code
        == 409
    )
    update = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": record["id"],
        "expectedVersion": 2,
        "fields": {"status": "applied"},
    }
    assert (
        client.post(
            "/api/v1/mutations", headers=paired, json=update
        ).status_code
        == 409
    )
    assert client.get("/api/v1/applications", headers=paired).json["entries"][
        0
    ]["application"]["deletedAt"]
    with app.app_context():
        assert JobApplication.query.one().deleted_at
        assert JobApplication.for_user(Device.query.one().user_id).count() == 0


def test_cloud_created_record_can_map_without_company_title_merging(
    client, app, paired
):
    first, _ = create_record(client, paired)
    second, _ = create_record(client, paired)
    assert first["id"] != second["id"]
    body = {
        "mutationId": str(uuid4()),
        "operation": "map",
        "applicationId": first["id"],
        "expectedVersion": 1,
        "localRecordId": "board:opaque/id:42",
    }
    result = client.post("/api/v1/mutations", json=body, headers=paired)
    assert result.status_code == 200
    assert (
        result.json["application"]["mappings"][0]["localRecordId"]
        == "board:opaque/id:42"
    )
    body.update(mutationId=str(uuid4()), applicationId=second["id"])
    assert (
        client.post("/api/v1/mutations", json=body, headers=paired).status_code
        == 409
    )
    with app.app_context():
        assert ApplicationMapping.query.count() == 1


def test_source_history_is_deduplicated_and_content_change_conflicts(
    client, app, paired
):
    record, _ = create_record(client, paired)
    history = [
        {
            "sourceEventId": "fictional-event",
            "fromStatus": "shortlisted",
            "status": "applied",
            "occurredAt": None,
        }
    ]
    body = {
        "mutationId": str(uuid4()),
        "operation": "update",
        "applicationId": record["id"],
        "expectedVersion": 1,
        "statusHistory": history,
    }
    result = client.post("/api/v1/mutations", json=body, headers=paired)
    assert result.status_code == 200
    body.update(mutationId=str(uuid4()), expectedVersion=2)
    assert (
        client.post("/api/v1/mutations", json=body, headers=paired).json[
            "application"
        ]["version"]
        == 2
    )
    body.update(
        mutationId=str(uuid4()),
        statusHistory=[{**history[0], "status": "offer"}],
    )
    assert (
        client.post("/api/v1/mutations", json=body, headers=paired).status_code
        == 409
    )
    with app.app_context():
        assert StatusEvent.query.count() == 2


def test_device_revocation_is_immediate(client, paired):
    assert (
        client.post("/api/v1/device/revoke", headers=paired).status_code == 200
    )
    assert (
        client.get("/api/v1/applications", headers=paired).status_code == 401
    )
    assert (
        client.post("/api/v1/mutations", json={}, headers=paired).status_code
        == 401
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"appliedDate": "2026-02-30"},
        {"appliedDate": "2026-01-01T00:00:00Z"},
        {"postedAt": "2026-01-01T00:00:00"},
        {"postedAtApproximate": True},
        {"url": "javascript://example.com/x"},
        {"status": "Applied"},
        {"applicants": {"count": True}},
        {"applicants": {"count": -1}},
        {"applicants": {"count": 20, "relation": "exact"}},
        {"applicants": {"count": 20, "relation": {}}},
        {
            "applicants": {
                "count": 20,
                "relation": "exact",
                "source": "Example",
                "observedAt": "bad",
            }
        },
    ],
)
def test_api_field_validation_rejects_invalid_values(client, paired, fields):
    result = client.post(
        "/api/v1/mutations",
        headers=paired,
        json={
            "operation": "create",
            "mutationId": str(uuid4()),
            "fields": {"title": "Role", "company": "Example", **fields},
        },
    )
    assert result.status_code == 422


def test_observations_preserve_unknown_counts_and_provenance(client, paired):
    record, _ = create_record(
        client, paired, applicants={"count": None, "source": "Example board"}
    )
    assert record["applicants"]["count"] is None
    assert record["applicants"]["observedAt"] is None
    known, _ = create_record(
        client,
        paired,
        applicants={
            "count": 20,
            "relation": "at-least",
            "source": "Example board",
            "url": "https://example.com/jobs",
            "observedAt": "2026-10-06T12:00:00+02:00",
        },
    )
    assert known["applicants"]["observedAt"] == "2026-10-06T10:00:00Z"


def test_failed_commit_rolls_back_record_history_feed_receipt(
    client, app, paired, monkeypatch
):
    def fail():
        raise SQLAlchemyError("Fictional database failure")

    monkeypatch.setattr(db.session, "commit", fail)
    result = client.post(
        "/api/v1/mutations",
        headers=paired,
        json={
            "operation": "create",
            "mutationId": str(uuid4()),
            "fields": {"title": "Role", "company": "Example"},
        },
    )
    assert result.status_code == 503
    with app.app_context():
        assert all(
            model.query.count() == 0
            for model in (
                JobApplication,
                StatusEvent,
                ChangeEntry,
                MutationReceipt,
            )
        )


def test_request_limits_and_schema_endpoint(client, app, paired):
    result = client.post(
        "/api/v1/mutations",
        headers=paired,
        data="x" * (app.config["API_MAX_CONTENT_LENGTH"] + 1),
        content_type="application/json",
    )
    assert result.status_code == 413
    assert result.is_json
    schema = client.get("/api/v1/openapi.json").json
    assert schema["openapi"] == "3.1.0"
    assert (
        set(schema["components"]["schemas"]["Fields"]["properties"])
        == DEFAULT_FIELDS | OPTIONAL_FIELDS
    )
