"""Shared application input contracts and safe wire representations."""

import re
from datetime import date, datetime, timezone

from email_validator import EmailNotValidError, validate_email

from app.models import JOB_STATUSES
from app.utils import is_http_url

# API name: (model attribute, scalar type, maximum text length).
FIELD_SPECS = {
    "title": ("job_title", "text", 128),
    "company": ("company", "text", 128),
    "url": ("job_url", "url", 512),
    "board": ("board", "text", 128),
    "location": ("location", "text", 128),
    "status": ("status", "status", 64),
    "appliedDate": ("applied_on", "date", None),
    "followUpDate": ("follow_up_on", "date", None),
    "postedAt": ("posted_at", "timestamp", None),
    "postedAtApproximate": ("posted_at_approximate", "bool", None),
    "applicants": ("applicants", "observation", None),
    "note": ("notes", "multiline", 20000),
    "contactName": ("contact_person", "text", 128),
    "contactEmail": ("contact_email", "email", 254),
    "contactPhone": ("contact_phone", "text", 80),
    "salary": ("salary", "text", 64),
}
OPTIONAL_FIELDS = {
    "note",
    "contactName",
    "contactEmail",
    "contactPhone",
    "salary",
}
DEFAULT_FIELDS = set(FIELD_SPECS) - OPTIONAL_FIELDS
RELATIONS = {"exact", "less-than", "more-than", "at-least"}


