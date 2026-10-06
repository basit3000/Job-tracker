"""Device-only JSON API; browser sessions never authorize these routes."""

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

from app.api_schema import openapi_document
from app.contracts import (
    ServiceError,
    identifier,
    project_application,
    serialize_application,
    strict_object,
)
from app.devices import (
    authenticate_device,
    record_exchange,
    record_failure,
    redeem_pairing,
    revoke_device,
    start_pairing,
)
from app.extensions import csrf, db, limiter
from app.models import JobApplication
from app.sync import feed_page, mutate

api = Blueprint("api", __name__, url_prefix="/api/v1")
csrf.exempt(api)
limiter.limit("120 per minute")(api)


@api.before_request
def authorize_api_request():
    request.max_content_length = current_app.config["API_MAX_CONTENT_LENGTH"]
    if request.endpoint == "api.openapi":
        return None
    local = current_app.config[
        "ALLOW_INSECURE_LOCAL_API"
    ] and request.remote_addr in {"127.0.0.1", "::1"}
    if not request.is_secure and not local:
        raise ServiceError(
            "https_required", "The device API requires HTTPS.", 400
        )
    if request.endpoint in {"api.pair", "api.redeem"}:
        return None
    g.device = authenticate_device(request.headers.get("Authorization", ""))
    if request.method == "GET":
        record_exchange(g.device)


@api.errorhandler(ServiceError)
def service_error(error):
    db.session.rollback()
    record_failure(getattr(g, "device", None), error.code)
    content = {"code": error.code, "message": str(error)}
    if error.details and getattr(g, "device", None):
        content["current"] = project_application(
            error.details, g.device.optional_fields, g.device.installation_id
        )
    return jsonify(error=content), error.status


@api.errorhandler(HTTPException)
def http_error(error):
    db.session.rollback()
    record_failure(getattr(g, "device", None), f"http_{error.code}")
    return jsonify(
        error={"code": f"http_{error.code}", "message": error.name}
    ), error.code


def json_body(allowed=None):
    if not request.is_json:
        raise ServiceError(
            "unsupported_media_type", "Use application/json.", 415
        )
    body = request.get_json()
    return strict_object(
        body,
        allowed
        if allowed is not None
        else set(body)
        if isinstance(body, dict)
        else (),
    )


@api.get("/openapi.json")
def openapi():
    return jsonify(openapi_document())


@api.post("/pairings")
@limiter.limit("5 per minute; 20 per hour")
def pair():
    body = json_body({"installationId", "name"})
    return jsonify(start_pairing(body.get("installationId"), body.get("name")))


@api.post("/pairings/redeem")
@limiter.limit("30 per minute")
def redeem():
    body = json_body({"pairingId", "pairingSecret"})
    return jsonify(
        redeem_pairing(body.get("pairingId"), body.get("pairingSecret"))
    )


@api.post("/mutations")
def mutation():
    return jsonify(mutate(json_body(), g.device))


def page(snapshot):
    token = request.args.get("cursor")
    if token is not None:
        identifier(token, "cursor", 4096)
    try:
        limit = int(
            request.args.get("limit", current_app.config["API_PAGE_SIZE"])
        )
    except ValueError as error:
        raise ServiceError(
            "validation_error", "limit must be an integer.", 422
        ) from error
    return jsonify(
        feed_page(g.device, token=token, snapshot=snapshot, limit=limit)
    )


@api.get("/applications")
def applications():
    return page(True)


@api.get("/changes")
def changes():
    return page(False)


@api.get("/applications/<application_id>")
def application(application_id):
    job = (
        JobApplication.for_user(g.device.user_id, include_deleted=True)
        .filter_by(public_id=application_id)
        .first()
    )
    if not job:
        raise ServiceError("not_found", "Application not found.", 404)
    return jsonify(
        project_application(
            serialize_application(job),
            g.device.optional_fields,
            g.device.installation_id,
        )
    )


@api.get("/device")
def device():
    return jsonify(
        deviceId=g.device.id,
        name=g.device.name,
        installationId=g.device.installation_id,
        optionalFields=g.device.optional_fields,
    )


@api.post("/device/revoke")
def disconnect():
    revoke_device(g.device.user_id, g.device.id)
    return jsonify(revoked=True)
