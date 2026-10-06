"""Reviewed inbound merges preserve local edits and never delete jobs."""

import hashlib
import json
from collections import Counter

from app.contracts import (
    FIELD_SPECS,
    ServiceError,
    iso,
    serialize_application,
    validate_fields,
)
from app.extensions import db
from app.import_mapping import FIELD_LABELS, layout, row_preview
from app.import_readers import import_error
from app.import_service import duplicate_key, finish_batch, validate_options
from app.models import (
    TERMINAL_STATUSES,
    JobApplication,
    SourceConnection,
    SourceRecord,
    _utcnow,
)
from app.record_updates import write_application


def batch_connection(batch):
    connection = (
        SourceConnection.query.filter_by(
            id=batch.connection_id, user_id=batch.user_id
        )
        .populate_existing()
        .first()
    )
    if not connection or connection.version != batch.connection_version:
        raise ServiceError(
            "source_changed", "This source changed. Read a fresh preview.", 409
        )
    return connection


def sync_fields(entry, options):
    fields = dict(entry["fields"])
    mapped = set(options["mapping"]) - {""}
    for name in mapped - {"title", "company", "status"}:
        fields.setdefault(name, None)
    if "status" not in mapped:
        fields.pop("status", None)
    if fields.get("status") in TERMINAL_STATUSES and "followUpDate" in fields:
        fields["followUpDate"] = None
    values = validate_fields(fields, create=True)
    return {
        name: iso(values[FIELD_SPECS[name][0]])
        if FIELD_SPECS[name][1] == "date"
        else values[FIELD_SPECS[name][0]]
        for name in fields
    }


def source_key(sheet, entry, options):
    if sheet.get("row_ids"):
        identity = sheet["row_ids"][entry["number"] - 1]
        if not isinstance(identity, str) or not identity:
            import_error("This Notion row has no stable page ID.")
    elif options.get("identity_column", -1) >= 0:
        identity = entry["source"][options["identity_column"]].strip()
        if not identity or len(identity) > 256:
            import_error(
                "Each source record needs a unique ID of 1–256 characters."
            )
    else:
        fields = entry["fields"]
        identity = duplicate_key(
            fields["title"],
            fields["company"],
            fields.get("url"),
            fields.get("appliedDate"),
        )
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False).encode()
    ).hexdigest()


def merge_fields(current, incoming, baseline):
    changes, conflicts, accepted = {}, [], dict(baseline)
    for name, value in incoming.items():
        local, previous = current.get(name), baseline.get(name)
        if local in (value, previous):
            accepted[name] = value
            if local != value:
                changes[name] = value
        elif value != previous:
            conflicts.append(FIELD_LABELS[name])
    return changes, conflicts, accepted


def existing_candidates(user_id):
    candidates = {}
    for row in (
        JobApplication.for_user(user_id)
        .with_entities(
            JobApplication.id,
            JobApplication.job_title,
            JobApplication.company,
            JobApplication.job_url,
            JobApplication.applied_on,
        )
        .yield_per(500)
    ):
        candidates.setdefault(duplicate_key(*row[1:]), []).append(row[0])
    return candidates


def plan_entry(entry, record, candidates, user_id, reserved):
    fields = entry["fields"]
    entry.update(changes={}, conflicts=[], record=record, job=None)
    if record:
        job = (
            JobApplication.for_user(user_id, include_deleted=True)
            .filter_by(id=record.application_id)
            .populate_existing()
            .first()
        )
        if not job:
            import_error(
                "A linked application is unavailable. Reconnect the source."
            )
        entry["job"] = job
        if job.deleted_at:
            entry["decision"] = "Preserve deletion"
            return
        changes, conflicts, baseline = merge_fields(
            serialize_application(job), fields, record.baseline
        )
        entry.update(
            changes=changes,
            conflicts=conflicts,
            baseline=baseline,
            decision="Update" if changes else "Unchanged",
        )
        return
    key = duplicate_key(
        fields["title"],
        fields["company"],
        fields.get("url"),
        fields.get("appliedDate"),
    )
    matches = [
        job_id for job_id in candidates.get(key, []) if job_id not in reserved
    ]
    if len(matches) > 1:
        import_error(
            "Multiple tracker jobs match. Resolve duplicates before syncing."
        )
    if matches:
        job = (
            JobApplication.for_user(user_id)
            .filter_by(id=matches[0])
            .populate_existing()
            .one()
        )
        reserved.add(job.id)
        current = serialize_application(job)
        entry.update(
            job=job,
            decision="Link existing",
            conflicts=[
                FIELD_LABELS[name]
                for name, value in fields.items()
                if current.get(name) != value
            ],
        )
    else:
        entry["decision"] = "Create"
    entry["baseline"] = fields


