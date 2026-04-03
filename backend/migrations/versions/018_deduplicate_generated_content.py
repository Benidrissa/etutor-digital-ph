"""Deduplicate generated_content rows caused by concurrent Celery workers.

Concurrent workers could insert multiple rows for the same
(module_id, content_type, language, level, country_context, unit_id) tuple.
This migration removes duplicate rows, keeping only the most recently
generated entry per unique key, so that the unique index from migration 017
remains valid and future concurrent inserts hit an ON CONFLICT instead of
inserting duplicates.

Revision ID: 018_deduplicate_generated_content
Revises: 017_fix_unique_lesson_per_unit_index
Create Date: 2026-04-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018_deduplicate_generated_content"
down_revision: str | None = "017_fix_unique_lesson_per_unit_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM generated_content
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            module_id,
                            content_type,
                            language,
                            level,
                            country_context,
                            content->>'unit_id'
                        ORDER BY generated_at DESC
                    ) AS rn
                FROM generated_content
                WHERE content->>'unit_id' IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
        """
    )

    op.execute(
        """
        DELETE FROM generated_content
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            module_id,
                            content_type,
                            language,
                            level,
                            country_context
                        ORDER BY generated_at DESC
                    ) AS rn
                FROM generated_content
                WHERE content->>'unit_id' IS NULL
            ) ranked
            WHERE rn > 1
        )
        """
    )


def downgrade() -> None:
    pass
