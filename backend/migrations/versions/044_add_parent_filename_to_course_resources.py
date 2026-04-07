"""add parent_filename to course_resources for chapter-split tracking

Revision ID: 044
Revises: 043
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_resources",
        sa.Column("parent_filename", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("course_resources", "parent_filename")
