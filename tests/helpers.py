import re
from pathlib import Path

MIGRATIONS = str(Path(__file__).resolve().parents[1] / "migrations")


def csrf_token(client, path):
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert match, response.data
    return match.group(1).decode()


def job_data(**overrides):
    data = {"job_title": "Engineer", "company": "Example", "status": "Applied"}
    data.update(overrides)
    return data