class ServiceError(ValueError):
    def __init__(self, code, message, status=400, *, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details


def invalid(message):
    raise ServiceError("validation_error", message, 422)


def strict_object(value, allowed, label="Object"):
    if not isinstance(value, dict) or set(value) - set(allowed):
        invalid(f"{label} contains unknown or forbidden fields.")
    return value


def bounded_text(value, label, maximum, *, multiline=False, trim=True):
    if not isinstance(value, str) or len(value) > maximum:
        invalid(f"{label} must be text of at most {maximum} characters.")
    controls = {"\n", "\r", "\t"} if multiline else set()
    if any(
        (ord(c) < 32 and c not in controls) or ord(c) == 127 for c in value
    ):
        invalid(f"{label} contains unsupported control characters.")
    return value.strip() if trim else value


def identifier(value, label, maximum=128):
    value = bounded_text(value, label, maximum, trim=False)
    if not value or not value.strip():
        invalid(f"{label} must not be empty.")
    return value


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value
    ):
        invalid("Calendar dates must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        invalid("Calendar date does not exist.")


def timestamp(value):
    pattern = (
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
        r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)"
    )
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        invalid("Event timestamps must be ISO timestamps with a UTC offset.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        invalid("Invalid event timestamp.")


def utc(value):
    if value is None:
        return None
    return (
        value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    )


def iso(value):
    if isinstance(value, datetime):
        return (
            utc(value)
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return value.isoformat() if value else None


def observation(value):
    strict_object(
        value,
        {"count", "relation", "label", "source", "url", "observedAt"},
        "Applicant observation",
    )
    count = value.get("count")
    if count is not None and (
        type(count) is not int or not 0 <= count <= 10**9
    ):
        invalid("Applicant count must be a nonnegative integer or null.")
    relation = value.get("relation")
    if relation is not None and (
        not isinstance(relation, str) or relation not in RELATIONS
    ):
        invalid("Unknown applicant relation.")
    if count is not None and (
        not relation or not value.get("source") or not value.get("observedAt")
    ):
        invalid(
            "Known applicant counts require relation, source, and observedAt."
        )
    result = {"count": count, "relation": relation}
    for name in ("label", "source", "url"):
        item = value.get(name)
        if item is not None:
            item = bounded_text(item, name, 512 if name == "url" else 128)
            if name == "url" and item and not is_http_url(item):
                invalid("Observation URL must use HTTP or HTTPS.")
        result[name] = item
    result["observedAt"] = (
        iso(timestamp(value["observedAt"]))
        if value.get("observedAt") is not None
        else None
    )
    if count is not None and not result["source"]:
        invalid("Known applicant counts require a nonempty source.")
    return result


def parse_scalar(name, value):
    _, kind, maximum = FIELD_SPECS[name]
    if value is None:
        if name in {"title", "company", "status", "postedAtApproximate"}:
            invalid(f"{name} cannot be null.")
        return None
    parsers = {
        "date": calendar_date,
        "timestamp": timestamp,
        "observation": observation,
    }
    if kind in parsers:
        return parsers[kind](value)
    if kind == "bool":
        if type(value) is not bool:
            invalid(f"{name} must be a boolean.")
        return value
    value = bounded_text(value, name, maximum, multiline=kind == "multiline")
    if name in {"title", "company"} and not value:
        invalid(f"{name} is required.")
    if kind == "status" and value not in JOB_STATUSES:
        invalid("Unknown application status.")
    if kind == "url" and value and not is_http_url(value):
        invalid("Job URL must use HTTP or HTTPS.")
    return contact_email(value) if kind == "email" and value else value


def contact_email(value):
    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError:
        invalid("Invalid contact email.")


def validate_fields(fields, allowed=None, *, create=False):
    allowed = set(FIELD_SPECS) if allowed is None else allowed
    strict_object(fields, allowed, "Application")
    if create and not {"title", "company"} <= set(fields):
        invalid("New applications require title and company.")
    return {
        FIELD_SPECS[name][0]: parse_scalar(name, value)
        for name, value in fields.items()
    }


def expected_version(value):
    if type(value) is not int or not 1 <= value <= 2**31 - 1:
        invalid("expectedVersion must be a positive integer.")
    return value


def form_version(value):
    """Apply the same version bounds to browser text and JSON integers."""
    parsed = (
        int(value)
        if isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and len(value) <= 10
        else None
    )
    return expected_version(parsed)


def validate_history(events):
    if not isinstance(events, list) or len(events) > 100:
        invalid("statusHistory must contain at most 100 source events.")
    result = []
    seen = set()
    for event in events:
        strict_object(
            event,
            {"sourceEventId", "status", "fromStatus", "occurredAt"},
            "Status event",
        )
        source_id = identifier(event.get("sourceEventId"), "sourceEventId")
        if source_id in seen:
            invalid("Duplicate sourceEventId within statusHistory.")
        seen.add(source_id)
        status = event.get("status")
        previous = event.get("fromStatus")
        if status not in JOB_STATUSES or (
            previous is not None and previous not in JOB_STATUSES
        ):
            invalid("Unknown status in history.")
        result.append(
            {
                "source_event_id": source_id,
                "status": status,
                "from_status": previous,
                "occurred_at": timestamp(event["occurredAt"])
                if event.get("occurredAt") is not None
                else None,
            }
        )
    return result


def serialize_application(job):
    result = {
        name: iso(getattr(job, attr))
        if kind in {"date", "timestamp"}
        else getattr(job, attr)
        for name, (attr, kind, _) in FIELD_SPECS.items()
    }
    result.update(
        id=job.public_id,
        version=job.version,
        deletedAt=iso(job.deleted_at),
        createdAt=iso(job.created_at),
        updatedAt=iso(job.updated_date),
    )
    result["url"] = job.safe_job_url
    if isinstance(job.applicants, dict):
        result["applicants"] = {
            **job.applicants,
            "url": job.safe_observation_url,
        }
    result["statusHistory"] = [
        {
            "id": item.public_id,
            "status": item.status,
            "fromStatus": item.from_status,
            "source": item.source,
            "installationId": item.installation_id,
            "sourceEventId": item.source_event_id,
            "occurredAt": iso(item.occurred_at),
            "recordedAt": iso(item.recorded_at),
        }
        for item in job.history
    ]
    result["mappings"] = [
        {
            "installationId": item.installation_id,
            "localRecordId": item.local_record_id,
        }
        for item in job.mappings
    ]
    return result


def project_application(payload, optional_fields=(), installation_id=None):
    metadata = {
        "id",
        "version",
        "deletedAt",
        "createdAt",
        "updatedAt",
        "statusHistory",
        "mappings",
    }
    allowed = DEFAULT_FIELDS | set(optional_fields) | metadata
    result = {key: value for key, value in payload.items() if key in allowed}
    if installation_id is not None:
        result["mappings"] = [
            item
            for item in payload.get("mappings", [])
            if item["installationId"] == installation_id
        ]
    if payload.get("deletedAt"):
        result = {
            key: value
            for key, value in result.items()
            if key in {"id", "version", "deletedAt", "updatedAt", "mappings"}
        }
    return result
