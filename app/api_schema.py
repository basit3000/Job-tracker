"""OpenAPI 3.1 schemas derived from the application's field contract."""

from app.contracts import (
    DEFAULT_FIELDS,
    FIELD_SPECS,
    OPTIONAL_FIELDS,
    RELATIONS,
)
from app.models import JOB_STATUSES


def field_schemas():
    result = {}
    for name, (_, kind, maximum) in FIELD_SPECS.items():
        if kind == "bool":
            schema = {"type": "boolean"}
        elif kind == "observation":
            schema = {
                "anyOf": [
                    {"$ref": "#/components/schemas/Applicants"},
                    {"type": "null"},
                ]
            }
        else:
            nullable = name not in {"title", "company", "status"}
            schema = {"type": ["string", "null"] if nullable else "string"}
            if maximum:
                schema["maxLength"] = maximum
            if kind in {"date", "timestamp", "email"}:
                schema["format"] = {
                    "date": "date",
                    "timestamp": "date-time",
                    "email": "email",
                }[kind]
            if kind == "date":
                schema["pattern"] = r"^\d{4}-\d{2}-\d{2}$"
            if kind == "status":
                schema["enum"] = JOB_STATUSES
            if name in {"title", "company"}:
                schema["minLength"] = 1
        result[name] = schema
    return result


