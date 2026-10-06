"""Bounded spreadsheet readers; files and formulas are never executed."""

import csv
import io
import json
from contextlib import closing, contextmanager
from datetime import date, datetime
from pathlib import PurePath
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

import openpyxl
import xlrd
from defusedxml.ElementTree import fromstring

from app.contracts import ServiceError

MAX_BYTES = 5 * 1024 * 1024
MAX_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_ROWS = 1000
MAX_COLUMNS = 60
MAX_TABLES = 10
MAX_CELL = 20000
FORMATS = {
    "csv",
    "tsv",
    "txt",
    "xlsx",
    "xls",
    "ods",
    "json",
    "jsonl",
    "ndjson",
}


def import_error(message):
    raise ServiceError("import_error", message, 422)


def cell_text(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    result = str(value)
    if len(result) > MAX_CELL:
        import_error("A cell exceeds 20,000 characters. Shorten it and retry.")
    return result


def table(name, rows):
    result = []
    for row in rows:
        if len(row) > MAX_COLUMNS:
            import_error("Use at most 60 columns per sheet.")
        result.append([cell_text(value) for value in row])
        if len(result) > MAX_ROWS + 30:
            import_error(
                "Use at most 1,000 data rows "
                "and 30 header/title rows per sheet."
            )
    while result and not any(value.strip() for value in result[-1]):
        result.pop()
    return {"name": cell_text(name)[:128], "rows": result}


def decode_text(data):
    encoding = (
        "utf-16"
        if data.startswith((b"\xff\xfe", b"\xfe\xff"))
        else "utf-8-sig"
    )
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode("cp1252")


def read_delimited(data):
    content = decode_text(data)
    dialect = detect_delimiter(content)
    return [table("Table", csv.reader(io.StringIO(content), dialect))]


def detect_delimiter(content):
    lines = content[:8192].splitlines(keepends=True)
    for offset in range(min(len(lines), 30)):
        try:
            return csv.Sniffer().sniff(
                "".join(lines[offset:]), delimiters=",;\t|"
            )
        except csv.Error:
            continue
    return csv.excel_tab if "\t" in content else csv.excel


def read_json(data, *, lines=False):
    content = decode_text(data)
    if lines:
        records = [
            json.loads(line) for line in content.splitlines() if line.strip()
        ]
    else:
        records = json.loads(content)
    if isinstance(records, dict):
        lists = [
            records[key]
            for key in ("applications", "records", "jobs", "data")
            if isinstance(records.get(key), list)
        ]
        if len(lists) != 1:
            import_error(
                "JSON must be a list of records or contain "
                "applications, records, jobs, or data."
            )
        records = lists[0]
    if (
        not isinstance(records, list)
        or not records
        or any(not isinstance(row, dict) for row in records)
    ):
        import_error("JSON must contain a nonempty list of record objects.")
    columns = list(dict.fromkeys(key for row in records for key in row))
    return [
        table(
            "Records",
            [columns] + [[row.get(key) for key in columns] for row in records],
        )
    ]


@contextmanager
def checked_archive(data):
    with ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 1000
            or sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES
        ):
            import_error("This workbook expands beyond the safe import limit.")
        for entry in entries:
            if entry.filename.endswith((".xml", ".rels")):
                fromstring(archive.read(entry), forbid_dtd=True)
        yield archive


def read_xlsx(data):
    with (
        checked_archive(data),
        closing(
            openpyxl.load_workbook(
                io.BytesIO(data),
                read_only=True,
                data_only=True,
                keep_links=False,
            )
        ) as book,
    ):
        if len(book.worksheets) > MAX_TABLES:
            import_error("Use at most 10 sheets per workbook.")
        result = []
        for sheet in book.worksheets:
            sheet.reset_dimensions()
            result.append(
                table(sheet.title, sheet.iter_rows(values_only=True))
            )
        return result


def read_xls(data):
    book = xlrd.open_workbook(file_contents=data, on_demand=True)
    try:
        if book.nsheets > MAX_TABLES:
            import_error("Use at most 10 sheets per workbook.")
        return [
            table(sheet.name, xls_rows(sheet, book.datemode))
            for sheet in book.sheets()
        ]
    finally:
        book.release_resources()


def xls_rows(sheet, datemode):
    for index in range(sheet.nrows):
        yield [
            xlrd.xldate_as_datetime(cell.value, datemode)
            if cell.ctype == xlrd.XL_CELL_DATE
            else cell.value
            for cell in sheet.row(index)
        ]


ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODF_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"


def ods_rows(sheet):
    for row in sheet.iter(ODF_TABLE + "table-row"):
        values = []
        for cell in row:
            repeat = int(cell.get(ODF_TABLE + "number-columns-repeated", "1"))
            value = (
                cell.get(ODF_OFFICE + "date-value")
                or "\n".join(
                    "".join(p.itertext()) for p in cell.findall(ODF_TEXT + "p")
                )
                or cell.get(ODF_OFFICE + "value", "")
            )
            if not value and repeat > MAX_COLUMNS:
                continue
            if repeat < 1 or len(values) + repeat > MAX_COLUMNS:
                import_error("Use at most 60 columns per sheet.")
            values.extend([value] * repeat)
        repeat = int(row.get(ODF_TABLE + "number-rows-repeated", "1"))
        if not any(values):
            continue
        if not 1 <= repeat <= MAX_ROWS:
            import_error("Too many repeated spreadsheet rows.")
        yield from (values for _ in range(repeat))


def read_ods(data):
    with checked_archive(data) as archive:
        root = fromstring(archive.read("content.xml"), forbid_dtd=True)
    sheets = root.findall(".//" + ODF_TABLE + "table")
    if len(sheets) > MAX_TABLES:
        import_error("Use at most 10 sheets per workbook.")
    return [
        table(sheet.get(ODF_TABLE + "name", "Sheet"), ods_rows(sheet))
        for sheet in sheets
    ]


def read_file(data, filename):
    if not data or len(data) > MAX_BYTES:
        import_error("Choose a nonempty file of at most 5 MB.")
    extension = PurePath(filename).suffix.lower().lstrip(".")
    readers = {
        "xlsx": read_xlsx,
        "xls": read_xls,
        "ods": read_ods,
        "json": read_json,
        "jsonl": lambda value: read_json(value, lines=True),
        "ndjson": lambda value: read_json(value, lines=True),
    }
    if extension not in FORMATS:
        import_error("Use XLSX, XLS, ODS, CSV, TSV, TXT, JSON, or JSONL.")
    try:
        tables = readers.get(extension, read_delimited)(data)
    except ServiceError:
        raise
    except (
        ValueError,
        KeyError,
        csv.Error,
        BadZipFile,
        xlrd.XLRDError,
        OSError,
        ParseError,
        RuntimeError,
    ) as error:
        raise ServiceError(
            "import_error",
            "The file could not be read. "
            "Export it again as XLSX or CSV and retry.",
            422,
        ) from error
    return validated_tables(tables)


def validated_tables(tables):
    tables = [item for item in tables if item["rows"]]
    if not tables or sum(len(item["rows"]) for item in tables) > 5000:
        import_error(
            "Choose a workbook with data and at most 5,000 total rows."
        )
    if len(json.dumps(tables).encode()) > MAX_EXPANDED_BYTES:
        import_error("The extracted data exceeds 20 MB.")
    return tables
