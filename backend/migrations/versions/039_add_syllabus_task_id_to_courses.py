"""add syllabus_task_id to courses

Revision ID: 039
Revises: 038
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("syllabus_task_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "syllabus_task_id")
