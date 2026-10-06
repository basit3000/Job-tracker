"""Google sign-in and explicit linking; all starts are CSRF-protected POSTs."""

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_login import current_user, login_required

from app.contracts import ServiceError
from app.extensions import limiter
from app.forms import GoogleLoginForm
from app.google_accounts import GoogleAccountError, connect_google, google_user
from app.google_login import (
    PROVIDER_ERRORS,
    clear_google_flow,
    finish_google_flow,
    start_google_flow,
)
from app.routes.auth import finish_login
from app.security import AUTH_RATE_LIMIT

google_auth = Blueprint("google_auth", __name__)


@google_auth.get("/account")
@login_required
def account():
    return render_template("account.html", form=GoogleLoginForm(intent="link"))


@google_auth.post("/auth/google")
@limiter.limit(AUTH_RATE_LIMIT)
def start():
    if not current_app.config["GOOGLE_LOGIN_ENABLED"]:
        abort(404)
    form = GoogleLoginForm()
    if not form.validate_on_submit():
        abort(400)
    if current_user.is_authenticated and form.intent.data == "signin":
        return redirect(url_for("jobs.dashboard"))
    try:
        return start_google_flow(form)
    except GoogleAccountError as error:
        return sign_in_error(str(error), link=form.intent.data == "link")
    except PROVIDER_ERRORS:
        clear_google_flow()
        return sign_in_error(
            "Google is temporarily unavailable. Please try again.",
            link=form.intent.data == "link",
        )


@google_auth.get("/auth/google/callback")
@limiter.limit(AUTH_RATE_LIMIT)
def callback():
    if not current_app.config["GOOGLE_LOGIN_ENABLED"]:
        abort(404)
    try:
        flow, claims, access_token = finish_google_flow()
        if flow["intent"] == "sheets":
            from app.google_sheets import read_private_sheet
            from app.import_service import create_batch

            if not isinstance(access_token, str) or not access_token:
                raise GoogleAccountError("Google did not grant Sheets access.")
            batch = create_batch(
                current_user.id,
                read_private_sheet(flow["sheet"], access_token),
            )
            return redirect(url_for("imports.mapping", batch_id=batch.id))
        if flow["intent"] == "link":
            user = connect_google(current_user, claims)
            return finish_login(
                user,
                url_for("google_auth.account"),
                message="Google connected.",
            )
        user = google_user(
            claims, allow_signup=current_app.config["PUBLIC_SIGNUP_ENABLED"]
        )
        return finish_login(user, flow["next"])
    except GoogleAccountError as error:
        return sign_in_error(str(error))
    except ServiceError as error:
        flash(str(error), "danger")
        return redirect(url_for("imports.index"))
    except PROVIDER_ERRORS:
        # Provider descriptions can contain codes, tokens, or personal data.
        return sign_in_error(
            "Google sign-in was cancelled or could not be verified. "
            "Please try again."
        )


def sign_in_error(message, *, link=False):
    flash(message, "danger")
    destination = (
        "google_auth.account"
        if link and current_user.is_authenticated
        else "auth.login"
    )
    return redirect(url_for(destination))
