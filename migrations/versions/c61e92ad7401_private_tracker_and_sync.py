"""Add canonical statuses, calendar dates, device pairing and durable sync.

Revision ID: c61e92ad7401
Revises: 894a267eb935
"""

from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "c61e92ad7401"
down_revision = "894a267eb935"
branch_labels = None
depends_on = None

STATUS_MAP = {
    "Wishlist": "shortlisted",
    "Applied": "applied",
    "Interviewing": "interviewing",
    "Offer": "offer",
    "Accepted": "accepted",
    "Rejected": "rejected",
}
STATUSES = tuple(STATUS_MAP.values()) + ("closed", "skipped")


def _added_columns():
    return (
        sa.Column("public_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("applied_on", sa.Date()),
        sa.Column("follow_up_on", sa.Date()),
        sa.Column("board", sa.String(128)),
        sa.Column("contact_email", sa.String(254)),
        sa.Column("contact_phone", sa.String(80)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "posted_at_approximate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("applicants", sa.JSON()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )


def _owner():
    return sa.Column(
        "user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False
    )


def _primary():
    return sa.Column("id", sa.Integer(), primary_key=True)


def _time(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _tables():
    op.create_table(
        "status_event",
        _primary(),
        _owner(),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("job_application.id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(64)),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("installation_id", sa.String(128)),
        sa.Column("source_event_id", sa.String(128)),
        _time("occurred_at", True),
        _time("recorded_at"),
        sa.UniqueConstraint(
            "user_id",
            "installation_id",
            "source_event_id",
            name="uq_source_status_event",
        ),
    )
    op.create_index(
        "ix_status_event_application_id", "status_event", ["application_id"]
    )
    op.create_table(
        "application_mapping",
        _primary(),
        _owner(),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("job_application.id"),
            nullable=False,
        ),
        sa.Column("installation_id", sa.String(128), nullable=False),
        sa.Column("local_record_id", sa.String(256), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "installation_id",
            "local_record_id",
            name="uq_local_application",
        ),
        sa.UniqueConstraint(
            "application_id",
            "installation_id",
            name="uq_application_installation",
        ),
    )
    op.create_table(
        "change_entry",
        _primary(),
        _owner(),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("mutation_id", sa.String(128)),
        _time("created_at"),
        sa.UniqueConstraint(
            "user_id", "sequence", name="uq_account_change_sequence"
        ),
    )
    op.create_index(
        "ix_change_entry_application_id", "change_entry", ["application_id"]
    )
    op.create_table(
        "device",
        sa.Column("id", sa.String(36), primary_key=True),
        _owner(),
        sa.Column("installation_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("optional_fields", sa.JSON(), nullable=False),
        _time("created_at"),
        _time("last_seen_at", True),
        _time("revoked_at", True),
        sa.Column("last_error_code", sa.String(40)),
        _time("last_error_at", True),
    )
    op.create_index("ix_device_user_id", "device", ["user_id"])
    op.create_table(
        "pairing_request",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("installation_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        _time("expires_at"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id")),
        sa.Column("optional_fields", sa.JSON()),
        _time("consumed_at", True),
    )
    op.create_table(
        "mutation_receipt",
        _primary(),
        _owner(),
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("device.id"),
            nullable=False,
        ),
        sa.Column("mutation_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "device_id", "mutation_id", name="uq_device_mutation"
        ),
    )


def _iso(value):
    if value is None:
        return None
    return (
        value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _baseline(row):
    url = row["job_url"]
    try:
        parsed = urlsplit(url or "")
        safe = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        safe = False
    return {
        "id": row["public_id"],
        "version": 1,
        "deletedAt": None,
        "title": row["job_title"],
        "company": row["company"],
        "url": url if safe else None,
        "board": None,
        "location": row["location"],
        "status": row["status"],
        "appliedDate": None,
        "followUpDate": None,
        "createdAt": _iso(row["created_at"]),
        "updatedAt": _iso(row["updated_date"]),
        "note": row["notes"],
        "salary": row["salary"],
        "contactName": row["contact_person"],
        "contactEmail": None,
        "contactPhone": None,
        "postedAt": None,
        "postedAtApproximate": False,
        "applicants": None,
        "statusHistory": [],
        "mappings": [],
    }


def upgrade():
    bind = op.get_bind()
    statuses = (
        bind.execute(sa.text("SELECT DISTINCT status FROM job_application"))
        .scalars()
        .all()
    )
    if any(
        status not in STATUS_MAP and status not in STATUSES
        for status in statuses
    ):
        raise RuntimeError(
            "Resolve unknown legacy application statuses before upgrading."
        )
    with op.batch_alter_table("user") as batch:
        batch.add_column(
            sa.Column(
                "feed_sequence",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            )
        )
    with op.batch_alter_table("job_application") as batch:
        for column in _added_columns():
            batch.add_column(column)
    metadata = sa.MetaData()
    jobs = sa.Table("job_application", metadata, autoload_with=bind)
    now = datetime.now(timezone.utc)
    for row in bind.execute(sa.select(jobs)).mappings().all():
        bind.execute(
            jobs.update()
            .where(jobs.c.id == row["id"])
            .values(
                public_id=str(uuid4()),
                created_at=row["applied_date"] or now,
                status=STATUS_MAP.get(row["status"], row["status"]),
            )
        )
    with op.batch_alter_table("job_application") as batch:
        batch.alter_column(
            "public_id", existing_type=sa.String(36), nullable=False
        )
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch.create_unique_constraint("uq_job_public_id", ["public_id"])
        batch.create_check_constraint("ck_job_version", "version >= 1")
        batch.create_check_constraint(
            "ck_job_status",
            "status IN (" + ",".join(repr(item) for item in STATUSES) + ")",
        )
        batch.create_index("ix_job_application_follow_up_on", ["follow_up_on"])
    _tables()
    users = sa.Table("user", metadata, autoload_with=bind)
    feed = sa.Table("change_entry", metadata, autoload_with=bind)
    sequences = {}
    for row in (
        bind.execute(sa.select(jobs).order_by(jobs.c.id)).mappings().all()
    ):
        owner = row["user_id"]
        sequences[owner] = sequences.get(owner, 0) + 1
        bind.execute(
            feed.insert().values(
                user_id=owner,
                sequence=sequences[owner],
                application_id=row["public_id"],
                payload=_baseline(row),
                source="migration",
                created_at=now,
            )
        )
    for owner, sequence in sequences.items():
        bind.execute(
            users.update()
            .where(users.c.id == owner)
            .values(feed_sequence=sequence)
        )


def downgrade():
    for table in (
        "mutation_receipt",
        "pairing_request",
        "device",
        "change_entry",
        "application_mapping",
        "status_event",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    reverse = {value: key for key, value in STATUS_MAP.items()}
    with op.batch_alter_table("job_application") as batch:
        batch.drop_constraint("ck_job_status", type_="check")
        batch.drop_constraint("ck_job_version", type_="check")
        batch.drop_constraint("uq_job_public_id", type_="unique")
        batch.drop_index("ix_job_application_follow_up_on")
        for column in _added_columns():
            batch.drop_column(column.name)
    for status in STATUSES:
        bind.execute(
            sa.text(
                "UPDATE job_application SET status=:old WHERE status=:new"
            ),
            {"new": status, "old": reverse.get(status, "Wishlist")},
        )
    with op.batch_alter_table("user") as batch:
        batch.drop_column("feed_sequence")
