"""Add private source connections, merge baselines and reviewed sync batches.

Revision ID: c82b4f7d901a
Revises: f70a93bd2158
"""

import sqlalchemy as sa
from alembic import op

revision = "c82b4f7d901a"
down_revision = "f70a93bd2158"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_connection",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("reference", sa.JSON(), nullable=False),
        sa.Column("credential_ciphertext", sa.Text()),
        sa.Column("options", sa.JSON()),
        sa.Column("columns", sa.JSON()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.JSON()),
        sa.Column("last_error", sa.String(256)),
        sa.CheckConstraint("version >= 1", name="ck_source_version"),
        sa.CheckConstraint(
            "interval_minutes IN (0,15,60)", name="ck_source_interval"
        ),
        sa.CheckConstraint(
            "provider IN ('google_public','google_private','notion')",
            name="ck_source_provider",
        ),
    )
    op.create_index(
        "ix_source_connection_user_id", "source_connection", ["user_id"]
    )
    op.create_index(
        "ix_source_connection_next_sync_at",
        "source_connection",
        ["next_sync_at"],
    )
    op.create_table(
        "source_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("source_connection.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False
        ),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("job_application.id"),
            nullable=False,
        ),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "connection_id", "source_key", name="uq_source_record"
        ),
        sa.UniqueConstraint(
            "connection_id", "application_id", name="uq_source_application"
        ),
    )
    op.create_index(
        "ix_source_record_connection_id", "source_record", ["connection_id"]
    )
    with op.batch_alter_table("import_batch") as batch:
        batch.add_column(sa.Column("connection_id", sa.String(36)))
        batch.add_column(sa.Column("connection_version", sa.Integer()))
        batch.create_foreign_key(
            "fk_import_batch_source",
            "source_connection",
            ["connection_id"],
            ["id"],
        )
        batch.create_index("ix_import_batch_connection_id", ["connection_id"])


def downgrade():
    with op.batch_alter_table("import_batch") as batch:
        batch.drop_index("ix_import_batch_connection_id")
        batch.drop_constraint("fk_import_batch_source", type_="foreignkey")
        batch.drop_column("connection_version")
        batch.drop_column("connection_id")
    op.drop_index("ix_source_record_connection_id", table_name="source_record")
    op.drop_table("source_record")
    op.drop_index(
        "ix_source_connection_next_sync_at", table_name="source_connection"
    )
    op.drop_index(
        "ix_source_connection_user_id", table_name="source_connection"
    )
    op.drop_table("source_connection")