def source_preview(batch, options):
    validate_options(batch, options)
    connection = batch_connection(batch)
    sheet = batch.payload[options["sheet"]]
    rows = row_preview(sheet, options)
    for entry in rows:
        if entry["error"]:
            continue
        try:
            entry["fields"] = sync_fields(entry, options)
            entry["source_key"] = source_key(sheet, entry, options)
        except ServiceError as error:
            entry["error"] = str(error)
    keys = Counter(
        entry.get("source_key") for entry in rows if not entry["error"]
    )
    records = {
        record.source_key: record
        for record in SourceRecord.query.filter_by(
            connection_id=connection.id, user_id=batch.user_id
        )
        .populate_existing()
        .all()
    }
    candidates = existing_candidates(batch.user_id)
    reserved = {record.application_id for record in records.values()}
    counts = dict.fromkeys(
        (
            "created",
            "updated",
            "linked",
            "unchanged",
            "conflicts",
            "invalid",
            "deleted",
            "missing",
        ),
        0,
    )
    decisions = {
        "Create": "created",
        "Update": "updated",
        "Link existing": "linked",
        "Unchanged": "unchanged",
        "Preserve deletion": "deleted",
    }
    for entry in rows:
        entry["conflicts"] = []
        if not entry["error"]:
            try:
                if keys[entry["source_key"]] > 1:
                    import_error(
                        "Source IDs must be unique. Choose a unique ID column."
                    )
                plan_entry(
                    entry,
                    records.get(entry["source_key"]),
                    candidates,
                    batch.user_id,
                    reserved,
                )
            except ServiceError as error:
                entry["error"] = str(error)
        if entry["error"]:
            counts["invalid"] += 1
            entry["decision"] = "Invalid"
        else:
            counts[decisions[entry["decision"]]] += 1
            counts["conflicts"] += bool(entry["conflicts"])
    counts["missing"] = len(set(records) - set(keys))
    return rows, counts


def commit_source_batch_locked(batch):
    """The shared batch handler owns the account lock and transaction."""
    connection = batch_connection(batch)
    rows, counts = source_preview(batch, batch.options)
    if counts["invalid"] and not batch.options["skip_invalid"]:
        import_error("Resolve invalid rows or explicitly choose to skip them.")
    options = dict(batch.options)
    sheet = batch.payload[options["sheet"]]
    for entry in rows:
        if entry["error"] or entry["decision"] == "Preserve deletion":
            continue
        job = entry["job"]
        if entry["decision"] == "Create":
            job = JobApplication(user_id=batch.user_id)
            fields = {"status": options["default_status"], **entry["fields"]}
            write_application(
                job, validate_fields(fields, create=True), source="source_sync"
            )
        elif entry["changes"]:
            write_application(
                job,
                validate_fields(entry["changes"]),
                version=job.version,
                source="source_sync",
            )
        record = entry["record"]
        if record:
            record.baseline = entry["baseline"]
        else:
            db.session.add(
                SourceRecord(
                    connection_id=connection.id,
                    user_id=batch.user_id,
                    source_key=entry["source_key"],
                    application_id=job.id,
                    baseline=entry["baseline"],
                )
            )
    reference = dict(connection.reference)
    if sheet.get("sheet_id"):
        reference["gid"] = sheet["sheet_id"]
    if sheet.get("data_source_id"):
        reference["data_source_id"] = sheet["data_source_id"]
    connection.reference = reference
    connection.columns = layout(sheet, options["header"])[0]
    options["sheet"] = 0
    connection.options = options
    connection.active = True
    connection.version += 1
    connection.last_synced_at = _utcnow()
    connection.last_result = counts
    connection.last_error = None
    from app.source_connections import next_sync

    connection.next_sync_at = next_sync(connection)
    finish_batch(batch, counts)
    return counts
