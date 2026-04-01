"""Invalidate stale M01-M03 lesson cache so units regenerate with topic-specific queries

Revision ID: 012_invalidate_m01_m03_lesson_cache
Revises: 011_add_email_otps_table, 0d1135672916
Create Date: 2026-04-01 16:13:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "012_invalidate_m01_m03_lesson_cache"
down_revision: tuple[str, str] = ("011_add_email_otps_table", "0d1135672916")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM generated_content
        WHERE content_type = 'lesson'
          AND module_id IN (
              SELECT id FROM modules WHERE module_number IN (1, 2, 3)
          )
    """)


def downgrade() -> None:
    pass
