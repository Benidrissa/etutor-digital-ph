"""Add creation_mode to courses.

Revision ID: 062
Revises: 061
Create Date: 2026-04-14

"""

import sqlalchemy as sa
from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("creation_mode", sa.String(20), server_default="legacy", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("courses", "creation_mode")