def _object(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def _response_schemas(fields):
    nullable_time = {"type": ["string", "null"], "format": "date-time"}
    time = {"type": "string", "format": "date-time"}
    identifier = {"type": "string", "format": "uuid"}
    version = {"type": "integer", "minimum": 1}
    mappings = {"type": "array", "items": _ref("Mapping")}
    metadata = {
        "id": identifier,
        "version": version,
        "createdAt": time,
        "updatedAt": nullable_time,
        "deletedAt": {"type": "null"},
        "statusHistory": {"type": "array", "items": _ref("StatusEvent")},
        "mappings": mappings,
    }
    return {
        "Mapping": _object(
            {
                "installationId": {"type": "string"},
                "localRecordId": {"type": "string"},
            },
            ["installationId", "localRecordId"],
        ),
        "StatusEvent": _object(
            {
                "id": identifier,
                "status": {"enum": JOB_STATUSES},
                "fromStatus": {"enum": JOB_STATUSES + [None]},
                "source": {"enum": ["browser", "device", "import"]},
                "installationId": {"type": ["string", "null"]},
                "sourceEventId": {"type": ["string", "null"]},
                "occurredAt": nullable_time,
                "recordedAt": time,
            },
            [
                "id",
                "status",
                "fromStatus",
                "source",
                "installationId",
                "sourceEventId",
                "occurredAt",
                "recordedAt",
            ],
        ),
        "ActiveApplication": _object(
            {**fields, **metadata}, sorted(DEFAULT_FIELDS | set(metadata))
        ),
        "Tombstone": _object(
            {
                "id": identifier,
                "version": version,
                "deletedAt": time,
                "updatedAt": time,
                "mappings": mappings,
            },
            ["id", "version", "deletedAt", "updatedAt", "mappings"],
        ),
        "Application": {
            "oneOf": [_ref("ActiveApplication"), _ref("Tombstone")]
        },
        "MutationResult": _object(
            {
                "mutationId": {"type": "string"},
                "application": _ref("Application"),
            },
            ["mutationId", "application"],
        ),
        "FeedEntry": _object(
            {
                "sequence": {"type": "integer", "minimum": 1},
                "source": {"enum": ["browser", "device", "migration"]},
                "mutationId": {"type": ["string", "null"]},
                "application": _ref("Application"),
            },
            ["sequence", "source", "mutationId", "application"],
        ),
        "FeedPage": _object(
            {
                "entries": {"type": "array", "items": _ref("FeedEntry")},
                "cursor": {"type": "string"},
                "hasMore": {"type": "boolean"},
                "watermark": {"type": "integer", "minimum": 0},
                "changesCursor": {"type": "string"},
            },
            ["entries", "cursor", "hasMore", "watermark"],
        ),
        "PairingResult": _object(
            {
                "pairingId": identifier,
                "pairingSecret": {"type": "string"},
                "userCode": {"type": "string"},
                "expiresIn": {"const": 600},
                "approvalPath": {"const": "/integrations"},
            },
            [
                "pairingId",
                "pairingSecret",
                "userCode",
                "expiresIn",
                "approvalPath",
            ],
        ),
        "RedeemResult": _object(
            {
                "deviceId": identifier,
                "token": {"type": "string"},
                "optionalFields": _ref("OptionalFields"),
            },
            ["deviceId", "token", "optionalFields"],
        ),
        "OptionalFields": {
            "type": "array",
            "uniqueItems": True,
            "items": {"enum": sorted(OPTIONAL_FIELDS)},
        },
        "Device": _object(
            {
                "deviceId": identifier,
                "name": {"type": "string"},
                "installationId": {"type": "string"},
                "optionalFields": _ref("OptionalFields"),
            },
            ["deviceId", "name", "installationId", "optionalFields"],
        ),
        "Revocation": _object({"revoked": {"const": True}}, ["revoked"]),
    }


def openapi_document():
    fields = field_schemas()
    schemas = {
        "Fields": _object(fields),
        "Applicants": _object(
            {
                "count": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "maximum": 10**9,
                },
                "relation": {"enum": sorted(RELATIONS) + [None]},
                "label": {"type": ["string", "null"], "maxLength": 128},
                "source": {"type": ["string", "null"], "maxLength": 128},
                "url": {"type": ["string", "null"], "maxLength": 512},
                "observedAt": {
                    "type": ["string", "null"],
                    "format": "date-time",
                },
            }
        ),
        "SourceEvent": _object(
            {
                "sourceEventId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
                "status": {"enum": JOB_STATUSES},
                "fromStatus": {"enum": JOB_STATUSES + [None]},
                "occurredAt": {
                    "type": ["string", "null"],
                    "format": "date-time",
                },
            },
            ["sourceEventId", "status"],
        ),
        "Mutation": _object(
            {
                "mutationId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
                "operation": {"enum": ["create", "update", "delete", "map"]},
                "applicationId": {"type": "string", "maxLength": 36},
                "expectedVersion": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2**31 - 1,
                },
                "fields": {"$ref": "#/components/schemas/Fields"},
                "localRecordId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                },
                "statusHistory": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {"$ref": "#/components/schemas/SourceEvent"},
                },
            },
            ["mutationId", "operation"],
        ),
        "Pairing": _object(
            {
                "installationId": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
            },
            ["installationId", "name"],
        ),
        "Redeem": _object(
            {
                "pairingId": {"type": "string", "maxLength": 36},
                "pairingSecret": {"type": "string", "maxLength": 128},
            },
            ["pairingId", "pairingSecret"],
        ),
        "Error": {
            "type": "object",
            "required": ["error"],
            "additionalProperties": False,
            "properties": {
                "error": {
                    "type": "object",
                    "required": ["code", "message"],
                    "additionalProperties": False,
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "current": _ref("Application"),
                    },
                }
            },
        },
    }
    # Conditional operation shapes complement scalar validation. Stateful
    # Scope, existing versions, and history IDs are enforced by services.
    schemas["Mutation"]["oneOf"] = [
        {
            "properties": {"operation": {"const": "create"}},
            "required": ["fields"],
            "not": {
                "anyOf": [
                    {"required": ["applicationId"]},
                    {"required": ["expectedVersion"]},
                ]
            },
            "allOf": [
                {"properties": {"fields": {"required": ["title", "company"]}}}
            ],
        },
        {
            "properties": {"operation": {"const": "update"}},
            "required": ["applicationId", "expectedVersion"],
        },
        {
            "properties": {"operation": {"const": "delete"}},
            "required": ["applicationId", "expectedVersion"],
            "not": {
                "anyOf": [
                    {"required": ["fields"]},
                    {"required": ["statusHistory"]},
                    {"required": ["localRecordId"]},
                ]
            },
        },
        {
            "properties": {"operation": {"const": "map"}},
            "required": ["applicationId", "expectedVersion", "localRecordId"],
            "not": {
                "anyOf": [
                    {"required": ["fields"]},
                    {"required": ["statusHistory"]},
                ]
            },
        },
    ]
    schemas.update(_response_schemas(fields))
    response_schemas = {
        "/pairings": "PairingResult",
        "/pairings/redeem": "RedeemResult",
        "/mutations": "MutationResult",
        "/applications": "FeedPage",
        "/changes": "FeedPage",
        "/applications/{applicationId}": "Application",
        "/device": "Device",
        "/device/revoke": "Revocation",
    }
    paths = {}
    operations = {
        "/pairings": (
            "post",
            "Request a ten-minute browser-approved pairing",
            "Pairing",
            False,
        ),
        "/pairings/redeem": (
            "post",
            "Redeem one approved pairing exactly once",
            "Redeem",
            False,
        ),
        "/mutations": (
            "post",
            "Apply one idempotent version-aware mutation",
            "Mutation",
            True,
        ),
        "/applications": (
            "get",
            "Read a stable paginated snapshot, then its changesCursor",
            None,
            True,
        ),
        "/changes": (
            "get",
            "Read commit-ordered changes using a resumable cursor",
            None,
            True,
        ),
        "/applications/{applicationId}": (
            "get",
            "Read one owned application or tombstone",
            None,
            True,
        ),
        "/device": (
            "get",
            "Read this device's granted field scope",
            None,
            True,
        ),
        "/device/revoke": (
            "post",
            "Immediately revoke this device credential",
            None,
            True,
        ),
    }
    for path, (method, summary, schema, authenticated) in operations.items():
        operation = {
            "summary": summary,
            "security": [{"deviceBearer": []}] if authenticated else [],
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": _ref(response_schemas[path])
                        }
                    },
                },
                "default": {
                    "description": "Stable error response",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"}
                        }
                    },
                },
            },
        }
        if schema:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{schema}"}
                    }
                },
            }
        if path in {"/applications", "/changes"}:
            operation["parameters"] = [
                {
                    "name": "cursor",
                    "in": "query",
                    "schema": {"type": "string", "maxLength": 4096},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 50,
                    },
                },
            ]
        if "{applicationId}" in path:
            operation["parameters"] = [
                {
                    "name": "applicationId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                }
            ]
        paths[path] = {method: operation}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Job Scout Tracker API", "version": "1.0.0"},
        "servers": [{"url": "/api/v1"}],
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "deviceBearer": {"type": "http", "scheme": "bearer"}
            },
        },
    }
