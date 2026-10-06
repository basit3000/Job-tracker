"""Add short-lived private import previews and idempotent receipts.

Revision ID: f70a93bd2158
Revises: d48f7a916b02
"""

import sqlalchemy as sa
from alembic import op

revision = "f70a93bd2158"
down_revision = "d48f7a916b02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "import_batch",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("options", sa.JSON()),
        sa.Column("result", sa.JSON()),
    )
    op.create_index("ix_import_batch_user_id", "import_batch", ["user_id"])
    op.create_index(
        "ix_import_batch_expires_at", "import_batch", ["expires_at"]
    )


def downgrade():
    op.drop_index("ix_import_batch_expires_at", table_name="import_batch")
    op.drop_index("ix_import_batch_user_id", table_name="import_batch")
    op.drop_table("import_batch")
