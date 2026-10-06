"""Bounded A1 selections shared by public and authorized Sheets readers."""

import csv
import io
import re
from itertools import islice

from app.import_readers import (
    MAX_COLUMNS,
    MAX_ROWS,
    decode_text,
    import_error,
    table,
    validated_tables,
)


def column_number(label):
    number = 0
    for char in label.upper():
        number = number * 26 + ord(char) - ord("A") + 1
    return number


def sheet_range(value):
    if not value:
        return None
    if not isinstance(value, str) or len(value) > 40:
        import_error("Choose a cell range such as B4:N200.")
    match = re.fullmatch(
        r"\$?([A-Za-z]{1,3})\$?([1-9]\d{0,6})"
        r"(?::\$?([A-Za-z]{1,3})\$?([1-9]\d{0,6}))?",
        value.strip(),
    )
    if not match:
        import_error("Use a cell or a bounded range such as B4:N200.")
    first_col, first_row, last_col, last_row = match.groups()
    last_col, last_row = last_col or first_col, last_row or first_row
    start_col, end_col = map(column_number, (first_col, last_col))
    start_row, end_row = int(first_row), int(last_row)
    if (
        not 1 <= end_col - start_col + 1 <= MAX_COLUMNS
        or not 1 <= end_row - start_row + 1 <= MAX_ROWS + 30
    ):
        import_error("Select at most 60 columns and 1,030 rows, in order.")
    return {
        "a1": f"{first_col.upper()}{start_row}:{last_col.upper()}{end_row}",
        "start_col": start_col,
        "end_col": end_col,
        "start_row": start_row,
        "end_row": end_row,
    }


def selected_csv(data, selection):
    rows = csv.reader(io.StringIO(decode_text(data)))
    selected = islice(rows, selection["start_row"] - 1, selection["end_row"])
    result = table(
        "Selected range",
        (
            row[selection["start_col"] - 1 : selection["end_col"]]
            for row in selected
        ),
    )
    result["start_row"] = selection["start_row"]
    return validated_tables([result])
