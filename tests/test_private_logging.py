"""Private URLs and model fields must not enter ordinary diagnostics."""

import logging

import pytest

from app.models import JobApplication, User
from app.security import PrivateRequestLogFilter


@pytest.mark.parametrize(
    "message,args",
    [
        (
            '"%s" 200',
            ("GET /jobs?q=private-contact&company=private-company HTTP/1.1",),
        ),
        (
            '"GET /notifications/unsubscribe/private-token HTTP/1.1" 200',
            (),
        ),
        (
            "%(r)s %(q)s %(U)s %(f)s",
            {
                "r": "POST /notifications/unsubscribe/private-token HTTP/1.1",
                "q": "code=private-code",
                "U": "/notifications/unsubscribe/private-token",
                "f": "https://tracker.example.com/jobs?q=private-contact",
            },
        ),
    ],
)
def test_request_log_redacts_sensitive_urls(message, args):
    record = logging.LogRecord(
        "werkzeug", logging.INFO, "", 0, message, (), None
    )
    record.args = args
    assert PrivateRequestLogFilter().filter(record)
    rendered = record.getMessage()
    for value in (
        "private-token",
        "private-contact",
        "private-company",
        "private-code",
    ):
        assert value not in rendered
    assert "HTTP/1.1" in rendered


def test_factory_installs_access_log_redaction_once(
    app_factory, caplog, monkeypatch
):
    app_factory(migrate=False)
    app_factory(migrate=False)
    for name in ("werkzeug", "gunicorn.access"):
        logger = logging.getLogger(name)
        # Alembic replaces root handlers while building migrated test apps.
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        assert (
            sum(
                isinstance(item, PrivateRequestLogFilter)
                for item in logger.filters
            )
            == 1
        )
        with caplog.at_level(logging.INFO, logger=name):
            logger.info(
                '"GET /notifications/unsubscribe/private-token HTTP/1.1"'
            )
    assert "private-token" not in caplog.text
    assert "/notifications/unsubscribe/[redacted]" in caplog.text


def test_model_diagnostics_exclude_personal_and_application_data():
    user = User(id=7, email="private-person@example.com")
    job = JobApplication(
        id=9, job_title="Private role", company="Private company"
    )
    assert "private-person" not in repr(user)
    assert "Private role" not in repr(job)
    assert "Private company" not in repr(job)


def test_resume_cleanup_does_not_log_private_paths(app, caplog, monkeypatch):
    from pathlib import Path

    from app.uploads import delete_resume

    def inaccessible_file(*args, **kwargs):
        raise OSError("private-resume-path and private-filename")

    monkeypatch.setattr(Path, "unlink", inaccessible_file)
    monkeypatch.setattr(app.logger, "handlers", [caplog.handler])
    with app.app_context(), caplog.at_level(logging.WARNING):
        delete_resume("private-filename.pdf")
    assert "Could not remove a retired resume file" in caplog.text
    assert "private-resume-path" not in caplog.text
    assert "private-filename" not in caplog.text
