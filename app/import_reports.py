"""CSV review reports independent of the HTTP import workflow."""

import csv
import io

from app.exports import csv_cell
from app.import_mapping import FIELD_LABELS, layout
from app.import_service import preview


def review_csv(batch):
    """Render mapped and original values with CSV formula protection."""
    rows, _ = preview(batch, batch.options)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    labels, _ = layout(
        batch.payload[batch.options["sheet"]], batch.options["header"]
    )
    writer.writerow(
        [
            "Source row",
            "Decision",
            "Issue",
            *FIELD_LABELS.values(),
            *[csv_cell("Original: " + label) for label in labels],
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["number"],
                row["decision"],
                csv_cell(_row_issue(row)),
                *[
                    csv_cell(row["fields"].get(name, ""))
                    for name in FIELD_LABELS
                ],
                *[csv_cell(value) for value in row["source"]],
            ]
        )
    return output.getvalue()


def _row_issue(row):
    if row["error"]:
        return row["error"]
    if row.get("conflicts"):
        return "Local edits preserved: " + ", ".join(row["conflicts"])
    return ""
