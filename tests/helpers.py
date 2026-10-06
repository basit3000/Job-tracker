import re
from pathlib import Path
from uuid import uuid4

from app.devices import approve_pairing

MIGRATIONS = str(Path(__file__).resolve().parents[1] / "migrations")


def csrf_token(client, path):
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert match, response.data
    return match.group(1).decode()


def job_data(**overrides):
    data = {
        "job_title": "Engineer",
        "company": "Example",
        "status": "applied",
        "version": 1,
    }
    data.update(overrides)
    return data


def pair_device(
    client, app, user_id, *, optional=(), installation="fictional-installation"
):
    result = client.post(
        "/api/v1/pairings",
        json={"installationId": installation, "name": "Fictional client"},
    )
    assert result.status_code == 200
    pairing = result.json
    with app.app_context():
        approve_pairing(user_id, pairing["userCode"], optional)
    result = client.post(
        "/api/v1/pairings/redeem",
        json={
            "pairingId": pairing["pairingId"],
            "pairingSecret": pairing["pairingSecret"],
        },
    )
    assert result.status_code == 200
    return {"Authorization": f"Bearer {result.json['token']}"}, result.json[
        "deviceId"
    ]


def create_record(client, headers, **fields):
    body = {
        "mutationId": str(uuid4()),
        "operation": "create",
        "fields": {
            "title": "Engineer",
            "company": "Example",
            "status": "applied",
            **fields,
        },
    }
    response = client.post("/api/v1/mutations", json=body, headers=headers)
    assert response.status_code == 200, response.json
    return response.json["application"], body
