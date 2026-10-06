"""Account-scoped previews and atomic imports using the shared write path."""

import hashlib
import json
from datetime import timedelta

from app.contracts import ServiceError, utc, validate_fields
from app.database import database_transaction
from app.extensions import db
from app.import_mapping import (
    FIELD_LABELS,
    date_order,
    layout,
    normalized,
    row_preview,
    status_values,
    suggested_header,
    suggested_mapping,
    suggested_status,
)
from app.import_readers import import_error
from app.models import JOB_STATUSES, ImportBatch, JobApplication, _utcnow
from app.record_updates import lock_account, write_application


def create_batch(user_id, tables):
    with database_transaction():
        lock_account(user_id)
        ImportBatch.query.filter_by(user_id=user_id).filter(
            ImportBatch.expires_at < _utcnow()
        ).delete(synchronize_session=False)
        pending = (
            ImportBatch.query.filter_by(user_id=user_id)
            .order_by(ImportBatch.created_at.desc())
            .all()
        )
        for old in pending[9:]:
            db.session.delete(old)
        batch = ImportBatch(
            user_id=user_id,
            payload=tables,
            expires_at=_utcnow() + timedelta(minutes=30),
        )
        db.session.add(batch)
    return batch


def cleanup_imports():
    """Erase expired drafts/receipts without reading their private contents."""
    with database_transaction():
        return ImportBatch.query.filter(
            ImportBatch.expires_at < _utcnow()
        ).delete(synchronize_session=False)


def get_batch(user_id, batch_id):
    batch = ImportBatch.query.filter_by(id=batch_id, user_id=user_id).first()
    if not batch:
        raise ServiceError("not_found", "Import preview not found.", 404)
    if utc(batch.expires_at) < _utcnow():
        raise ServiceError(
            "import_expired",
            "This import preview expired. Choose the source again.",
            410,
        )
    return batch


def selected_sheet(batch, sheet_index):
    if type(sheet_index) is not int or not 0 <= sheet_index < len(
        batch.payload
    ):
        import_error("Choose an available sheet.")
    return batch.payload[sheet_index]


def initial_options(batch, sheet_index=0, header=None):
    sheet = selected_sheet(batch, sheet_index)
    header = suggested_header(sheet["rows"]) if header is None else header
    labels, rows = layout(sheet, header)
    mapping = suggested_mapping(labels, rows)
    return {
        "sheet": sheet_index,
        "header": header,
        "mapping": mapping,
        "date_order": date_order(rows, mapping),
        "default_status": "shortlisted",
        "status_map": {
            normalized(value): suggested_status(value)
            for value in status_values(rows, mapping)
        },
        "preserve": False,
        "duplicates": "skip",
        "skip_invalid": False,
    }


def validate_options(batch, options):
    sheet = selected_sheet(batch, options.get("sheet"))
    mapping = options.get("mapping")
    labels, _ = layout(sheet, options.get("header"))
    if (
        not isinstance(mapping, list)
        or len(mapping) != len(labels)
        or any(field and field not in FIELD_LABELS for field in mapping)
    ):
        import_error("Choose a supported destination for each column.")
    mapped = [field for field in mapping if field]
    if len(mapped) != len(set(mapped)) or not {"title", "company"} <= set(
        mapped
    ):
        import_error(
            "Map job title and company, and map each tracker field only once."
        )
    if (
        options.get("date_order") not in {"auto", "dmy", "mdy"}
        or options.get("default_status") not in JOB_STATUSES
        or options.get("duplicates") not in {"skip", "allow"}
    ):
        import_error("Choose supported date, status and duplicate options.")
    statuses = options.get("status_map")
    if (
        not isinstance(statuses, dict)
        or len(statuses) > 100
        or any(
            value and value not in JOB_STATUSES for value in statuses.values()
        )
    ):
        import_error("Choose supported status mappings.")
    if any(
        type(options.get(key)) is not bool
        for key in ("preserve", "skip_invalid")
    ):
        import_error("Choose valid import options.")


def options_digest(options):
    return hashlib.sha256(
        json.dumps(options, sort_keys=True).encode()
    ).hexdigest()


def duplicate_key(title, company, url, applied):
    # Case/whitespace-insensitive text; distinct dates/URLs stay distinct.
    return (
        " ".join(title.casefold().split()),
        " ".join(company.casefold().split()),
        (url or "").strip(),
        str(applied or ""),
    )


def preview(batch, options):
    validate_options(batch, options)
    known = {
        duplicate_key(*row)
        for row in JobApplication.for_user(batch.user_id)
        .with_entities(
            JobApplication.job_title,
            JobApplication.company,
            JobApplication.job_url,
            JobApplication.applied_on,
        )
        .yield_per(500)
    }
    rows = row_preview(batch.payload[options["sheet"]], options)
    counts = {"ready": 0, "invalid": 0, "duplicates": 0}
    for entry in rows:
        if entry["error"]:
            counts["invalid"] += 1
            entry["decision"] = "Invalid"
            continue
        fields = entry["fields"]
        key = duplicate_key(
            fields["title"],
            fields["company"],
            fields.get("url"),
            fields.get("appliedDate"),
        )
        if key in known and options["duplicates"] == "skip":
            counts["duplicates"] += 1
            entry["decision"] = "Skip duplicate"
        else:
            counts["ready"] += 1
            entry["decision"] = "Import"
        known.add(key)
    return rows, counts


def save_options(batch, options):
    validate_options(batch, options)
    with database_transaction():
        lock_account(batch.user_id)
        db.session.refresh(batch)
        if batch.result or utc(batch.expires_at) < _utcnow():
            raise ServiceError(
                "import_changed",
                "This preview changed or expired. Reload it.",
                409,
            )
        batch.options = options


def commit_batch(user_id, batch_id, digest):
    with database_transaction():
        lock_account(user_id)
        batch = get_batch(user_id, batch_id)
        db.session.refresh(batch)
        if batch.result:
            return batch.result
        if not batch.options or options_digest(batch.options) != digest:
            raise ServiceError(
                "import_changed",
                "Review the latest preview before importing.",
                409,
            )
        rows, counts = preview(batch, batch.options)
        if counts["invalid"] and not batch.options["skip_invalid"]:
            import_error(
                "Resolve invalid rows or explicitly choose to skip them."
            )
        if not counts["ready"]:
            import_error("No new valid rows are selected for import.")
        for entry in rows:
            if entry["decision"] == "Import":
                write_application(
                    JobApplication(user_id=user_id),
                    validate_fields(entry["fields"], create=True),
                    source="import",
                )
        result = {
            "imported": counts["ready"],
            "invalid": counts["invalid"],
            "duplicates": counts["duplicates"],
        }
        batch.payload = None
        batch.options = None
        batch.result = result
        batch.expires_at = _utcnow() + timedelta(hours=24)
    return result
