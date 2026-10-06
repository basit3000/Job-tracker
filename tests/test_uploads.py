from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import JobApplication
from app.uploads import delete_resume, resume_path
from tests.helpers import csrf_token, job_data


def test_upload_help_and_validation_follow_configured_policy(
    logged_client,
    app,
):
    app.config.update(
        ALLOWED_UPLOAD_EXTENSIONS={"pdf"},
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    response = logged_client.get("/jobs/add")
    assert b"PDF (max 2 MB)." in response.data
    token = csrf_token(logged_client, "/jobs/add")
    response = logged_client.post(
        "/jobs/add",
        data=job_data(
            csrf_token=token,
            resume=(BytesIO(b"a resume"), "resume.txt"),
        ),
    )
    assert response.status_code == 200
    assert b"Documents only (pdf)." in response.data
    with app.app_context():
        assert JobApplication.query.count() == 0


@pytest.mark.parametrize("operation", ["add", "edit", "delete"])
def test_failed_commit_preserves_old_resume_and_removes_new_file(
    logged_client,
    app,
    job,
    monkeypatch,
    operation,
):
    path = "/jobs/add" if operation == "add" else f"/jobs/{job}/{operation}"
    token_path = f"/jobs/{job}" if operation == "delete" else path
    token = csrf_token(logged_client, token_path)

    def fail_commit():
        raise SQLAlchemyError("simulated failed transaction")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    data = (
        {"csrf_token": token}
        if operation == "delete"
        else job_data(
            csrf_token=token,
            resume=(BytesIO(b"replacement"), "resume.pdf"),
        )
    )
    assert logged_client.post(path, data=data).status_code == 500
    folder = Path(app.config["UPLOAD_FOLDER"])
    assert sorted(path.name for path in folder.iterdir()) == ["existing.pdf"]
    assert (folder / "existing.pdf").read_bytes() == b"original resume"
    with app.app_context():
        assert JobApplication.query.count() == 1
        assert (
            db.session.get(JobApplication, job).resume_filename
            == "existing.pdf"
        )


def test_replacing_resume_removes_old_file_after_success(
    logged_client, app, job
):
    token = csrf_token(logged_client, f"/jobs/{job}/edit")
    response = logged_client.post(
        f"/jobs/{job}/edit",
        data=job_data(
            csrf_token=token,
            resume=(BytesIO(b"replacement"), "resume.pdf"),
        ),
    )
    assert response.status_code == 302
    assert not Path(app.config["UPLOAD_FOLDER"], "existing.pdf").exists()
    assert logged_client.get(f"/jobs/{job}/resume").data == b"replacement"


def test_partial_upload_failure_keeps_old_resume(
    logged_client,
    app,
    job,
    monkeypatch,
):
    token = csrf_token(logged_client, f"/jobs/{job}/edit")

    def partial_save(storage, destination, buffer_size=16384):
        destination.write(b"partial upload")
        raise OSError("simulated disk error")

    monkeypatch.setattr(FileStorage, "save", partial_save)
    response = logged_client.post(
        f"/jobs/{job}/edit",
        data=job_data(
            csrf_token=token,
            resume=(BytesIO(b"replacement"), "resume.pdf"),
        ),
    )
    assert response.status_code == 500
    folder = Path(app.config["UPLOAD_FOLDER"])
    assert sorted(path.name for path in folder.iterdir()) == ["existing.pdf"]
    with app.app_context():
        assert (
            db.session.get(JobApplication, job).resume_filename
            == "existing.pdf"
        )


@pytest.mark.parametrize("filename", ["../outside.txt", "..\\outside.txt"])
def test_stored_resume_paths_cannot_escape_uploads(
    logged_client, app, job, filename
):
    outside = Path(app.config["UPLOAD_FOLDER"]).parent / "outside.txt"
    outside.write_text("keep me")
    with app.app_context():
        item = db.session.get(JobApplication, job)
        item.resume_filename = filename
        db.session.commit()
        assert resume_path(filename) is None
        delete_resume(filename)
    assert outside.read_text() == "keep me"
    assert logged_client.get(f"/jobs/{job}/resume").status_code == 404


def test_disallowed_and_oversized_uploads(logged_client, app):
    token = csrf_token(logged_client, "/jobs/add")
    response = logged_client.post(
        "/jobs/add",
        data=job_data(
            csrf_token=token,
            resume=(BytesIO(b"<html>bad</html>"), "resume.html"),
        ),
    )
    assert response.status_code == 200
    app.config["MAX_CONTENT_LENGTH"] = 2048
    response = logged_client.post(
        "/jobs/add",
        data=job_data(
            csrf_token=token,
            resume=(BytesIO(b"a" * 4096), "resume.pdf"),
        ),
    )
    assert response.status_code == 413
    assert list(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == []
