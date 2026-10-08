"""Connect a source, review its mapping, then pull later changes."""

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.contracts import ServiceError
from app.extensions import limiter
from app.forms import GoogleLoginForm
from app.google_login import (
    PROVIDER_ERRORS,
    clear_google_flow,
    start_google_flow,
)
from app.google_sheets import sheet_reference
from app.import_readers import import_error
from app.models import SourceConnection
from app.notion_sources import notion_id
from app.sheet_ranges import sheet_range
from app.source_connections import (
    connection_batch,
    create_connection,
    get_connection,
    record_sync_error,
    remove_connection,
    set_schedule,
)
from app.source_credentials import credential_cipher

sources = Blueprint("sources", __name__)


def interval_choice():
    value = request.form.get("interval", "0")
    if value not in {"0", "15", "60"}:
        import_error("Choose manual syncing, every 15 minutes, or hourly.")
    return int(value)


def source_reference(provider):
    if provider in {"google_public", "google_private"}:
        reference = sheet_reference(request.form.get("sheet_url", ""))
        reference["range"] = sheet_range(request.form.get("cell_range", ""))
        return reference
    if provider == "notion":
        kind = request.form.get("notion_kind", "database")
        if kind not in {"database", "data_source"}:
            import_error("Choose a Notion database or data source.")
        return {
            "id": notion_id(request.form.get("notion_url", "")),
            "kind": kind,
        }
    import_error("Choose a supported source.")


def authorize_google(connection):
    if connection.provider != "google_private":
        import_error("Choose a private Google Sheets source to authorize.")
    if not current_app.config["GOOGLE_LOGIN_ENABLED"]:
        import_error(
            "Google access is not configured. "
            "Use a shared link or file import."
        )
    credential_cipher()
    reference = connection.reference
    url = f"https://docs.google.com/spreadsheets/d/{reference['id']}/edit"
    if reference["gid"] is not None:
        url += "#gid=" + reference["gid"]
    return start_google_flow(
        GoogleLoginForm(
            formdata=None,
            intent="sheet_sync",
            connection_id=connection.id,
            sheet_url=url,
        )
    )


def batch_redirect(batch):
    endpoint = "imports.review" if batch.options else "imports.mapping"
    return redirect(url_for(endpoint, batch_id=batch.id))


@sources.get("/sources")
@login_required
def index():
    connections = (
        SourceConnection.query.filter_by(user_id=current_user.id)
        .order_by(SourceConnection.created_at.desc())
        .all()
    )
    return render_template("sources/index.html", connections=connections)


@sources.post("/sources")
@login_required
@limiter.limit("10 per minute; 60 per hour")
def create():
    try:
        return create_source_preview(request.form.get("provider", ""))
    except ServiceError as error:
        flash(str(error), "danger")
    except PROVIDER_ERRORS:
        clear_google_flow()
        flash(
            "Google is temporarily unavailable. Try connecting again.",
            "danger",
        )
    return redirect(url_for("sources.index"))


def create_source_preview(provider):
    """Start setup from the import hub or a legacy source form."""
    connection = None
    try:
        if (
            provider == "google_private"
            and not current_app.config["GOOGLE_LOGIN_ENABLED"]
        ):
            import_error(
                "Google access is not configured. "
                "Choose a shared link or Notion."
            )
        connection = create_connection(
            current_user.id,
            request.form.get("name", ""),
            provider,
            source_reference(provider),
            token=request.form.get("notion_token"),
            interval=interval_choice(),
        )
        if provider == "google_private":
            return authorize_google(connection)
        return batch_redirect(connection_batch(connection))
    except ServiceError as error:
        if connection:
            record_sync_error(
                current_user.id, connection.id, connection.version, str(error)
            )
        raise


@sources.post("/sources/<connection_id>/read")
@login_required
@limiter.limit("10 per minute; 60 per hour")
def read(connection_id):
    connection = get_connection(current_user.id, connection_id)
    version = connection.version
    try:
        if request.form.get("action") == "authorize" or (
            connection.provider == "google_private"
            and not connection.credential_ciphertext
        ):
            return authorize_google(connection)
        return batch_redirect(
            connection_batch(
                connection, remap=request.form.get("action") == "configure"
            )
        )
    except ServiceError as error:
        record_sync_error(current_user.id, connection_id, version, str(error))
        flash(str(error), "danger")
    except PROVIDER_ERRORS:
        clear_google_flow()
        flash(
            "Google is temporarily unavailable. Try connecting again.",
            "danger",
        )
    return redirect(url_for("sources.index"))


@sources.post("/sources/<connection_id>/schedule")
@login_required
def schedule(connection_id):
    set_schedule(current_user.id, connection_id, interval_choice())
    flash("Sync schedule updated.", "success")
    return redirect(url_for("sources.index"))


@sources.post("/sources/<connection_id>/disconnect")
@login_required
def disconnect(connection_id):
    remove_connection(current_user.id, connection_id)
    flash(
        "Source disconnected. Your tracker applications are retained.",
        "success",
    )
    return redirect(url_for("sources.index"))
