"""Add is_marketplace and credit_price fields to courses table.

Revision ID: 025_add_marketplace_fields_to_courses
Revises: 024_add_course_taxonomy
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025_add_marketplace_fields_to_courses"
down_revision: str | None = "024_add_course_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_marketplace BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS credit_price INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_courses_is_marketplace ON courses (is_marketplace)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_courses_is_marketplace")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS credit_price")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS is_marketplace")
