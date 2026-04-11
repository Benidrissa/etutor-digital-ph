"""Create generated_audio table.

Revision ID: 057
Revises: 056
Create Date: 2026-04-11

"""

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use raw SQL for full idempotency (matches pattern from migration 048)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'audio_status_enum') THEN
                CREATE TYPE audio_status_enum AS ENUM ('pending', 'generating', 'ready', 'failed');
            END IF;
        END$$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_audio (
            id UUID PRIMARY KEY,
            lesson_id UUID REFERENCES generated_content(id) ON DELETE SET NULL,
            module_id UUID REFERENCES modules(id) ON DELETE SET NULL,
            unit_id TEXT,
            language VARCHAR(5) NOT NULL DEFAULT 'fr',
            storage_key TEXT,
            storage_url TEXT,
            script_text TEXT,
            duration_seconds INTEGER,
            file_size_bytes INTEGER,
            error_message TEXT,
            status audio_status_enum NOT NULL DEFAULT 'pending',
            generated_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_generated_audio_lesson_id
        ON generated_audio (lesson_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_generated_audio_status
        ON generated_audio (status);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS generated_audio")
    op.execute("DROP TYPE IF EXISTS audio_status_enum")
