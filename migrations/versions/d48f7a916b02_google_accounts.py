"""Add Google identities while preserving existing password accounts.

Revision ID: d48f7a916b02
Revises: c61e92ad7401
"""

import sqlalchemy as sa
from alembic import op

revision = "d48f7a916b02"
down_revision = "c61e92ad7401"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user") as batch:
        batch.alter_column(
            "email",
            existing_type=sa.String(120),
            type_=sa.String(254),
            existing_nullable=False,
        )
        batch.alter_column(
            "password_hash",
            existing_type=sa.String(512),
            nullable=True,
        )
        batch.add_column(sa.Column("google_subject", sa.String(255)))
        batch.create_unique_constraint(
            "uq_user_google_subject", ["google_subject"]
        )
        batch.create_check_constraint(
            "ck_user_login_method",
            "password_hash IS NOT NULL OR google_subject IS NOT NULL",
        )


def downgrade():
    # An older app cannot authenticate Google-only users. Refuse data loss
    # instead of discarding their identity or inventing a usable password.
    if (
        op.get_bind()
        .execute(
            sa.text(
                'SELECT 1 FROM "user" WHERE google_subject IS NOT NULL '
                "OR password_hash IS NULL OR length(email) > 120 LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError(
            "Google accounts or extended email addresses prevent downgrade. "
            "Restore a compatible backup instead of discarding identities."
        )
    with op.batch_alter_table("user") as batch:
        batch.drop_constraint("ck_user_login_method", type_="check")
        batch.drop_constraint("uq_user_google_subject", type_="unique")
        batch.drop_column("google_subject")
        batch.alter_column(
            "password_hash",
            existing_type=sa.String(512),
            nullable=False,
        )
        batch.alter_column(
            "email",
            existing_type=sa.String(254),
            type_=sa.String(120),
            existing_nullable=False,
        )
