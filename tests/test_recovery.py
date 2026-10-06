from pathlib import Path

import pytest

from app.contracts import ServiceError
from app.extensions import db
from app.models import Device, JobApplication
from app.sync import feed_page
from ops.backup_sqlite import backup_database
from tests.helpers import create_record, pair_device


def test_sqlite_backup_restores_identity_history_and_resets_future_cursors(
    app, app_factory, users, client, tmp_path
):
    headers, device_id = pair_device(client, app, users[0])
    record, _ = create_record(client, headers)
    with app.app_context():
        source = Path(db.engine.url.database)
        backup = tmp_path / "backups" / "verified.db"
        backup_database(source, backup)
    later, _ = create_record(client, headers, title="After backup")
    with app.app_context():
        cursor = feed_page(db.session.get(Device, device_id))["cursor"]
    restored = app_factory(
        migrate=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + backup.as_posix()
    )
    with restored.app_context():
        job = JobApplication.query.one()
        assert job.public_id == record["id"] and job.public_id != later["id"]
        assert job.version == 1 and len(job.history) == 1
        assert (
            feed_page(db.session.get(Device, device_id))["entries"][0][
                "application"
            ]["id"]
            == record["id"]
        )
        with pytest.raises(ServiceError) as error:
            feed_page(db.session.get(Device, device_id), token=cursor)
        assert error.value.code == "cursor_reset_required"


def test_sqlite_backup_never_overwrites_existing_files(app, tmp_path):
    with app.app_context():
        source = Path(db.engine.url.database)
        destination = tmp_path / "keep.db"
        destination.write_bytes(b"Keep this fictional file")
        with pytest.raises(FileExistsError):
            backup_database(source, destination)
        assert destination.read_bytes() == b"Keep this fictional file"
        with pytest.raises(ValueError):
            backup_database(source, source)
