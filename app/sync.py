"""Idempotent mutations and immutable, commit-ordered changes."""

import hashlib
import json

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import func

from app.contracts import (
    DEFAULT_FIELDS,
    ServiceError,
    expected_version,
    identifier,
    project_application,
    strict_object,
    validate_fields,
    validate_history,
)
from app.database import database_transaction
from app.devices import require_active_device
from app.extensions import db
from app.models import (
    ApplicationMapping,
    ChangeEntry,
    JobApplication,
    MutationReceipt,
    User,
)
from app.record_updates import (
    lock_account,
    tombstone_application,
    write_application,
)
from app.uploads import delete_resume

OPERATIONS = {"create", "update", "delete", "map"}


def mutation_contract(body, device):
    strict_object(
        body,
        {
            "mutationId",
            "operation",
            "applicationId",
            "expectedVersion",
            "fields",
            "localRecordId",
            "statusHistory",
        },
        "Mutation",
    )
    identifier(body.get("mutationId"), "mutationId")
    operation = body.get("operation")
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ServiceError(
            "validation_error", "Unknown mutation operation.", 422
        )
    if operation == "create":
        if "applicationId" in body or "expectedVersion" in body:
            raise ServiceError(
                "validation_error",
                "New applications cannot choose IDs or versions.",
                422,
            )
    else:
        identifier(body.get("applicationId"), "applicationId", 36)
        expected_version(body.get("expectedVersion"))
    if "localRecordId" in body:
        identifier(body["localRecordId"], "localRecordId", 256)
    if operation == "map" and "localRecordId" not in body:
        raise ServiceError(
            "validation_error", "Mapping requires localRecordId.", 422
        )
    if operation in {"delete", "map"} and (
        "fields" in body or "statusHistory" in body
    ):
        raise ServiceError(
            "validation_error",
            "This operation does not accept record fields or history.",
            422,
        )
    if operation == "delete" and "localRecordId" in body:
        raise ServiceError(
            "validation_error", "Delete does not accept a mapping.", 422
        )
    values = validate_fields(
        body.get("fields", {}),
        DEFAULT_FIELDS | set(device.optional_fields),
        create=operation == "create",
    )
    history = validate_history(body.get("statusHistory", []))
    return values, history


def _mutation_job(body, device):
    if body["operation"] == "create":
        if "localRecordId" in body:
            mapping = ApplicationMapping.query.filter_by(
                user_id=device.user_id,
                installation_id=device.installation_id,
                local_record_id=body["localRecordId"],
            ).first()
            if mapping:
                raise ServiceError(
                    "mapping_conflict",
                    "Local record already has a cloud mapping; "
                    "pull its current state.",
                    409,
                )
        return JobApplication(user_id=device.user_id)
    job = (
        JobApplication.for_user(device.user_id, include_deleted=True)
        .filter_by(public_id=body["applicationId"])
        .first()
    )
    if not job:
        raise ServiceError("not_found", "Application not found.", 404)
    return job


def mutate(body, device):
    values, history = mutation_contract(body, device)
    request_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    retired_resume = None
    with database_transaction():
        lock_account(device.user_id)
        require_active_device(device)
        receipt = MutationReceipt.query.filter_by(
            device_id=device.id,
            user_id=device.user_id,
            mutation_id=body["mutationId"],
        ).first()
        if receipt:
            if receipt.request_hash != request_hash:
                raise ServiceError(
                    "mutation_reused",
                    "Mutation ID was already used with a different request.",
                    409,
                )
            return receipt.response
        job = _mutation_job(body, device)
        if body["operation"] == "delete":
            payload, retired_resume = tombstone_application(
                job,
                body["expectedVersion"],
                source="device",
                mutation_id=body["mutationId"],
            )
        else:
            payload = write_application(
                job,
                values,
                version=body.get("expectedVersion"),
                source="device",
                installation_id=device.installation_id,
                local_record_id=body.get("localRecordId"),
                history=history,
                mutation_id=body["mutationId"],
            )
        result = {
            "mutationId": body["mutationId"],
            "application": project_application(
                payload, device.optional_fields, device.installation_id
            ),
        }
        db.session.add(
            MutationReceipt(
                user_id=device.user_id,
                device_id=device.id,
                mutation_id=body["mutationId"],
                request_hash=request_hash,
                response=result,
            )
        )
    delete_resume(retired_resume)
    return result


def _signer():
    return URLSafeSerializer(current_app.secret_key, salt="tracker-v1-cursor")


def _cursor(device, kind, last, upper):
    return _signer().dumps(
        {
            "device": device.id,
            "account": device.user_id,
            "kind": kind,
            "last": last,
            "upper": upper,
        }
    )


def _read_cursor(token, device, kind):
    try:
        value = _signer().loads(token)
        valid = (
            isinstance(value, dict)
            and value.get("device") == device.id
            and value.get("account") == device.user_id
            and value.get("kind") == kind
        )
        valid = valid and all(
            type(value.get(key)) is int and value[key] >= 0
            for key in ("last", "upper")
        )
        valid = valid and value["last"] <= value["upper"]
        if valid:
            return value["last"], value["upper"]
    except BadData:
        pass
    raise ServiceError(
        "invalid_cursor",
        "Cursor is invalid for this device. Restart with a snapshot.",
        422,
    )


def feed_page(device, *, token=None, snapshot=False, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ServiceError(
            "validation_error", "limit must be between 1 and 100.", 422
        )
    kind = "snapshot" if snapshot else "changes"
    current = (
        db.session.query(User.feed_sequence)
        .filter(User.id == device.user_id)
        .scalar()
    )
    last, upper = _read_cursor(token, device, kind) if token else (0, current)
    if upper > current:
        raise ServiceError(
            "cursor_reset_required",
            "The database history changed. Restart with a snapshot.",
            409,
        )
    if not snapshot and last == upper:
        upper = current
    query = ChangeEntry.query.filter_by(user_id=device.user_id).filter(
        ChangeEntry.sequence > last, ChangeEntry.sequence <= upper
    )
    if snapshot:
        latest = (
            db.session.query(func.max(ChangeEntry.sequence).label("sequence"))
            .filter(
                ChangeEntry.user_id == device.user_id,
                ChangeEntry.sequence <= upper,
            )
            .group_by(ChangeEntry.application_id)
            .subquery()
        )
        query = query.join(latest, ChangeEntry.sequence == latest.c.sequence)
    rows = query.order_by(ChangeEntry.sequence).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    after = rows[-1].sequence if has_more else upper
    entries = [
        {
            "sequence": row.sequence,
            "source": row.source,
            "mutationId": row.mutation_id,
            "application": project_application(
                row.payload, device.optional_fields, device.installation_id
            ),
        }
        for row in rows
    ]
    result = {
        "entries": entries,
        "cursor": _cursor(device, kind, after, upper),
        "hasMore": has_more,
        "watermark": upper,
    }
    if snapshot and not has_more:
        result["changesCursor"] = _cursor(device, "changes", upper, upper)
    return result
