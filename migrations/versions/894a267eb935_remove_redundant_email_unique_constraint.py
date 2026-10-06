"""Remove redundant email unique constraint

Revision ID: 894a267eb935
Revises: 82f7af7adc75
Create Date: 2026-10-06 17:53:44.178468

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "894a267eb935"
down_revision = "82f7af7adc75"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite's original unnamed constraint is already represented by its index.
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("user")
    for constraint in constraints:
        if constraint["column_names"] == ["email"] and constraint["name"]:
            with op.batch_alter_table("user", schema=None) as batch_op:
                batch_op.drop_constraint(constraint["name"], type_="unique")


def downgrade():
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("user")
    if not any(item["column_names"] == ["email"] for item in constraints):
        with op.batch_alter_table("user", schema=None) as batch_op:
            batch_op.create_unique_constraint("user_email_key", ["email"])
