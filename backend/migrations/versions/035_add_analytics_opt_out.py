"""Add analytics_opt_out column to users table.

Revision ID: 035
Revises: 034
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("analytics_opt_out", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "analytics_opt_out")
