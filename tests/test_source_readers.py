"""Fictional provider responses exercise range and Notion API boundaries."""

import io
import json
from urllib.parse import unquote

import pytest
import requests

from app.contracts import ServiceError
from app.google_sheets import read_private_sheet, read_public_sheet
from app.import_mapping import layout
from app.notion_sources import API_VERSION, notion_id, read_notion
from app.sheet_ranges import selected_csv, sheet_range

DATABASE_ID = "00000000-0000-4000-8000-000000000001"
SOURCE_ID = "00000000-0000-4000-8000-000000000002"
PAGE_ID = "00000000-0000-4000-8000-000000000003"
TOKEN = "fictional-notion-token"


def response(value, status=200):
    result = requests.Response()
    result.status_code = status
    result.raw = io.BytesIO(
        value if isinstance(value, bytes) else json.dumps(value).encode()
    )
    return result


@pytest.mark.parametrize(
    "value",
    [
        "A0:B2",
        "A2:A1",
        "A1:BI2",
        "A1:B1031",
        "Sheet!A1:B5",
        "A1:A",
        "http://evil",
    ],
)
def test_range_rejects_invalid_or_unbounded_selections(value):
    with pytest.raises(ServiceError):
        sheet_range(value)


def test_public_range_selects_exact_cells_before_column_limits(monkeypatch):
    data = (
        "outside," * 65 + "\nignore,Role,Employer,ignore\n"
        "ignore,Engineer,Example,ignore\nignore,Outside,Outside,ignore"
    ).encode()
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(data))
    reference = {"id": "fictionalSheet12345", "published": False, "gid": "42"}
    tables = read_public_sheet(reference, sheet_range("$B$2:$C$3"))
    assert tables[0]["rows"] == [["Role", "Employer"], ["Engineer", "Example"]]
    assert layout(tables[0], 1)[1][0][0] == 3
    with pytest.raises(ServiceError, match="data"):
        selected_csv(data, sheet_range("B50:C60"))


def test_private_range_is_quoted_and_requested_exactly(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(unquote(url))
        assert kwargs["allow_redirects"] is False
        if "/values/" not in url:
            return response(
                {
                    "sheets": [
                        {
                            "properties": {
                                "sheetId": 42,
                                "title": "My team's applications",
                            }
                        }
                    ]
                }
            )
        return response({"values": [["Role", "Employer"], ["A", "B"]]})

    monkeypatch.setattr(requests, "get", get)
    result = read_private_sheet(
        {"id": "fictionalSheet12345", "published": False, "gid": "42"},
        "fictional-access-token",
        sheet_range("B4:C5"),
    )
    assert calls[-1].endswith("/'My team''s applications'!B4:C5")
    assert result[0]["sheet_id"] == "42"
    assert result[0]["start_row"] == 4


@pytest.mark.parametrize(
    "value",
    [
        "http://notion.so/" + DATABASE_ID,
        "https://notion.so.evil.test/" + DATABASE_ID,
        "https://user@notion.so/" + DATABASE_ID,
        "https://127.0.0.1/" + DATABASE_ID,
        "not-a-source-id",
    ],
)
def test_notion_reference_never_allows_arbitrary_hosts(value):
    with pytest.raises(ServiceError):
        notion_id(value)


def test_notion_database_discovers_source_and_paginates_typed_properties(
    monkeypatch,
):
    calls = []
    properties = {
        "Position": {"type": "title", "title": [{"plain_text": "Engineer"}]},
        "Employer": {
            "type": "rich_text",
            "rich_text": [{"text": {"content": "Example"}}],
        },
        "Stage": {"type": "status", "status": {"name": "Submitted"}},
        "Applied on": {
            "type": "date",
            "date": {"start": "2026-10-06T12:00:00Z"},
        },
    }

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        assert url.startswith("https://api.notion.com/v1/")
        assert kwargs["headers"]["Notion-Version"] == API_VERSION
        assert kwargs["headers"]["Authorization"] == "Bearer " + TOKEN
        assert kwargs["allow_redirects"] is False
        if "/databases/" in url:
            return response(
                {"data_sources": [{"id": SOURCE_ID, "name": "Jobs"}]}
            )
        if method == "GET":
            return response({"properties": {name: {} for name in properties}})
        if kwargs["json"].get("start_cursor"):
            return response({"results": [], "has_more": False})
        return response(
            {
                "results": [
                    {"object": "page", "id": PAGE_ID, "properties": properties}
                ],
                "has_more": True,
                "next_cursor": "fictional-cursor",
            }
        )

    monkeypatch.setattr(requests, "request", request)
    result = read_notion({"kind": "database", "id": DATABASE_ID}, TOKEN)[0]
    assert result["rows"] == [
        ["Applied on", "Employer", "Position", "Stage"],
        ["2026-10-06", "Example", "Engineer", "Submitted"],
    ]
    assert result["row_ids"] == [None, PAGE_ID]
    assert calls[-1][2]["json"]["start_cursor"] == "fictional-cursor"


def test_notion_redirects_errors_and_cursor_loops_are_sanitized(monkeypatch):
    monkeypatch.setattr(
        requests, "request", lambda *a, **k: response({"message": TOKEN}, 302)
    )
    with pytest.raises(ServiceError) as error:
        read_notion({"kind": "data_source", "id": SOURCE_ID}, TOKEN)
    assert TOKEN not in str(error.value)
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **k: response(
            {
                "properties": {"Title": {}},
                "results": [],
                "has_more": True,
                "next_cursor": "repeated",
            }
        ),
    )
    with pytest.raises(ServiceError, match="pagination"):
        read_notion({"kind": "data_source", "id": SOURCE_ID}, TOKEN)


def test_notion_one_time_import_does_not_save_or_echo_token(
    app, logged_client, monkeypatch
):
    from app.extensions import db
    from app.models import ImportBatch
    from tests.helpers import csrf_token

    def request(method, url, **kwargs):
        if method == "GET":
            return response({"properties": {"Role": {}, "Company": {}}})
        return response(
            {
                "results": [
                    {
                        "object": "page",
                        "id": PAGE_ID,
                        "properties": {
                            "Role": {
                                "type": "title",
                                "title": [{"plain_text": "Engineer"}],
                            },
                            "Company": {
                                "type": "rich_text",
                                "rich_text": [{"plain_text": "Example"}],
                            },
                        },
                    }
                ],
                "has_more": False,
            }
        )

    monkeypatch.setattr(requests, "request", request)
    result = logged_client.post(
        "/imports",
        data={
            "source": "notion",
            "notion_kind": "data_source",
            "notion_url": SOURCE_ID,
            "notion_token": TOKEN,
            "csrf_token": csrf_token(logged_client, "/imports"),
        },
    )
    assert result.status_code == 302
    assert TOKEN.encode() not in logged_client.get(result.location).data
    with logged_client.session_transaction() as session:
        assert TOKEN not in json.dumps(dict(session))
    with app.app_context():
        batch = db.session.query(ImportBatch).one()
        assert TOKEN not in json.dumps(batch.payload)
