"""HTTP import workflow: choose a source, map, review, then confirm."""

import csv
import io

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.contracts import ServiceError
from app.database import database_transaction
from app.exports import csv_cell
from app.extensions import db, limiter
from app.forms import GoogleLoginForm
from app.google_login import (
    PROVIDER_ERRORS,
    clear_google_flow,
    start_google_flow,
)
from app.google_sheets import read_public_sheet, sheet_reference
from app.import_mapping import (
    FIELD_LABELS,
    layout,
    normalized,
    status_values,
    suggested_status,
)
from app.import_readers import MAX_BYTES, import_error, read_file
from app.import_service import (
    cleanup_imports,
    commit_batch,
    create_batch,
    get_batch,
    initial_options,
    options_digest,
    preview,
    save_options,
)
from app.models import JOB_STATUSES
from app.record_updates import lock_account

imports = Blueprint("imports", __name__)


def source_tables():
    source = request.form.get("source", "file")
    if source == "file":
        file = request.files.get("file")
        if not file:
            import_error("Choose a file first.")
        return read_file(file.stream.read(MAX_BYTES + 1), file.filename or "")
    if source == "paste":
        return read_file(request.form.get("text", "").encode(), "table.tsv")
    if source == "public":
        return read_public_sheet(
            sheet_reference(request.form.get("sheet_url", ""))
        )
    import_error("Choose a supported source.")


@imports.route("/imports", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def index():
    cleanup_imports()
    if request.method == "POST":
        try:
            if request.form.get("source") == "private":
                if not current_app.config["GOOGLE_LOGIN_ENABLED"]:
                    import_error(
                        "Google access is not configured. "
                        "Upload an export or paste the table instead."
                    )
                return start_google_flow(
                    GoogleLoginForm(
                        formdata=None,
                        intent="sheets",
                        sheet_url=request.form.get("sheet_url", ""),
                    )
                )
            batch = create_batch(current_user.id, source_tables())
            return redirect(url_for("imports.mapping", batch_id=batch.id))
        except ServiceError as error:
            flash(str(error), "danger")
        except PROVIDER_ERRORS:
            clear_google_flow()
            flash(
                "Google is temporarily unavailable. "
                "Upload an export or try again.",
                "danger",
            )
    return render_template("imports/source.html")


def form_integer(name, default):
    value = request.values.get(name, str(default))
    if not value.isascii() or not value.isdigit() or len(value) > 5:
        import_error("Choose valid sheet and header numbers.")
    return int(value)


def mapped_options(options, labels, rows):
    options.update(
        mapping=[
            request.form.get(f"column_{index}", "")
            for index in range(len(labels))
        ],
        date_order=request.form.get("date_order", "auto"),
        default_status=request.form.get("default_status", "shortlisted"),
        duplicates=request.form.get("duplicates", "skip"),
        preserve=request.form.get("preserve") == "yes",
        skip_invalid=request.form.get("skip_invalid") == "yes",
    )
    values = status_values(rows, options["mapping"])
    options["status_map"] = {
        normalized(value): request.form.get(
            "status_" + normalized(value), suggested_status(value)
        )
        for value in values
    }
    return options


@imports.route("/imports/<batch_id>/map", methods=["GET", "POST"])
@login_required
def mapping(batch_id):
    batch = get_batch(current_user.id, batch_id)
    if batch.result:
        return redirect(url_for("imports.review", batch_id=batch_id))
    sheet_index = form_integer("sheet", 0)
    header = form_integer("header", 1) if "header" in request.values else None
    options = (
        batch.options
        if request.method == "GET" and not request.args and batch.options
        else initial_options(batch, sheet_index, header)
    )
    labels, rows = layout(batch.payload[options["sheet"]], options["header"])
    if request.method == "POST":
        options = mapped_options(options, labels, rows)
        try:
            if request.form.get("action") == "refresh":
                return mapping_response(batch, options, labels, rows)
            save_options(batch, options)
            return redirect(url_for("imports.review", batch_id=batch_id))
        except ServiceError as error:
            flash(str(error), "danger")
    return mapping_response(batch, options, labels, rows)


def mapping_response(batch, options, labels, rows):
    return render_template(
        "imports/mapping.html",
        batch=batch,
        options=options,
        labels=labels,
        sample=rows[:5],
        fields=FIELD_LABELS,
        statuses=JOB_STATUSES,
        status_values=status_values(rows, options["mapping"]),
        normalized=normalized,
        suggested_status=suggested_status,
    )


@imports.get("/imports/<batch_id>/review")
@login_required
def review(batch_id):
    batch = get_batch(current_user.id, batch_id)
    if batch.result:
        return render_template("imports/complete.html", result=batch.result)
    if not batch.options:
        return redirect(url_for("imports.mapping", batch_id=batch_id))
    rows, counts = preview(batch, batch.options)
    return render_template(
        "imports/review.html",
        batch=batch,
        rows=rows[:100],
        total=len(rows),
        counts=counts,
        digest=options_digest(batch.options),
    )


@imports.post("/imports/<batch_id>/confirm")
@login_required
@limiter.limit("10 per minute")
def confirm(batch_id):
    try:
        commit_batch(current_user.id, batch_id, request.form.get("digest", ""))
    except ServiceError as error:
        if error.status in {404, 410}:
            raise
        flash(str(error), "danger")
        return redirect(url_for("imports.review", batch_id=batch_id))
    return redirect(url_for("imports.review", batch_id=batch_id))


@imports.get("/imports/<batch_id>/report.csv")
@login_required
def report(batch_id):
    batch = get_batch(current_user.id, batch_id)
    if not batch.options:
        abort(404)
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
                csv_cell(row["error"]),
                *[
                    csv_cell(row["fields"].get(name, ""))
                    for name in FIELD_LABELS
                ],
                *[csv_cell(value) for value in row["source"]],
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="import-review.csv"'
        },
    )


@imports.post("/imports/<batch_id>/cancel")
@login_required
def cancel(batch_id):
    batch = get_batch(current_user.id, batch_id)
    with database_transaction():
        lock_account(current_user.id)
        db.session.delete(batch)
    flash("Import preview discarded.", "info")
    return redirect(url_for("imports.index"))
