"""Account creation and credential checks, independent of HTTP forms."""

from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import database_transaction
from app.extensions import db
from app.models import User

_DUMMY_PASSWORD_HASH = generate_password_hash("unused-password-for-timing")


class EmailAlreadyRegisteredError(ValueError):
    """An account already owns the requested email address."""

    def __init__(self):
        super().__init__("An account with that email already exists.")


def register_user(email, password):
    """Create an account, including handling concurrent duplicate requests."""
    if User.find_by_email(email):
        raise EmailAlreadyRegisteredError()

    user = User(email=email)
    user.set_password(password)
    try:
        with database_transaction():
            db.session.add(user)
    except IntegrityError as error:
        if User.find_by_email(email):
            raise EmailAlreadyRegisteredError() from error
        raise
    return user


def authenticate_user(email, password):
    """Check credentials without skipping password work for unknown users."""
    user = User.find_by_email(email)
    password_valid = (
        user.check_password(password)
        if user and user.password_hash
        else check_password_hash(_DUMMY_PASSWORD_HASH, password)
    )
    return user if user and user.password_hash and password_valid else None
