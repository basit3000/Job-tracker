from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from flask import template_rendered

from app.extensions import db
from app.models import JobApplication
from tests.helpers import csrf_token, job_data


def test_dashboard_totals_and_recent_applications_are_user_scoped(
    logged_client,
    app,
    users,
):
    with app.app_context():
        for day in range(1, 9):
            db.session.add(
                JobApplication(
                    job_title=f"Owner job {day}",
                    company="Owner company",
                    status="applied" if day % 2 else "rejected",
                    user_id=users[0],
                    applied_date=datetime(2026, 1, day, tzinfo=timezone.utc),
                    created_at=datetime(2026, 1, day, tzinfo=timezone.utc),
                )
            )
        db.session.add(
            JobApplication(
                job_title="Another user's job",
                company="Private company",
                status="offer",
                user_id=users[1],
            )
        )
        db.session.commit()

    contexts = []

    def capture_template(sender, template, context, **extra):
        contexts.append(context)

    with template_rendered.connected_to(capture_template, app):
        response = logged_client.get("/dashboard")
    assert response.status_code == 200
    context = contexts[0]
    assert context["total"] == 8
    assert context["active"] == 4
    assert context["counts"]["rejected"] == 4
    assert context["counts"]["offer"] == 0
    assert [job.job_title for job in context["recent"]] == [
        f"Owner job {day}" for day in range(8, 3, -1)
    ]
    assert b"Private company" not in response.data


@pytest.mark.parametrize(
    "field,size",
    [
        ("job_title", 129),
        ("company", 129),
        ("location", 129),
        ("salary", 65),
        ("contact_person", 129),
    ],
)
def test_job_text_limits_match_the_schema(logged_client, app, field, size):
    token = csrf_token(logged_client, "/jobs/add")
    response = logged_client.post(
        "/jobs/add",
        data=job_data(
            csrf_token=token,
            **{field: "x" * size},
        ),
    )
    assert response.status_code == 200
    assert b"invalid-feedback" in response.data
    with app.app_context():
        assert JobApplication.query.count() == 0


@pytest.mark.parametrize(
    "url",
    [
        "javascript://example.com/%0aalert(1)",
        "data://example.com/x",
        "ftp://example.com/file",
        "https://exam\nple.com",
        "https://example.com:99999",
        "https://example.com\\evil",
    ],
)
def test_unsafe_job_urls_are_rejected(logged_client, app, url):
    token = csrf_token(logged_client, "/jobs/add")
    response = logged_client.post(
        "/jobs/add", data=job_data(job_url=url, csrf_token=token)
    )
    assert response.status_code == 200
    with app.app_context():
        assert JobApplication.query.count() == 0


def test_legacy_unsafe_url_is_not_clickable(logged_client, app, job):
    with app.app_context():
        item = db.session.get(JobApplication, job)
        item.job_url = "javascript://example.com/%0aalert(1)"
        item.notes = "<script>alert(2)</script>"
        db.session.commit()
    response = logged_client.get(f"/jobs/{job}")
    assert response.status_code == 200
    assert b'href="javascript:' not in response.data
    assert b"&lt;script&gt;alert(2)&lt;/script&gt;" in response.data


@pytest.mark.parametrize(
    "suffix,method",
    [
        ("", "get"),
        ("/edit", "get"),
        ("/resume", "get"),
        ("/edit", "post"),
        ("/delete", "post"),
    ],
)
def test_other_user_cannot_access_or_mutate_job(
    client, app, users, job, suffix, method
):
    with client.session_transaction() as session:
        session["_user_id"] = str(users[1])
        session["_fresh"] = True
    data = (
        {"csrf_token": csrf_token(client, "/dashboard")}
        if method == "post"
        else None
    )
    response = getattr(client, method)(f"/jobs/{job}{suffix}", data=data)
    assert response.status_code == 404
    with app.app_context():
        assert (
            db.session.get(JobApplication, job).resume_filename
            == "existing.pdf"
        )
    assert Path(app.config["UPLOAD_FOLDER"], "existing.pdf").exists()


def test_job_mutations_require_csrf(logged_client, job, app):
    assert logged_client.post("/jobs/add", data=job_data()).status_code == 400
    assert (
        logged_client.post(f"/jobs/{job}/edit", data=job_data()).status_code
        == 400
    )
    assert logged_client.post(f"/jobs/{job}/delete").status_code == 400
    with app.app_context():
        assert JobApplication.query.count() == 1


def test_job_crud_resume_search_and_filters(logged_client, app, job):
    token = csrf_token(logged_client, "/jobs/add")
    response = logged_client.post(
        "/jobs/add",
        data=job_data(
            job_title="  Developer  ",
            company="  New Company  ",
            status="interviewing",
            job_url="https://example.com/jobs/1",
            csrf_token=token,
            resume=(BytesIO(b"new resume"), "../../resume.PDF"),
        ),
    )
    assert response.status_code == 302
    with app.app_context():
        item = JobApplication.query.filter_by(company="New Company").one()
        new_id, filename = item.id, item.resume_filename
        assert item.job_title == "Developer"
        assert len(filename) == 36 and filename.endswith(".pdf")
    response = logged_client.get(f"/jobs/{new_id}/resume")
    assert response.data == b"new resume"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert response.headers["Cache-Control"] == "no-store, private"
    results = logged_client.get(
        "/jobs?q=New&status=interviewing&sort=company"
    ).data
    assert b"New Company" in results
    assert b"<td>Example</td>" not in results
    assert logged_client.get("/jobs?sort=invalid").status_code == 200
    token = csrf_token(logged_client, f"/jobs/{new_id}/edit")
    response = logged_client.post(
        f"/jobs/{new_id}/edit",
        data=job_data(
            company="New Company",
            status="offer",
            csrf_token=token,
        ),
    )
    assert response.status_code == 302
    with app.app_context():
        assert (
            db.session.get(JobApplication, new_id).resume_filename == filename
        )
        assert db.session.get(JobApplication, new_id).status == "offer"
    token = csrf_token(logged_client, f"/jobs/{new_id}")
    assert (
        logged_client.post(
            f"/jobs/{new_id}/delete", data={"csrf_token": token, "version": 2}
        ).status_code
        == 302
    )
    assert not Path(app.config["UPLOAD_FOLDER"], filename).exists()


@pytest.mark.parametrize("version", ["", "0", "-1", "1.5", "١", "2147483648"])
@pytest.mark.parametrize("action", ["edit", "delete"])
def test_invalid_browser_version_does_not_change_application(
    logged_client, app, job, version, action
):
    token = csrf_token(logged_client, f"/jobs/{job}/edit")
    response = logged_client.post(
        f"/jobs/{job}/{action}",
        data=job_data(csrf_token=token, version=version),
    )
    # WTForms can reject malformed text before contract validation runs.
    assert response.status_code in {200, 422}
    with app.app_context():
        record = db.session.get(JobApplication, job)
        assert record.company == "Example"
        assert record.version == 1 and record.deleted_at is None
    assert Path(app.config["UPLOAD_FOLDER"], "existing.pdf").exists()
