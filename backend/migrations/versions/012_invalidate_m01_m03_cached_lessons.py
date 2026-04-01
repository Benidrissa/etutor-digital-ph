"""Invalidate cached lesson content for M01-M03 units

Deletes previously generated lesson content for modules M01, M02, and M03
so that lessons are regenerated with unit-specific RAG queries.

Revision ID: 012_invalidate_m01_m03_cached_lessons
Revises: 0d1135672916
Create Date: 2026-04-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012_invalidate_m01_m03_cached_lessons"
down_revision: str | None = "0d1135672916"
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
