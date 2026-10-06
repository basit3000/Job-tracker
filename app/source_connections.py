"""Account-scoped source access, credentials and reusable mapping previews."""

import json
from datetime import timedelta

import requests
from flask import current_app

from app.contracts import ServiceError, utc
from app.database import database_transaction
from app.extensions import db
from app.google_sheets import (
    bounded_response,
    read_private_sheet,
    read_public_sheet,
)
from app.import_mapping import layout
from app.import_readers import import_error
from app.import_service import new_batch_locked
from app.models import (
    ImportBatch,
    SourceConnection,
    SourceRecord,
    _utcnow,
    public_id,
)
from app.notion_sources import checked_token, read_notion
from app.record_updates import lock_account
from app.source_credentials import (
    credential_cipher,
    decrypt_credential,
    encrypt_credential,
)

PROVIDERS = {"google_public", "google_private", "notion"}
INTERVALS = {0, 15, 60}


def get_connection(user_id, connection_id):
    connection = (
        SourceConnection.query.filter_by(user_id=user_id, id=connection_id)
        .populate_existing()
        .first()
    )
    if not connection:
        raise ServiceError("not_found", "Connected source not found.", 404)
    return connection


def create_connection(
    user_id, name, provider, reference, *, token=None, interval=0
):
    name = name.strip()
    if (
        not name
        or len(name) > 80
        or provider not in PROVIDERS
        or interval not in INTERVALS
    ):
        import_error(
            "Choose a source name, supported provider and sync interval."
        )
    if provider != "google_public":
        credential_cipher()
    connection = SourceConnection(
        id=public_id(),
        user_id=user_id,
        name=name,
        provider=provider,
        reference=reference,
        interval_minutes=interval,
    )
    if provider == "notion":
        connection.credential_ciphertext = encrypt_credential(
            connection, checked_token(token)
        )
    with database_transaction():
        lock_account(user_id)
        if SourceConnection.query.filter_by(user_id=user_id).count() >= 20:
            import_error("Connect at most 20 sources per account.")
        db.session.add(connection)
    return connection


def next_sync(connection):
    return (
        _utcnow() + timedelta(minutes=connection.interval_minutes)
        if connection.interval_minutes
        else None
    )


def remove_connection(user_id, connection_id):
    with database_transaction():
        lock_account(user_id)
        connection = get_connection(user_id, connection_id)
        ImportBatch.query.filter_by(
            user_id=user_id, connection_id=connection_id
        ).delete(synchronize_session=False)
        SourceRecord.query.filter_by(
            user_id=user_id, connection_id=connection_id
        ).delete(synchronize_session=False)
        db.session.delete(connection)


def set_schedule(user_id, connection_id, interval):
    if type(interval) is not int or interval not in INTERVALS:
        import_error("Choose manual syncing, every 15 minutes, or hourly.")
    with database_transaction():
        lock_account(user_id)
        connection = get_connection(user_id, connection_id)
        connection.interval_minutes = interval
        connection.next_sync_at = (
            next_sync(connection) if connection.active else None
        )
        connection.version += 1


def google_access_token(connection):
    try:
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": decrypt_credential(connection),
                "client_id": current_app.config["GOOGLE_CLIENT_ID"],
                "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            },
            timeout=10,
            stream=True,
            allow_redirects=False,
        )
        token = json.loads(bounded_response(response))
        if (
            not isinstance(token.get("access_token"), str)
            or not token["access_token"]
        ):
            raise ValueError
        return token["access_token"]
    except (requests.RequestException, ValueError, AttributeError) as error:
        raise ServiceError(
            "reconnect_required",
            "Reconnect Google Sheets to restore access.",
            422,
        ) from error


def fetch_tables(connection):
    reference = connection.reference
    selection = reference.get("range")
    if connection.provider == "google_public":
        return read_public_sheet(reference, selection)
    if connection.provider == "google_private":
        return read_private_sheet(
            reference, google_access_token(connection), selection
        )
    return read_notion(reference, decrypt_credential(connection))


def check_columns(connection, tables):
    options = connection.options
    labels, _ = layout(tables[0], options["header"])
    if labels != connection.columns:
        raise ServiceError(
            "source_layout_changed",
            "Source columns changed. Review the mapping before syncing again.",
            409,
        )


def connection_batch(connection, *, remap=False, tables=None):
    version = connection.version
    tables = fetch_tables(connection) if tables is None else tables
    if connection.options and not remap:
        if len(tables) != 1:
            import_error("Choose one source tab for this connection.")
        check_columns(connection, tables)
    # The network read happens before acquiring the account write lock.
    with database_transaction():
        lock_account(connection.user_id)
        connection = get_connection(connection.user_id, connection.id)
        if connection.version != version:
            raise ServiceError(
                "source_changed", "Source changed. Read it again.", 409
            )
        batch = new_batch_locked(
            connection.user_id, tables, connection=connection
        )
        if connection.options and not remap:
            batch.options = dict(connection.options)
    return batch


def complete_google_connection(
    user_id, connection_id, expected_version, token
):
    refresh_token = token.get("refresh_token")
    with database_transaction():
        lock_account(user_id)
        connection = get_connection(user_id, connection_id)
        if (
            connection.provider != "google_private"
            or connection.version != expected_version
        ):
            raise ServiceError(
                "source_changed", "Source changed. Reconnect it.", 409
            )
        if not refresh_token:
            import_error(
                "Google did not grant offline access. "
                "Reconnect and approve access."
            )
        connection.credential_ciphertext = encrypt_credential(
            connection, refresh_token
        )
        connection.version += 1
    return connection_batch(connection, remap=not connection.options)


def record_sync_error(user_id, connection_id, version, message):
    with database_transaction():
        lock_account(user_id)
        connection = SourceConnection.query.filter_by(
            id=connection_id, user_id=user_id
        ).first()
        if connection and connection.version == version:
            connection.last_error = message[:256]
            connection.next_sync_at = next_sync(connection)


def claim_due(user_id, connection_id):
    with database_transaction():
        lock_account(user_id)
        connection = get_connection(user_id, connection_id)
        if (
            not connection.active
            or not connection.interval_minutes
            or not connection.next_sync_at
            or utc(connection.next_sync_at) > _utcnow()
        ):
            return None
        connection.next_sync_at = next_sync(connection)
    return connection
