"""Create module_media table.

Revision ID: 048
Revises: 047
Create Date: 2026-04-08

"""

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'media_status_enum') THEN
                CREATE TYPE media_status_enum AS ENUM ('pending', 'generating', 'ready', 'failed');
            END IF;
        END$$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS module_media (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            module_id UUID NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
            media_type VARCHAR(50) NOT NULL DEFAULT 'audio_summary',
            language VARCHAR(10) NOT NULL,
            status media_status_enum NOT NULL DEFAULT 'pending',
            storage_key TEXT,
            storage_url TEXT,
            duration_seconds INTEGER,
            file_size_bytes INTEGER,
            script_text TEXT,
            error_message TEXT,
            media_metadata JSONB,
            generated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_module_media_module_type_lang UNIQUE (module_id, media_type, language)
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_module_media_module_id ON module_media (module_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_module_media_status ON module_media (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_module_media_module_language_type ON module_media (module_id, language, media_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS module_media")
    op.execute("DROP TYPE IF EXISTS media_status_enum")
