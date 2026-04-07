"""add image_extraction_task_id to courses

Revision ID: 040
Revises: 039
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("image_extraction_task_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "image_extraction_task_id")
