"""Add tutor voice-output tables: per-message TTS cache and voice-call session log.

Revision ID: 082
Revises: 081
Create Date: 2026-04-24

Adds two tables supporting issue #1932 (hybrid tutor voice output):

1. ``tutor_message_audio`` — caches synthesized audio for the "listen" button
   on tutor replies. Keyed on (conversation_id, message_index, language) since
   tutor messages are positional entries in ``tutor_conversations.messages``
   and carry no per-message UUID. Unique constraint enforces idempotency:
   clicking listen twice on the same reply returns the cached URL.

2. ``tutor_voice_sessions`` — logs live voice-call sessions so we can enforce
   ``tutor_voice_daily_minutes_cap`` across sessions. Holds OpenAI Realtime
   session ID, start/end timestamps, and reported duration.

Uses raw SQL with ``IF NOT EXISTS`` guards mirroring the canonical 057
pattern, because ``sa.Enum(..., create_type=False)`` isn't reliable in the
Alembic context used by the deploy pipeline — staging blew up with
``type "audio_status_enum" already exists`` under the SQLAlchemy-generated
path (#1941). Forward-only; downgrade is kept for local dev reset.
"""

from alembic import op

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum is created by migration 057; guard against re-create so repeated
    # fresh-deploys or partial-retry flows don't blow up.
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
        CREATE TABLE IF NOT EXISTS tutor_message_audio (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES tutor_conversations(id) ON DELETE CASCADE,
            message_index INTEGER NOT NULL,
            language VARCHAR(5) NOT NULL,
            status audio_status_enum NOT NULL DEFAULT 'pending',
            storage_key TEXT,
            storage_url TEXT,
            duration_seconds INTEGER,
            file_size_bytes INTEGER,
            error_message TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            generated_at TIMESTAMP,
            CONSTRAINT uq_tutor_message_audio_conv_idx_lang
                UNIQUE (conversation_id, message_index, language)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tutor_message_audio_conversation_id
        ON tutor_message_audio (conversation_id);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tutor_voice_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            openai_session_id VARCHAR(100),
            started_at TIMESTAMP NOT NULL DEFAULT now(),
            ended_at TIMESTAMP,
            duration_seconds INTEGER
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tutor_voice_sessions_user_started
        ON tutor_voice_sessions (user_id, started_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tutor_voice_sessions")
    op.execute("DROP TABLE IF EXISTS tutor_message_audio")
    # Leave audio_status_enum in place — it's shared with generated_audio.
