"""add course_filter to tutor_conversations

Revision ID: 029
Revises: 028
Create Date: 2026-04-04

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tutor_conversations",
        sa.Column("course_filter", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tutor_conversations", "course_filter")
