import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.api_schema import openapi_document
from app.devices import approve_pairing
from tests.helpers import create_record


def validator(document, name):
    return Draft202012Validator(
        {
            "$ref": f"#/components/schemas/{name}",
            "components": document["components"],
        },
        format_checker=FormatChecker(),
    )


def test_schema_components_and_actual_pairing_crud_feed_responses(
    client,
    app,
    users,
):
    document = client.get("/api/v1/openapi.json").json
    for schema in document["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)
    pairing = client.post(
        "/api/v1/pairings",
        json={
            "installationId": "schema-installation",
            "name": "Schema client",
        },
    ).json
    validator(document, "PairingResult").validate(pairing)
    with app.app_context():
        approve_pairing(users[0], pairing["userCode"], [])
    redeemed = client.post(
        "/api/v1/pairings/redeem",
        json={key: pairing[key] for key in ("pairingId", "pairingSecret")},
    ).json
    validator(document, "RedeemResult").validate(redeemed)
    headers = {"Authorization": f"Bearer {redeemed['token']}"}
    created, request = create_record(client, headers, appliedDate=None)
    validator(document, "Mutation").validate(request)
    validator(document, "Application").validate(created)
    replay = client.post("/api/v1/mutations", json=request, headers=headers)
    validator(document, "MutationResult").validate(replay.json)
    for path, schema in (
        ("/applications", "FeedPage"),
        ("/changes", "FeedPage"),
        (f"/applications/{created['id']}", "Application"),
        ("/device", "Device"),
    ):
        validator(document, schema).validate(
            client.get("/api/v1" + path, headers=headers).json
        )
    deleted = client.post(
        "/api/v1/mutations",
        headers=headers,
        json={
            "mutationId": "schema-delete",
            "operation": "delete",
            "applicationId": created["id"],
            "expectedVersion": 1,
        },
    ).json
    validator(document, "MutationResult").validate(deleted)
    validator(document, "Tombstone").validate(deleted["application"])
    revoked = client.post("/api/v1/device/revoke", headers=headers).json
    validator(document, "Revocation").validate(revoked)
    validator(document, "Error").validate(
        client.get("/api/v1/device", headers=headers).json
    )


@pytest.mark.parametrize(
    "body",
    [
        {"mutationId": "x", "operation": "create", "fields": {}},
        {
            "mutationId": "x",
            "operation": "create",
            "applicationId": "chosen",
            "fields": {"title": "Role", "company": "Example"},
        },
        {"mutationId": "x", "operation": "update", "applicationId": "id"},
        {
            "mutationId": "x",
            "operation": "delete",
            "applicationId": "id",
            "expectedVersion": 1,
            "fields": {},
        },
        {
            "mutationId": "x",
            "operation": "map",
            "applicationId": "id",
            "expectedVersion": 1,
        },
        {
            "mutationId": "x",
            "operation": "create",
            "ownerId": 99,
            "fields": {"title": "Role", "company": "Example"},
        },
        {
            "mutationId": "x",
            "operation": "create",
            "fields": {
                "title": "Role",
                "company": "Example",
                "resume_filename": "x",
            },
        },
    ],
)
def test_schema_rejects_forbidden_operation_shapes(body):
    assert not validator(openapi_document(), "Mutation").is_valid(body)


@pytest.mark.parametrize(
    "value",
    [
        "",
        False,
        0,
        "2026-01-01T00:00:00+00:99",
        "0001-01-01T00:00:00+23:59",
        "9999-12-31T23:59:59-23:59",
    ],
)
def test_invalid_source_times_are_validation_errors(client, paired, value):
    response = client.post(
        "/api/v1/mutations",
        headers=paired,
        json={
            "mutationId": "bad-time",
            "operation": "create",
            "fields": {"title": "Role", "company": "Example"},
            "statusHistory": [
                {
                    "sourceEventId": "event",
                    "status": "applied",
                    "occurredAt": value,
                }
            ],
        },
    )
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
