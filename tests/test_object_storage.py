"""Private remote resumes retain owner checks and transactional cleanup."""

import io
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import boto3
import pytest
from botocore.config import Config
from botocore.stub import ANY, Stubber
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import FileStorage

from app.contracts import ServiceError
from app.extensions import db
from app.models import JobApplication
from app.uploads import delete_resume, save_resume
from tests.helpers import csrf_token, job_data

NAME = "0" * 32 + ".pdf"
OBJECT = {"Bucket": "private-test-resumes", "Key": f"resumes/{NAME}"}


@pytest.fixture
def remote(app, monkeypatch):
    app.config.update(UPLOAD_STORAGE="s3", S3_BUCKET=OBJECT["Bucket"])
    client = boto3.session.Session().client(
        "s3",
        endpoint_url="https://storage.example.com",
        region_name="us-east-1",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        config=Config(signature_version="s3v4"),
    )
    app.extensions["resume_s3"] = client
    monkeypatch.setattr("app.uploads.uuid4", lambda: UUID(int=0))
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def resume():
    return FileStorage(
        stream=io.BytesIO(b"private resume"), filename="my-cv.pdf"
    )


def test_resume_write_is_opaque_private_and_never_writes_to_disk(app, remote):
    _, stub = remote
    stub.add_response(
        "put_object",
        {},
        {
            **OBJECT,
            "Body": ANY,
            "ContentType": "application/octet-stream",
            "ContentDisposition": "attachment",
        },
    )
    with app.app_context():
        assert save_resume(resume()) == NAME
    assert not Path(app.config["UPLOAD_FOLDER"], NAME).exists()


def test_uncertain_write_is_cleaned_up_and_error_is_safe(app, remote):
    _, stub = remote
    stub.add_client_error(
        "put_object",
        "AccessDenied",
        "private credential detail",
        expected_params={
            **OBJECT,
            "Body": ANY,
            "ContentType": "application/octet-stream",
            "ContentDisposition": "attachment",
        },
    )
    stub.add_response("delete_object", {}, OBJECT)
    with app.app_context(), pytest.raises(ServiceError) as error:
        save_resume(resume())
    assert error.value.status == 503
    assert "private" not in str(error.value)


@pytest.mark.parametrize("failure", [False, True])
def test_replacement_retires_only_the_correct_remote_object(
    app,
    remote,
    logged_client,
    job,
    monkeypatch,
    failure,
):
    _, stub = remote
    token = csrf_token(logged_client, f"/jobs/{job}/edit")
    stub.add_response(
        "put_object",
        {},
        {
            **OBJECT,
            "Body": ANY,
            "ContentType": "application/octet-stream",
            "ContentDisposition": "attachment",
        },
    )
    retired = NAME if failure else "existing.pdf"
    stub.add_response(
        "delete_object",
        {},
        {
            "Bucket": OBJECT["Bucket"],
            "Key": f"resumes/{retired}",
        },
    )
    if failure:
        monkeypatch.setattr(
            db.session,
            "commit",
            Mock(side_effect=SQLAlchemyError("failed")),
        )
    response = logged_client.post(
        f"/jobs/{job}/edit",
        data=job_data(
            csrf_token=token,
            resume=(io.BytesIO(b"replacement"), "resume.pdf"),
        ),
    )
    assert response.status_code == (500 if failure else 302)
    with app.app_context():
        assert db.session.get(JobApplication, job).resume_filename == (
            "existing.pdf" if failure else NAME
        )


def test_object_delete_rejects_path_and_header_injection(app, remote):
    _, stub = remote
    stub.add_response("delete_object", {}, OBJECT)
    with app.app_context():
        for name in (
            "../private.pdf",
            "resumes/private.pdf",
            'a".pdf',
            "a\r\n.pdf",
        ):
            delete_resume(name)
        delete_resume(NAME)


def test_download_requires_owner_before_signing_url(
    app,
    remote,
    logged_client,
    client,
    users,
    job,
    monkeypatch,
):
    s3, stub = remote
    # Existing opaque database names continue to work without a schema change.
    stored = {"Bucket": OBJECT["Bucket"], "Key": "resumes/existing.pdf"}
    stub.add_response("head_object", {"ContentLength": 10}, stored)
    signer = Mock(wraps=s3.generate_presigned_url)
    monkeypatch.setattr(s3, "generate_presigned_url", signer)
    response = logged_client.get(f"/jobs/{job}/resume")
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.location).query)
    assert query["X-Amz-Expires"] == ["60"]
    assert "attachment" in query["response-content-disposition"][0]
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response.headers["Cache-Control"]
    signer.reset_mock()
    with client.session_transaction() as session:
        session["_user_id"] = str(users[1])
        session["_fresh"] = True
    assert client.get(f"/jobs/{job}/resume").status_code == 404
    signer.assert_not_called()
    with client.session_transaction() as session:
        session.clear()
    assert client.get(f"/jobs/{job}/resume").status_code == 302
    signer.assert_not_called()


@pytest.mark.parametrize("code,status", [("404", 404), ("AccessDenied", 503)])
def test_remote_download_failures_hide_provider_details(
    remote,
    logged_client,
    job,
    code,
    status,
):
    _, stub = remote
    stub.add_client_error(
        "head_object",
        code,
        "private storage details",
        expected_params={
            "Bucket": OBJECT["Bucket"],
            "Key": "resumes/existing.pdf",
        },
    )
    response = logged_client.get(f"/jobs/{job}/resume")
    assert response.status_code == status
    assert b"private storage details" not in response.data
