"""Verified Google identities with explicit linking to password accounts."""

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.exc import IntegrityError

from app.contracts import ServiceError
from app.database import database_transaction
from app.extensions import db
from app.models import User
from app.record_updates import lock_account


class GoogleAccountError(ServiceError):
    def __init__(self, message):
        super().__init__("google_account_error", message, 400)


def verified_identity(claims):
    """Called only after Authlib has validated the signed OpenID ID token."""
    if (
        not isinstance(claims, dict)
        or claims.get("email_verified") is not True
    ):
        raise GoogleAccountError(
            "Google must verify your email address first."
        )
    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not 1 <= len(subject) <= 255
        or any(not 33 <= ord(char) <= 126 for char in subject)
    ):
        raise GoogleAccountError(
            "Google did not return a valid account identity."
        )
    email = claims.get("email")
    try:
        email = validate_email(
            email, check_deliverability=False
        ).normalized.lower()
    except (EmailNotValidError, TypeError, AttributeError) as error:
        raise GoogleAccountError(
            "Google did not return a valid email address."
        ) from error
    if len(email) > User.email.type.length:
        raise GoogleAccountError(
            "This email address exceeds the account limit."
        )
    return subject, email


def _link_required():
    raise GoogleAccountError(
        "An account with this email already exists. Sign in with its current "
        "method, then connect Google from Account settings."
    )


def google_user(claims, *, allow_signup):
    subject, email = verified_identity(claims)
    user = User.query.filter_by(google_subject=subject).first()
    if user:
        # Email can change at Google; never change the linked identity or merge
        # it with a different local account merely because an email matches.
        return user
    if not allow_signup:
        raise GoogleAccountError(
            "New account registration is currently closed."
        )
    if User.find_by_email(email):
        _link_required()
    user = User(email=email, google_subject=subject)
    try:
        with database_transaction():
            db.session.add(user)
    except IntegrityError:
        existing = User.query.filter_by(google_subject=subject).first()
        if existing:
            return existing
        if User.find_by_email(email):
            _link_required()
        raise
    return user


def connect_google(user, claims):
    subject, email = verified_identity(claims)
    try:
        with database_transaction():
            lock_account(user.id)
            db.session.refresh(user)
            if user.email != email:
                raise GoogleAccountError(
                    "Choose the Google account with the same email as your "
                    "tracker account."
                )
            if user.google_subject and user.google_subject != subject:
                raise GoogleAccountError(
                    "A different Google identity is already connected."
                )
            user.google_subject = subject
    except IntegrityError as error:
        raise GoogleAccountError(
            "This Google identity is already connected to another account."
        ) from error
    return user
