"""Account-approved, single-use pairing and revocable device credentials."""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.exc import SQLAlchemyError

from app.contracts import OPTIONAL_FIELDS, ServiceError, identifier, utc
from app.database import database_transaction
from app.extensions import db
from app.models import Device, PairingRequest, _utcnow
from app.record_updates import lock_account


def credential_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def start_pairing(installation_id, name):
    installation_id = identifier(installation_id, "installationId")
    name = identifier(name, "name", 80)
    secret = secrets.token_urlsafe(32)
    code = secrets.token_hex(6).upper()
    pairing = PairingRequest(
        installation_id=installation_id,
        name=name,
        secret_hash=credential_hash(secret),
        code_hash=credential_hash(code),
        expires_at=_utcnow() + timedelta(minutes=10),
    )
    with database_transaction():
        # Expired pairing intents contain no records and are no longer usable.
        PairingRequest.query.filter(
            PairingRequest.expires_at < _utcnow()
        ).delete()
        db.session.add(pairing)
    return {
        "pairingId": pairing.id,
        "pairingSecret": secret,
        "userCode": code,
        "expiresIn": 600,
        "approvalPath": "/integrations",
    }


def usable_pairing(pairing):
    if (
        not pairing
        or pairing.consumed_at
        or utc(pairing.expires_at) <= _utcnow()
    ):
        raise ServiceError(
            "pairing_expired",
            "Pairing is invalid, expired, or already used.",
            410,
        )


def approve_pairing(user_id, code, optional_fields):
    if set(optional_fields) - OPTIONAL_FIELDS:
        raise ServiceError(
            "validation_error", "Unknown optional field selection.", 422
        )
    code = identifier(code, "userCode", 32).replace("-", "").upper()
    with database_transaction():
        lock_account(user_id)
        pairing = (
            PairingRequest.query.filter_by(code_hash=credential_hash(code))
            .populate_existing()
            .with_for_update()
            .first()
        )
        usable_pairing(pairing)
        if pairing.user_id is not None:
            raise ServiceError(
                "pairing_used", "This pairing has already been approved.", 409
            )
        pairing.user_id = user_id
        pairing.optional_fields = sorted(set(optional_fields))
    return pairing


def redeem_pairing(pairing_id, secret):
    identifier(pairing_id, "pairingId", 36)
    identifier(secret, "pairingSecret", 128)
    pairing = db.session.get(PairingRequest, pairing_id)
    usable_pairing(pairing)
    if not secrets.compare_digest(
        pairing.secret_hash, credential_hash(secret)
    ):
        raise ServiceError(
            "unauthorized", "Pairing credential is invalid.", 401
        )
    if pairing.user_id is None:
        raise ServiceError(
            "approval_pending",
            "Approve the code in the signed-in integration page.",
            409,
        )
    token = "jst_" + secrets.token_urlsafe(32)
    with database_transaction():
        lock_account(pairing.user_id)
        pairing = (
            PairingRequest.query.filter_by(id=pairing_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        usable_pairing(pairing)
        pairing.consumed_at = _utcnow()
        device = Device(
            user_id=pairing.user_id,
            installation_id=pairing.installation_id,
            name=pairing.name,
            token_hash=credential_hash(token),
            optional_fields=pairing.optional_fields,
        )
        db.session.add(device)
        db.session.flush()
        device_id = device.id
    return {
        "deviceId": device_id,
        "token": token,
        "optionalFields": device.optional_fields,
    }


def authenticate_device(header):
    parts = header.split()
    if (
        len(parts) != 2
        or parts[0] != "Bearer"
        or not 40 <= len(parts[1]) <= 128
    ):
        raise ServiceError(
            "unauthorized",
            "A valid device bearer credential is required.",
            401,
        )
    device = Device.query.filter_by(
        token_hash=credential_hash(parts[1]), revoked_at=None
    ).first()
    if not device:
        raise ServiceError(
            "unauthorized", "Device credential is invalid or revoked.", 401
        )
    return device


def require_active_device(device):
    db.session.refresh(device)
    if device.revoked_at:
        raise ServiceError(
            "unauthorized", "Device credential has been revoked.", 401
        )
    device.last_seen_at = _utcnow()
    device.last_error_code = None
    device.last_error_at = None


def record_exchange(device):
    with database_transaction():
        lock_account(device.user_id)
        require_active_device(device)


def record_failure(device, code):
    """Store only an error code; no request or private error payload."""
    if device is None:
        return
    try:
        with database_transaction():
            lock_account(device.user_id)
            db.session.refresh(device)
            if not device.revoked_at:
                device.last_error_code = code[:40]
                device.last_error_at = _utcnow()
    except SQLAlchemyError:
        db.session.rollback()


def revoke_device(user_id, device_id):
    with database_transaction():
        lock_account(user_id)
        device = Device.query.filter_by(id=device_id, user_id=user_id).first()
        if not device:
            raise ServiceError("not_found", "Device not found.", 404)
        device.revoked_at = device.revoked_at or _utcnow()
