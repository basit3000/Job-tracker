from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app.extensions import db
from tests.helpers import MIGRATIONS


def test_fresh_schema_matches_models(app):
    with app.app_context(), db.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, db.metadata) == []


def test_upgrade_retains_existing_job_titles(app_factory):
    app = app_factory(migrate=False)
    with app.app_context():
        upgrade(directory=MIGRATIONS, revision="e328f9542d2c")
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user (id, email, password_hash) "
                    "VALUES (1, 'legacy@example.com', 'legacy-hash')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO job_application "
                    "(id, job_title, company, status, user_id) "
                    "VALUES (1, 'Keep this title', "
                    "'Legacy company', 'Applied', 1)"
                )
            )
        upgrade(directory=MIGRATIONS)
        with db.engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT job_title FROM job_application WHERE id=1")
                ).scalar_one()
                == "Keep this title"
            )
        downgrade(directory=MIGRATIONS, revision="e328f9542d2c")
        with db.engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT job_title FROM job_application WHERE id=1")
                ).scalar_one()
                == "Keep this title"
            )
