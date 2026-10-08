"""Opt-in application reminders and durable daily delivery claims."""

import sqlalchemy as sa
from alembic import op

revision = "b24f08d93c71"
down_revision = "a93e7d4b620f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_preference",
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id"), primary_key=True
        ),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=False),
        sa.Column("reminder_hour", sa.Integer(), nullable=False),
        sa.Column("unsubscribe_key", sa.String(36), nullable=False),
        sa.CheckConstraint(
            "reminder_hour BETWEEN 0 AND 23", name="ck_reminder_hour"
        ),
    )
    op.create_table(
        "reminder_delivery",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "local_date", name="uq_reminder_day"),
        sa.CheckConstraint(
            "status IN ('claimed','sent','failed','skipped')",
            name="ck_reminder_status",
        ),
    )


def downgrade():
    op.drop_table("reminder_delivery")
    op.drop_table("notification_preference")
