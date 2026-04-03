"""Fix unique constraint on generated_content to include country_context and level.

The previous index (if deployed) only covered (module_id, content_type, language,
content->>'unit_id'), which caused UniqueViolationError when generating content for
the same module+unit+language but different country or level.

The corrected index adds country_context and level so that content for different
country/level combinations can coexist, matching the 6-field cache key used by the
service layer: (module_id, content_type, language, level, country_context, unit_id).

Revision ID: 017_fix_unique_lesson_per_unit_index
Revises: 016_add_image_data_bytea
Create Date: 2026-04-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "017_fix_unique_lesson_per_unit_index"
down_revision: str | None = "016_add_image_data_bytea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_unique_lesson_per_unit")

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_lesson_per_unit
        ON generated_content (
            module_id,
            content_type,
            language,
            level,
            country_context,
            (content ->> 'unit_id')
        )
        WHERE content ->> 'unit_id' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_unique_lesson_per_unit")
