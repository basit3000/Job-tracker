"""Private notification inbox, email outbox and channel preferences."""

import sqlalchemy as sa
from alembic import op

revision = "c31e6a920d84"
down_revision = "b24f08d93c71"
branch_labels = None
depends_on = None

PREFERENCES = {
    "social_in_app": True,
    "social_email": False,
    "followups_in_app": True,
    "followups_email": False,
    "sources_in_app": True,
    "sources_email": False,
    "reminders_in_app": False,
}


def upgrade():
    with op.batch_alter_table("notification_preference") as batch:
        for name, enabled in PREFERENCES.items():
            batch.add_column(
                sa.Column(
                    name,
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true() if enabled else sa.false(),
                )
            )
    op.create_table(
        "notification",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False
        ),
        sa.Column("event_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("email_status", sa.String(8), nullable=False),
        sa.Column("email_sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "user_id", "event_key", name="uq_notification_event"
        ),
        sa.CheckConstraint(
            "kind IN ('social','followups','sources','reminders')",
            name="ck_notification_kind",
        ),
        sa.CheckConstraint(
            "email_status IN "
            "('disabled','pending','claimed','sent','failed','skipped')",
            name="ck_notification_email_status",
        ),
    )
    op.create_index(
        "ix_notification_inbox",
        "notification",
        ["user_id", "in_app", "dismissed_at", "created_at"],
    )
    op.create_index(
        "ix_notification_outbox",
        "notification",
        ["email_status", "created_at"],
    )


def downgrade():
    op.drop_table("notification")
    with op.batch_alter_table("notification_preference") as batch:
        for name in reversed(PREFERENCES):
            batch.drop_column(name)
