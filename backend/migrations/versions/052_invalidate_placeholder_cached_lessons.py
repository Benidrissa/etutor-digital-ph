"""Invalidate cached lessons containing placeholder text

Deletes generated lesson content that still has the old placeholder
values injected by the pre-fix _parse_lesson_content() implementation.

Revision ID: 052
Revises: 051
Create Date: 2026-04-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "052"
down_revision: str | None = "051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM generated_content
        WHERE content_type = 'lesson'
          AND content::text LIKE '%Exemple contextuel sera extrait%'
    """)


def downgrade() -> None:
    pass
