"""Streaming account-scoped exports with explicit field selection."""

import csv
import io
import json

from flask import (
    Blueprint,
    Response,
    render_template,
    request,
    stream_with_context,
)
from flask_login import current_user, login_required

from app.contracts import (
    DEFAULT_FIELDS,
    FIELD_SPECS,
    OPTIONAL_FIELDS,
    ServiceError,
    serialize_application,
)
from app.models import JobApplication

exports = Blueprint("exports", __name__)
EXPORT_FIELDS = set(FIELD_SPECS) | {"statusHistory"}
METADATA = {"id", "version", "createdAt", "updatedAt"}


def csv_cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@"))
        or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value


@exports.get("/exports")
@login_required
def index():
    return render_template(
        "exports.html",
        fields=sorted(EXPORT_FIELDS),
        default_fields=DEFAULT_FIELDS,
        optional_fields=OPTIONAL_FIELDS,
    )


def records(user_id, fields):
    for job in (
        JobApplication.for_user(user_id)
        .order_by(JobApplication.id)
        .yield_per(50)
    ):
        payload = serialize_application(job)
        yield {
            key: value
            for key, value in payload.items()
            if key in fields | METADATA
        }


def json_export(user_id, fields):
    yield '{"schemaVersion":1,"applications":['
    separator = ""
    for payload in records(user_id, fields):
        yield separator + json.dumps(payload, ensure_ascii=False)
        separator = ","
    yield "]}"


def csv_export(user_id, fields):
    columns = sorted(METADATA | fields)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    yield buffer.getvalue()
    for payload in records(user_id, fields):
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow(
            {name: csv_cell(payload.get(name)) for name in columns}
        )
        yield buffer.getvalue()


@exports.get("/exports/<format>")
@login_required
def download(format):
    if format not in {"json", "csv"}:
        raise ServiceError("not_found", "Export format not found.", 404)
    fields = set(request.args.getlist("fields")) or DEFAULT_FIELDS
    if fields - EXPORT_FIELDS:
        raise ServiceError(
            "validation_error", "Unknown export field selection.", 422
        )
    generator = json_export if format == "json" else csv_export
    response = Response(
        stream_with_context(generator(current_user.id, fields)),
        mimetype="application/json" if format == "json" else "text/csv",
    )
    response.headers["Content-Disposition"] = (
        f'attachment; filename="job-scout-applications.{format}"'
    )
    return response
