"""Fix module_number unique constraint — per course, not global.

Revision ID: 025_fix_module_number_unique_per_course
Revises: 024_add_course_taxonomy
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025_fix_module_number_unique_per_course"
down_revision: str | None = "024_add_course_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_modules_module_number")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_modules_course_module_number "
        "ON modules (course_id, module_number)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_modules_course_module_number")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_modules_module_number "
        "ON modules (module_number)"
    )
