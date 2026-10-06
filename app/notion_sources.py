"""Read selected Notion data sources using bounded, fixed-host API calls."""

import json
import re
from urllib.parse import urlsplit
from uuid import UUID

import requests

from app.contracts import ServiceError
from app.google_sheets import bounded_response
from app.import_readers import (
    MAX_BYTES,
    MAX_ROWS,
    MAX_TABLES,
    cell_text,
    import_error,
    table,
    validated_tables,
)

API_ROOT = "https://api.notion.com/v1/"
API_VERSION = "2025-09-03"


def notion_id(value):
    if not isinstance(value, str) or len(value) > 2048:
        import_error("Choose a Notion database link or data source ID.")
    value = value.strip()
    if "://" in value:
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.port not in {None, 443}
                or not re.fullmatch(
                    r"(?:[a-z0-9-]+\.)?notion\.(?:so|site)",
                    parsed.hostname or "",
                )
            ):
                raise ValueError
            value = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            match = re.search(r"([a-fA-F0-9]{32})$", value)
            value = match[1] if match else value
        except ValueError:
            import_error("Use an HTTPS Notion link or a data source ID.")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        import_error("The Notion database or data source ID is invalid.")


def checked_token(token):
    if (
        not isinstance(token, str)
        or not 10 <= len(token.strip()) <= 4096
        or any(not 33 <= ord(char) <= 126 for char in token.strip())
    ):
        import_error("Enter a valid private Notion connection token.")
    return token.strip()


def notion_request(token, path, *, body=None):
    try:
        response = requests.request(
            "GET" if body is None else "POST",
            API_ROOT + path,
            headers={
                "Authorization": "Bearer " + checked_token(token),
                "Notion-Version": API_VERSION,
            },
            json=body,
            timeout=10,
            stream=True,
            allow_redirects=False,
        )
        result = json.loads(bounded_response(response, provider="Notion"))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except ServiceError:
        raise
    except (requests.RequestException, ValueError) as error:
        raise ServiceError(
            "notion_unavailable",
            "Notion is temporarily unavailable. Try again later.",
            422,
        ) from error


def notion_value(prop):
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in {"title", "rich_text"}:
        return "".join(
            item.get("plain_text", item.get("text", {}).get("content", ""))
            for item in value or []
        )
    if kind in {"select", "status"}:
        return (value or {}).get("name", "")
    if kind == "multi_select":
        return ", ".join(item.get("name", "") for item in value or [])
    if kind == "date":
        return (value or {}).get("start", "").split("T")[0]
    if kind in {"formula", "rollup"}:
        return notion_value(value or {})
    if kind == "people":
        return ", ".join(item.get("name", "") for item in value or [])
    if kind == "unique_id":
        return "-".join(
            str(part)
            for part in (
                (value or {}).get("prefix"),
                (value or {}).get("number"),
            )
            if part is not None
        )
    if kind in {
        "url",
        "email",
        "phone_number",
        "number",
        "string",
        "checkbox",
        "boolean",
        "created_time",
        "last_edited_time",
    }:
        return cell_text(value)
    return ""


def source_pages(source_id, token):
    pages, seen_cursors = [], set()
    body = {
        "page_size": 100,
        "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
    }
    size = 0
    for _ in range(20):
        response = notion_request(
            token, f"data_sources/{source_id}/query", body=body
        )
        size += len(json.dumps(response).encode())
        pages.extend(response.get("results", []))
        if size > MAX_BYTES or len(pages) > MAX_ROWS:
            import_error("Use a Notion source of at most 5 MB and 1,000 rows.")
        if response.get("request_status", {}).get("type") == "incomplete":
            import_error("Notion returned an incomplete source. Narrow it.")
        if not response.get("has_more"):
            return pages
        cursor = response.get("next_cursor")
        if (
            not isinstance(cursor, str)
            or not 1 <= len(cursor) <= 1024
            or cursor in seen_cursors
        ):
            import_error("Notion returned invalid pagination. Try again.")
        seen_cursors.add(cursor)
        body["start_cursor"] = cursor
    import_error("Notion returned too many pages. Use a smaller source.")


def read_data_source(source, token):
    source_id = notion_id(source["id"])
    schema = notion_request(token, "data_sources/" + source_id)
    properties = schema.get("properties", {})
    labels = sorted(properties)
    pages = source_pages(source_id, token)
    rows, ids = [labels], [None]
    for page in pages:
        if page.get("object") != "page":
            import_error(
                "Choose a Notion source containing application pages."
            )
        rows.append(
            [
                notion_value(page.get("properties", {}).get(label, {}))
                for label in labels
            ]
        )
        ids.append(notion_id(page.get("id")))
    result = table(source.get("name", "Notion"), rows)
    result["data_source_id"] = source_id
    result["row_ids"] = ids
    return result


def _read_notion(reference, token):
    resource_id = notion_id(reference["id"])
    if reference["kind"] == "data_source":
        sources = [{"id": resource_id, "name": "Notion"}]
    else:
        metadata = notion_request(token, "databases/" + resource_id)
        sources = metadata.get("data_sources", [])
        selected = reference.get("data_source_id")
        if selected:
            sources = [
                source for source in sources if source["id"] == selected
            ]
    if not 1 <= len(sources) <= MAX_TABLES:
        import_error("Choose an available Notion data source (at most 10).")
    return validated_tables(
        [read_data_source(source, token) for source in sources]
    )


def read_notion(reference, token):
    try:
        return _read_notion(reference, token)
    except ServiceError:
        raise
    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        RuntimeError,
    ) as error:
        raise ServiceError(
            "notion_unavailable",
            "Notion returned an unreadable source. Try again later.",
            422,
        ) from error
