"""add syllabus_context to courses

Revision ID: 041
Revises: 040
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("syllabus_context", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "syllabus_context")
