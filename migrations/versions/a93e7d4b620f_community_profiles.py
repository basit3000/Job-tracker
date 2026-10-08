"""Add opt-in community profiles and mutual friendships.

Revision ID: a93e7d4b620f
Revises: c82b4f7d901a
"""

import sqlalchemy as sa
from alembic import op

revision = "a93e7d4b620f"
down_revision = "c82b4f7d901a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user") as batch:
        batch.add_column(sa.Column("handle", sa.String(24)))
        batch.add_column(sa.Column("display_name", sa.String(60)))
        batch.add_column(sa.Column("bio", sa.String(280)))
        batch.add_column(
            sa.Column(
                "profile_visibility",
                sa.String(7),
                nullable=False,
                server_default="private",
            )
        )
        batch.add_column(
            sa.Column(
                "share_jobs",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "daily_goal",
                sa.Integer(),
                nullable=False,
                server_default="5",
            )
        )
        batch.create_unique_constraint("uq_user_handle", ["handle"])
        batch.create_check_constraint(
            "ck_user_profile_visibility",
            "profile_visibility IN ('private','public')",
        )
        batch.create_check_constraint(
            "ck_user_daily_goal", "daily_goal BETWEEN 1 AND 100"
        )
    op.create_table(
        "friendship",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_low_id",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column(
            "user_high_id",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(8), nullable=False, server_default="pending"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_low_id", "user_high_id", name="uq_friendship_pair"
        ),
        sa.CheckConstraint(
            "user_low_id < user_high_id", name="ck_friendship_order"
        ),
        sa.CheckConstraint(
            "requested_by_id = user_low_id OR requested_by_id = user_high_id",
            name="ck_friendship_requester",
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted')", name="ck_friendship_status"
        ),
    )
    for column in ("user_low_id", "user_high_id"):
        op.create_index(f"ix_friendship_{column}", "friendship", [column])
    op.create_index(
        "ix_job_social_activity",
        "job_application",
        ["user_id", "applied_on", "status"],
    )


def downgrade():
    op.drop_index("ix_job_social_activity", table_name="job_application")
    op.drop_table("friendship")
    with op.batch_alter_table("user") as batch:
        batch.drop_constraint("ck_user_daily_goal", type_="check")
        batch.drop_constraint("ck_user_profile_visibility", type_="check")
        batch.drop_constraint("uq_user_handle", type_="unique")
        for column in (
            "daily_goal",
            "share_jobs",
            "profile_visibility",
            "bio",
            "display_name",
            "handle",
        ):
            batch.drop_column(column)
