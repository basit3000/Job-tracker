"""Bounded, read-only access to explicitly selected Google spreadsheets."""

import csv
import json
import re
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import requests

from app.contracts import ServiceError
from app.import_readers import (
    MAX_BYTES,
    import_error,
    read_file,
    table,
    validated_tables,
)
from app.sheet_ranges import selected_csv

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets/"


def sheet_reference(value):
    if not isinstance(value, str) or len(value) > 2048:
        import_error("Use a Google Sheets link of at most 2,048 characters.")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        import_error("The Google Sheets URL is invalid.")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "docs.google.com"
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        import_error("Paste an HTTPS Google Sheets link from docs.google.com.")
    match = re.fullmatch(
        r"/spreadsheets/d/(e/)?([A-Za-z0-9_-]{10,200})(?:/[A-Za-z0-9_-]*)?/?",
        parsed.path,
    )
    if not match:
        import_error(
            "Use the spreadsheet's share link or published-to-web link."
        )
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid = (fragment.get("gid") or query.get("gid") or [None])[0]
    if gid is not None and not re.fullmatch(r"\d{1,12}", gid):
        import_error("The sheet tab ID is invalid.")
    return {"id": match[2], "published": bool(match[1]), "gid": gid}


def bounded_response(response, *, provider="Google Sheets"):
    with response:
        if response.status_code != 200:
            if provider == "Notion":
                import_error(
                    "Notion could not read this source. Check the token and "
                    "share the database with your Notion connection. "
                    "If rate limited, try again later."
                )
            import_error(
                "Google could not read this sheet. Check access, authorize "
                "private access, or download it as XLSX/CSV."
            )
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                import_error(
                    f"The {provider} response exceeds 5 MB. "
                    "Import a smaller sheet."
                )
        return bytes(data)


def allowed_export_redirect(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and port in {None, 443}
        and (
            parsed.hostname == "docs.google.com"
            or re.fullmatch(
                r"doc-[a-z0-9-]+-sheets\.googleusercontent\.com",
                parsed.hostname or "",
            )
        )
    )


def read_public_sheet(reference, selection=None):
    path = (
        f"e/{reference['id']}/pub"
        if reference["published"]
        else f"{reference['id']}/export"
    )
    url = "https://docs.google.com/spreadsheets/d/" + path
    params = {"output" if reference["published"] else "format": "csv"}
    if reference["gid"] is not None:
        params["gid"] = reference["gid"]
    try:
        for _ in range(4):
            response = requests.get(
                url,
                params=params,
                stream=True,
                timeout=10,
                allow_redirects=False,
            )
            params = None
            if response.status_code not in {301, 302, 303, 307, 308}:
                if "text/html" in response.headers.get("Content-Type", ""):
                    response.close()
                    import_error(
                        "This sheet requires Google authorization. "
                        "Choose private Sheets access or upload an export."
                    )
                data = bounded_response(response)
                return (
                    selected_csv(data, selection)
                    if selection
                    else read_file(data, "sheet.csv")
                )
            target = urljoin(url, response.headers.get("Location", ""))
            response.close()
            if not allowed_export_redirect(target):
                import_error(
                    "This sheet requires authorization or has an unsupported "
                    "redirect. Use private access or upload an export."
                )
            url = target
    except requests.RequestException as error:
        raise google_unavailable() from error
    except (csv.Error, UnicodeError) as error:
        raise ServiceError(
            "import_error",
            "The selected sheet could not be read. Export it as XLSX.",
            422,
        ) from error
    import_error(
        "Google returned too many redirects. Upload an export instead."
    )


def google_unavailable():
    return ServiceError(
        "google_unavailable",
        "Google Sheets is temporarily unavailable. "
        "Try again or upload an export.",
        422,
    )


def api_json(path, access_token, params):
    try:
        response = requests.get(
            API_ROOT + path,
            headers={"Authorization": "Bearer " + access_token},
            params=params,
            stream=True,
            timeout=10,
            allow_redirects=False,
        )
        result = json.loads(bounded_response(response))
        if not isinstance(result, dict):
            raise ValueError("Invalid provider response.")
        return result
    except ServiceError:
        raise
    except (requests.RequestException, ValueError) as error:
        raise google_unavailable() from error


def read_private_sheet(reference, access_token, selection=None):
    if reference["published"]:
        import_error(
            "Private access needs the normal spreadsheet share URL, "
            "not a published-to-web URL."
        )
    metadata = api_json(
        reference["id"],
        access_token,
        {"fields": "sheets.properties(sheetId,title)"},
    )
    sheets = [item["properties"] for item in metadata.get("sheets", [])]
    if reference["gid"] is not None:
        sheets = [
            item for item in sheets if str(item["sheetId"]) == reference["gid"]
        ]
    if not 1 <= len(sheets) <= 10:
        import_error(
            "Choose an available tab, or a workbook with at most 10 tabs."
        )
    tables = []
    for sheet in sheets:
        cells = selection["a1"] if selection else "A1:BI1031"
        range_name = "'" + sheet["title"].replace("'", "''") + "'!" + cells
        values = api_json(
            reference["id"] + "/values/" + quote(range_name, safe=""),
            access_token,
            {"valueRenderOption": "FORMATTED_VALUE"},
        )
        result = table(sheet["title"], values.get("values", []))
        result["sheet_id"] = str(sheet["sheetId"])
        result["start_row"] = selection["start_row"] if selection else 1
        tables.append(result)
    return validated_tables(tables)
