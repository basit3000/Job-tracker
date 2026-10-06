"""Short-lived browser OAuth transactions; no persistent Google tokens."""

import secrets
import time
from urllib.parse import urlsplit

from authlib.common.errors import AuthlibBaseError
from flask import current_app, request, session
from flask_login import current_user
from joserfc.errors import JoseError
from requests import RequestException

from app.google_accounts import GoogleAccountError
from app.utils import is_safe_redirect

FLOW_KEY = "_google_flow"
FLOW_LIFETIME = 600
PROVIDER_ERRORS = (AuthlibBaseError, JoseError, RequestException)


def google_client():
    return current_app.extensions[
        "authlib.integrations.flask_client"
    ].create_client("google")


def clear_google_flow():
    session.pop(FLOW_KEY, None)
    for key in list(session):
        if key.startswith("_state_google_"):
            session.pop(key)


def require_google_transport():
    callback = urlsplit(current_app.config["GOOGLE_REDIRECT_URI"])
    local = (
        callback.scheme == "http"
        and callback.hostname in {"localhost", "127.0.0.1", "::1"}
        and urlsplit(request.url).hostname == callback.hostname
    )
    if not request.is_secure and not local:
        raise GoogleAccountError(
            "Use HTTPS for Google sign-in, or the configured loopback URL "
            "during local development."
        )


def start_google_flow(form):
    require_google_transport()
    link = form.intent.data == "link"
    sheets = form.intent.data == "sheets"
    if sheets and not current_user.is_authenticated:
        raise GoogleAccountError("Sign in before importing a private sheet.")
    sheet = None
    oauth_options = {}
    if sheets:
        from app.google_sheets import SHEETS_SCOPE, sheet_reference

        sheet = sheet_reference(form.sheet_url.data or "")
        if sheet["published"]:
            raise GoogleAccountError(
                "Use the normal share URL for private sheet access."
            )
        oauth_options = {
            "scope": "openid email " + SHEETS_SCOPE,
            "include_granted_scopes": "true",
        }
    if link and (
        not current_user.is_authenticated
        or not current_user.check_password(form.password.data or "")
    ):
        raise GoogleAccountError(
            "Sign in and enter your current password to connect Google."
        )
    clear_google_flow()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    response = google_client().authorize_redirect(
        current_app.config["GOOGLE_REDIRECT_URI"],
        state=state,
        nonce=nonce,
        prompt="select_account",
        **oauth_options,
    )
    session[FLOW_KEY] = {
        "state": state,
        "nonce": nonce,
        "started_at": time.time(),
        "intent": form.intent.data,
        "user_id": current_user.id if link or sheets else None,
        "sheet": sheet,
        "next": form.next.data if is_safe_redirect(form.next.data) else None,
    }
    return response


def finish_google_flow():
    require_google_transport()
    flow = session.get(FLOW_KEY)
    state = request.args.get("state", "")
    if (
        not flow
        or not state
        or not secrets.compare_digest(flow["state"].encode(), state.encode())
    ):
        raise GoogleAccountError(
            "Google sign-in could not be verified. "
            "Start again from the login page."
        )
    if not 0 <= time.time() - flow["started_at"] <= FLOW_LIFETIME:
        clear_google_flow()
        raise GoogleAccountError("Google sign-in expired. Please start again.")
    if flow["intent"] in {"link", "sheets"} and (
        not current_user.is_authenticated or current_user.id != flow["user_id"]
    ):
        clear_google_flow()
        raise GoogleAccountError(
            "Your signed-in account changed. Start the connection again."
        )
    try:
        token = google_client().authorize_access_token(
            leeway=30,
            claims_options={
                "iss": {
                    "values": [
                        "https://accounts.google.com",
                        "accounts.google.com",
                    ]
                }
            },
        )
        claims = token.get("userinfo")
        # Require an ID token and validated claims, never plain userinfo.
        # Require nonce even if a provider claims nonce_supported=false.
        nonce = claims.get("nonce") if isinstance(claims, dict) else None
        if (
            not token.get("id_token")
            or not isinstance(nonce, str)
            or not secrets.compare_digest(
                nonce.encode(), flow["nonce"].encode()
            )
        ):
            raise GoogleAccountError(
                "Google did not return a verified sign-in."
            )
        return flow, claims, token.get("access_token")
    finally:
        clear_google_flow()
