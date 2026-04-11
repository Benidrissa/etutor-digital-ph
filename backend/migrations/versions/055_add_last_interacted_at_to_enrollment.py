"""Add last_interacted_at to user_course_enrollment.

Revision ID: 055
Revises: 054
Create Date: 2026-04-11

"""

import sqlalchemy as sa
from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_course_enrollment",
        sa.Column("last_interacted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_uce_last_interacted",
        "user_course_enrollment",
        ["user_id", "last_interacted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_uce_last_interacted", table_name="user_course_enrollment")
    op.drop_column("user_course_enrollment", "last_interacted_at")
