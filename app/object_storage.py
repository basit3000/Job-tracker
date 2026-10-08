"""Private resume objects with short-lived authorized downloads."""

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from flask import abort, current_app, redirect

from app.contracts import ServiceError

STORAGE_ERRORS = (BotoCoreError, ClientError)


def _client():
    app = current_app._get_current_object()
    if "resume_s3" not in app.extensions:
        config = app.config
        app.extensions["resume_s3"] = boto3.session.Session().client(
            "s3",
            endpoint_url=config["S3_ENDPOINT_URL"],
            region_name=config["S3_REGION"],
            aws_access_key_id=config["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=config["S3_SECRET_ACCESS_KEY"],
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=15,
                retries={"max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": config["S3_ADDRESSING_STYLE"]},
            ),
        )
    return app.extensions["resume_s3"]


def _object(filename):
    return {
        "Bucket": current_app.config["S3_BUCKET"],
        "Key": f"resumes/{filename}",
    }


def save_object(filename, stream):
    try:
        _client().put_object(
            **_object(filename),
            Body=stream,
            ContentType="application/octet-stream",
            ContentDisposition="attachment",
        )
    except STORAGE_ERRORS:
        # A failed response can follow a successful write.
        delete_object(filename)
        raise ServiceError(
            "storage_unavailable",
            "Resume storage is unavailable. Try again.",
            503,
        ) from None


def delete_object(filename):
    try:
        _client().delete_object(**_object(filename))
    except STORAGE_ERRORS:
        current_app.logger.warning("Could not remove a retired resume object.")


def download_object(filename):
    """Called only after the route has authorized the record owner."""
    try:
        client = _client()
        client.head_object(**_object(filename))
        url = client.generate_presigned_url(
            "get_object",
            Params={
                **_object(filename),
                "ResponseContentType": "application/octet-stream",
                "ResponseContentDisposition": (
                    f'attachment; filename="{filename}"'
                ),
            },
            ExpiresIn=60,
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            abort(404)
        raise ServiceError(
            "storage_unavailable",
            "Resume storage is unavailable. Try again.",
            503,
        ) from None
    except BotoCoreError:
        raise ServiceError(
            "storage_unavailable",
            "Resume storage is unavailable. Try again.",
            503,
        ) from None
    return redirect(url)
