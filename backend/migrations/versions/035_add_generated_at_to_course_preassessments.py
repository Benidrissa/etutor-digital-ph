"""add generated_at column to course_preassessments

Revision ID: 035
Revises: 034
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'course_preassessments' AND column_name = 'generated_at'"
        )
    )
    if result.fetchone() is None:
        op.add_column(
            "course_preassessments",
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("course_preassessments", "generated_at")
