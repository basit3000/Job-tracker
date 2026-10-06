"""Google sign-in and explicit linking; all starts are CSRF-protected POSTs."""

from authlib.common.errors import AuthlibBaseError
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
from joserfc.errors import JoseError
from requests import RequestException

from app.extensions import limiter
from app.forms import GoogleLoginForm
from app.google_accounts import GoogleAccountError, connect_google, google_user
from app.google_login import (
    clear_google_flow,
    finish_google_flow,
    start_google_flow,
)
from app.routes.auth import finish_login
from app.security import AUTH_RATE_LIMIT

google_auth = Blueprint("google_auth", __name__)
PROVIDER_ERRORS = (AuthlibBaseError, JoseError, RequestException)


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
        flow, claims = finish_google_flow()
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
