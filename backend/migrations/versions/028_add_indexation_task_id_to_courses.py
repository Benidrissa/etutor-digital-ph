"""Add indexation_task_id to courses table.

Revision ID: 028
Revises: 027
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa

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
