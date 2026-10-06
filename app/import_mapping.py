"""Explainable mapping suggestions and conservative date/status conversion."""

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

from app.contracts import ServiceError, validate_fields
from app.import_readers import MAX_ROWS, import_error
from app.models import JOB_STATUSES

FIELD_LABELS = {
    "title": "Job title",
    "company": "Company",
    "url": "Job link",
    "location": "Location",
    "status": "Status",
    "appliedDate": "Applied date",
    "followUpDate": "Follow-up date",
    "board": "Job board / source",
    "salary": "Salary",
    "contactName": "Contact name",
    "contactEmail": "Contact email",
    "contactPhone": "Contact phone",
    "note": "Notes",
}
ALIASES = {
    "title": (
        "title|job title|job_title|position|role|job role|"
        "position title|designation|stelle|poste"
    ),
    "company": (
        "company|company name|employer|organization|organisation|"
        "business|unternehmen|entreprise"
    ),
    "url": (
        "url|job_url|job link|job url|posting url|application link|"
        "link|job posting|posting link"
    ),
    "location": "location|city|place|office|work location|standort",
    "status": (
        "status|application status|stage|application stage|"
        "progress|outcome|pipeline"
    ),
    "appliedDate": (
        "appliedDate|applied_on|applied on|applied date|date applied|"
        "application date|application sent|submitted on"
    ),
    "followUpDate": (
        "followUpDate|follow_up_on|follow up|follow-up date|"
        "follow up on|next follow up|reminder date"
    ),
    "board": "board|source|job board|platform|found on|job source",
    "salary": "salary|salary range|pay|compensation|package",
    "contactName": (
        "contactName|contact_person|contact person|contact|"
        "recruiter|recruiter name|hiring manager"
    ),
    "contactEmail": (
        "contactEmail|contact_email|contact email|recruiter email|email|e-mail"
    ),
    "contactPhone": (
        "contactPhone|contact_phone|phone|phone number|"
        "recruiter phone|telephone"
    ),
    "note": "note|notes|comments|comment|remarks|details|description",
}
STATUS_ALIASES = {
    "shortlisted": (
        "wishlist|saved|to apply|not applied|interested|shortlist|bookmark"
    ),
    "applied": (
        "application sent|submitted|application submitted|in progress|pending"
    ),
    "interviewing": (
        "interview|interview scheduled|phone screen|screening|"
        "assessment|technical interview|final interview"
    ),
    "offer": "offer received|offered|job offer",
    "accepted": "offer accepted|hired|joined",
    "rejected": "declined|not selected|unsuccessful|rejection",
    "closed": "withdrawn|position closed|no longer available",
    "skipped": "skip|not interested",
}


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(char for char in value if char.isalnum())


_HEADER_ALIASES = {
    field: {normalized(alias) for alias in aliases.split("|")}
    for field, aliases in ALIASES.items()
}
_STATUS_LOOKUP = {
    normalized(alias): status
    for status in JOB_STATUSES
    for alias in [status, *STATUS_ALIASES[status].split("|")]
}


def header_match(value):
    key = normalized(str(value)[:128])
    if not key:
        return "", 0
    scored = []
    for field, aliases in _HEADER_ALIASES.items():
        score = max(
            SequenceMatcher(None, key, alias).ratio() for alias in aliases
        )
        scored.append((score, field))
    scored.sort(reverse=True)
    best, second = scored[:2]
    return (
        (best[1], best[0])
        if best[0] == 1 or best[0] >= 0.86 and best[0] - second[0] >= 0.08
        else ("", 0)
    )


def suggested_header(rows):
    scores = []
    for index, row in enumerate(rows[:30]):
        matches = {header_match(value)[0] for value in row} - {""}
        score = len(matches) + (5 if {"title", "company"} <= matches else 0)
        scores.append((score, -index))
    score, negative_index = max(scores)
    return -negative_index + 1 if score >= 2 else 1


