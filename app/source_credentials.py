"""Encrypt provider credentials with a separate private server key."""

import json

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from app.contracts import ServiceError


def credential_cipher():
    key = current_app.config.get("SYNC_ENCRYPTION_KEY")
    try:
        if not key:
            raise ValueError
        return Fernet(key)
    except (ValueError, TypeError) as error:
        raise ServiceError(
            "sync_not_configured",
            "Private source syncing needs the platform's encryption key. "
            "Use a one-time import until it is configured.",
            422,
        ) from error


def encrypt_credential(connection, token):
    if not isinstance(token, str) or not 1 <= len(token) <= 8192:
        raise ServiceError("reconnect_required", "Reconnect this source.", 422)
    payload = {
        "connection": connection.id,
        "user": connection.user_id,
        "token": token,
    }
    return credential_cipher().encrypt(json.dumps(payload).encode()).decode()


def decrypt_credential(connection):
    try:
        payload = json.loads(
            credential_cipher().decrypt(
                (connection.credential_ciphertext or "").encode()
            )
        )
        if (
            payload["connection"] != connection.id
            or payload["user"] != connection.user_id
        ):
            raise InvalidToken
        return payload["token"]
    except ServiceError:
        raise
    except (InvalidToken, ValueError, KeyError, TypeError) as error:
        raise ServiceError(
            "reconnect_required",
            "Reconnect this source to restore access.",
            422,
        ) from error
