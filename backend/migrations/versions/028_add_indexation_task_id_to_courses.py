"""add indexation_task_id to courses

Revision ID: 028
Revises: 027
Create Date: 2026-04-04

"""

import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("indexation_task_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "indexation_task_id")