def layout(sheet, header):
    rows = sheet["rows"]
    if type(header) is not int or not 0 <= header <= min(len(rows), 30):
        import_error("Choose a header row between 1 and 30, or no header.")
    width = max((len(row) for row in rows), default=0)
    labels = list(rows[header - 1]) if header else []
    labels += [""] * (width - len(labels))
    labels = [
        value or f"Column {index + 1}" for index, value in enumerate(labels)
    ]
    data = [
        (number, row + [""] * (width - len(row)))
        for number, row in enumerate(
            rows[header:], start=header + sheet.get("start_row", 1)
        )
        if any(value.strip() for value in row)
    ]
    if len(data) > MAX_ROWS:
        import_error("Import at most 1,000 data rows at a time.")
    return labels, data


def suggested_mapping(labels, rows):
    mapping = [""] * len(labels)
    candidates = []
    for index, label in enumerate(labels):
        field, score = header_match(label)
        candidates.append((score, index, field))
    used = set()
    for _score, index, field in sorted(candidates, reverse=True):
        if field and field not in used:
            mapping[index] = field
            used.add(field)
    # Content inference is limited to unambiguous email/URL columns.
    for index, field in enumerate(mapping):
        if field:
            continue
        values = [
            row[index].strip() for _, row in rows[:20] if row[index].strip()
        ]
        if len(values) < 2:
            continue
        if all(value.startswith(("https://", "http://")) for value in values):
            inferred = "url"
        elif all(
            re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
            for value in values
        ):
            inferred = "contactEmail"
        else:
            continue
        if inferred not in used:
            mapping[index] = inferred
            used.add(inferred)
    return mapping


def suggested_status(value):
    return _STATUS_LOOKUP.get(normalized(value), "")


def status_values(rows, mapping):
    if "status" not in mapping:
        return []
    column = mapping.index("status")
    return sorted(
        {row[column].strip() for _, row in rows if row[column].strip()}
    )[:100]


def date_order(rows, mapping):
    orders = set()
    for column, field in enumerate(mapping):
        if field not in {"appliedDate", "followUpDate"}:
            continue
        for _, row in rows:
            match = re.fullmatch(
                r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", row[column].strip()
            )
            if match:
                first, second = map(int, match.group(1, 2))
                if first > 12:
                    orders.add("dmy")
                if second > 12:
                    orders.add("mdy")
    return next(iter(orders)) if len(orders) == 1 else "auto"


def import_date(value, order):
    match = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", value)
    if match:
        first, second, year = match.groups()
        if (
            order == "auto"
            and first != second
            and int(first) <= 12
            and int(second) <= 12
        ):
            import_error(
                "Ambiguous date: choose day/month/year or month/day/year."
            )
        if order == "auto":
            order = "dmy" if int(first) > 12 else "mdy"
        month, day = (second, first) if order == "dmy" else (first, second)
        value = f"{year}-{month:0>2}-{day:0>2}"
    for pattern in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    import_error("Unrecognized date. Use a full date including its year.")


def row_fields(row, labels, options):
    fields = {}
    extra = []
    for column, field in enumerate(options["mapping"]):
        value = row[column].strip()
        if not field:
            if options["preserve"] and value:
                extra.append(f"{labels[column]}: {value}")
            continue
        if not value:
            continue
        if field in {"appliedDate", "followUpDate"}:
            value = import_date(value, options["date_order"])
        if field == "status":
            value = options["status_map"].get(
                normalized(value)
            ) or suggested_status(value)
            if value not in JOB_STATUSES:
                import_error(
                    "Unknown status: choose its tracker status above."
                )
        fields[field] = value
    fields.setdefault("status", options["default_status"])
    if extra:
        fields["note"] = "\n\n".join(
            filter(
                None,
                [fields.get("note"), "Imported details:\n" + "\n".join(extra)],
            )
        )
    validate_fields(fields, create=True)
    return fields


def row_preview(sheet, options):
    labels, rows = layout(sheet, options["header"])
    header = [normalized(value) for value in labels]
    result = []
    for number, row in rows:
        if (
            options["header"]
            and [normalized(value) for value in row] == header
        ):
            continue
        entry = {"number": number, "fields": {}, "source": row, "error": ""}
        try:
            entry["fields"] = row_fields(row, labels, options)
        except ServiceError as error:
            entry["error"] = str(error)
            entry["fields"] = {
                field: row[column].strip()
                for column, field in enumerate(options["mapping"])
                if field
            }
        result.append(entry)
    return result
