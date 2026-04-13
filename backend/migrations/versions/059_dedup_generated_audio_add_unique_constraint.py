"""Deduplicate generated_audio rows and add unique constraint on (module_id, unit_id, language).

Revision ID: 059
Revises: 058
Create Date: 2026-04-13

"""

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Delete duplicate rows, keeping the most recent ready one per (module_id, unit_id, language).
    # If no ready row exists, keep the most recent row regardless of status.
    op.execute(
        """
        DELETE FROM generated_audio
        WHERE id NOT IN (
            SELECT DISTINCT ON (module_id, unit_id, language) id
            FROM generated_audio
            ORDER BY module_id, unit_id, language,
                     (CASE WHEN status = 'ready' THEN 0 ELSE 1 END),
                     created_at DESC
        )
        AND module_id IS NOT NULL
        AND unit_id IS NOT NULL;
        """
    )

    # Step 2: Add unique constraint
    op.execute(
        """
        ALTER TABLE generated_audio
        ADD CONSTRAINT uq_generated_audio_module_unit_lang
        UNIQUE (module_id, unit_id, language);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE generated_audio
        DROP CONSTRAINT IF EXISTS uq_generated_audio_module_unit_lang;
        """
    )
