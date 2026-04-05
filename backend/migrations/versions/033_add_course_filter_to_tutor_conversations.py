"""add course_filter to tutor_conversations

Revision ID: 033
Revises: 032
Create Date: 2026-04-05

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tutor_conversations",
        sa.Column("course_filter", JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tutor_conversations", "course_filter")
