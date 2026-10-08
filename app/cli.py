"""Explicit account bootstrap and opt-in fictional seed commands."""

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import text

from app.authentication import EmailAlreadyRegisteredError, register_user
from app.extensions import db
from app.forms import RegistrationForm
from app.models import JobApplication
from app.services import save_application


@click.command("create-user")
@click.option("--email", prompt=True)
@click.password_option(confirmation_prompt=True)
@with_appcontext
def create_user(email, password):
    """Create an account administratively, independent of public signup."""
    # The CLI shares form validation without requiring a browser CSRF token.
    form = RegistrationForm(
        data={"email": email, "password": password, "confirm": password},
        meta={"csrf": False},
    )
    if not form.validate():
        raise click.ClickException(
            "Invalid email or password (8-1024 characters required)."
        )
    try:
        register_user(form.email.data, password)
    except EmailAlreadyRegisteredError as error:
        raise click.ClickException(str(error)) from error
    click.echo("Account created.")


@click.command("seed-demo")
@click.option("--confirm-fictional", is_flag=True, required=True)
@with_appcontext
def seed_demo(confirm_fictional):
    """Seed a disposable SQLite development database with fictional data."""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if (
        not confirm_fictional
        or not current_app.debug
        or not uri.startswith("sqlite:")
    ):
        raise click.ClickException(
            "Seeding requires debug mode, SQLite, and --confirm-fictional."
        )
    from app.models import User

    if User.query.first():
        raise click.ClickException("Seed only an empty disposable database.")
    password = click.prompt(
        "Demo password", hide_input=True, confirmation_prompt=True
    )
    if not 8 <= len(password) <= 1024:
        raise click.ClickException("Choose an 8-1024 character password.")
    user = register_user("demo@example.com", password)
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    for index, status in enumerate(
        ("shortlisted", "applied", "interviewing", "offer")
    ):
        save_application(
            JobApplication(user_id=user.id),
            {
                "job_title": f"Example role {index + 1}",
                "company": "Fictional Company",
                "status": status,
                "board": "Example board",
                "job_url": "https://example.com/jobs",
                "applied_on": today if status != "shortlisted" else None,
                "follow_up_on": today + timedelta(days=index - 1),
            },
        )
    click.echo("Fictional demo created. Sign in as demo@example.com.")


def register_cli(app):
    app.cli.add_command(create_user)
    app.cli.add_command(seed_demo)
    app.cli.add_command(grant_runtime)
    app.cli.add_command(cleanup_imports)
    app.cli.add_command(sync_sources)
    app.cli.add_command(send_reminders)


@click.command("cleanup-imports")
@with_appcontext
def cleanup_imports():
    """Remove expired private import previews and completion receipts."""
    from app.import_service import cleanup_imports as cleanup

    count = cleanup()
    click.echo(f"Removed {count} expired import previews/receipts.")


@click.command("grant-runtime")
@with_appcontext
def grant_runtime():
    """Grant the pre-provisioned runtime role access to application tables."""
    if db.engine.dialect.name != "postgresql":
        raise click.ClickException("Runtime role grants require PostgreSQL.")
    append_only = {
        "status_event",
        "change_entry",
        "mutation_receipt",
        "application_mapping",
    }
    with db.engine.begin() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname='tracker_runtime'")
        ).scalar()
        if not exists:
            raise click.ClickException(
                "Provision tracker_runtime before granting access."
            )
        for table in db.metadata.sorted_tables:
            privileges = (
                "SELECT, INSERT"
                if table.name in append_only
                else "SELECT, INSERT, UPDATE"
            )
            if table.name in {
                "pairing_request",
                "import_batch",
                "source_connection",
                "source_record",
                "friendship",
            }:
                privileges += ", DELETE"
            quoted = db.engine.dialect.identifier_preparer.quote(table.name)
            connection.execute(
                text(
                    f"GRANT {privileges} ON TABLE public.{quoted} "
                    "TO tracker_runtime"
                )
            )
        connection.execute(
            text(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public "
                "TO tracker_runtime"
            )
        )
    click.echo(
        "Runtime table privileges granted. "
        "Schema ownership stays with the migrator."
    )


@click.command("sync-sources")
@click.option("--watch", is_flag=True, help="Keep polling for due sources.")
@with_appcontext
def sync_sources(watch):
    """Pull due connected sources; output contains only aggregate counts."""
    from app.source_scheduler import run_due_syncs, watch_sources

    if watch:
        watch_sources(current_app._get_current_object())
    else:
        result = run_due_syncs()
        click.echo(
            f"Synced {result['synced']} sources; {result['failed']} failed."
        )


@click.command("send-reminders")
@click.option(
    "--watch", is_flag=True, help="Check for due reminders every minute."
)
@with_appcontext
def send_reminders(watch):
    """Send opted-in daily nudges, without repeating a daily attempt."""
    from app.notifications import (
        mail_ready,
        run_due_reminders,
        watch_reminders,
    )

    if watch:
        watch_reminders(current_app._get_current_object())
    elif not mail_ready():
        raise click.ClickException(
            "Email reminders are disabled or SMTP/APP_BASE_URL "
            "configuration is incomplete."
        )
    else:
        result = run_due_reminders()
        click.echo(
            f"Sent {result['sent']}; failed {result['failed']}; "
            f"skipped {result['skipped']}."
        )
