"""HTTP import workflow: choose a source, map, review, then confirm."""

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
from app.import_reports import review_csv
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
from app.notion_sources import notion_id, read_notion
from app.record_updates import lock_account
from app.routes.sources import create_source_preview
from app.sheet_ranges import sheet_range

imports = Blueprint("imports", __name__)


def import_choices():
    """Normalize the shared setup form and older one-time import requests."""
    source = request.form.get("source", "file")
    if source == "google":
        source = request.form.get("sheet_access", "public")
        if source not in {"public", "private"}:
            import_error("Choose shared link or private Google access.")
    mode = request.form.get("import_mode", "once")
    if mode not in {"once", "sync"}:
        import_error("Choose a one-time import or a connected source.")
    return source, mode


def source_tables(source):
    if source == "file":
        file = request.files.get("file")
        if not file:
            import_error("Choose a file first.")
        return read_file(file.stream.read(MAX_BYTES + 1), file.filename or "")
    if source == "paste":
        return read_file(request.form.get("text", "").encode(), "table.tsv")
    if source == "public":
        return read_public_sheet(
            sheet_reference(request.form.get("sheet_url", "")),
            sheet_range(request.form.get("cell_range", "")),
        )
    if source == "notion":
        kind = request.form.get("notion_kind", "database")
        if kind not in {"database", "data_source"}:
            import_error("Choose a Notion database or data source.")
        return read_notion(
            {
                "id": notion_id(request.form.get("notion_url", "")),
                "kind": kind,
            },
            request.form.get("notion_token", ""),
        )
    import_error("Choose a supported source.")


@imports.route("/imports", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def index():
    cleanup_imports()
    if request.method == "POST":
        try:
            source, mode = import_choices()
            if mode == "sync":
                provider = {
                    "public": "google_public",
                    "private": "google_private",
                    "notion": "notion",
                }.get(source)
                if not provider:
                    import_error("Choose Google Sheets or Notion for syncing.")
                return create_source_preview(provider)
            if source == "private":
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
                        cell_range=request.form.get("cell_range", ""),
                    )
                )
            batch = create_batch(current_user.id, source_tables(source))
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
    if "identity_column" in options:
        options["identity_column"] = (
            -1
            if request.form.get("identity_column", "-1") == "-1"
            else form_integer("identity_column", 0)
        )
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
        template = (
            "sources/complete.html"
            if batch.connection_id
            else "imports/complete.html"
        )
        return render_template(template, result=batch.result)
    if not batch.options:
        return redirect(url_for("imports.mapping", batch_id=batch_id))
    rows, counts = preview(batch, batch.options)
    template = (
        "sources/review.html" if batch.connection_id else "imports/review.html"
    )
    return render_template(
        template,
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


@imports.get("/imports/<batch_id>/report.csv")
@login_required
def report(batch_id):
    batch = get_batch(current_user.id, batch_id)
    if not batch.options:
        abort(404)
    return Response(
        review_csv(batch),
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
