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

Forward-only: downgrade included for local dev reset.
"""

import sqlalchemy as sa
from alembic import op

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tutor_message_audio",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tutor_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_index", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "generating",
                "ready",
                "failed",
                name="audio_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "conversation_id",
            "message_index",
            "language",
            name="uq_tutor_message_audio_conv_idx_lang",
        ),
    )
    op.create_index(
        "ix_tutor_message_audio_conversation_id",
        "tutor_message_audio",
        ["conversation_id"],
    )

    op.create_table(
        "tutor_voice_sessions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("openai_session_id", sa.String(length=100), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_tutor_voice_sessions_user_started",
        "tutor_voice_sessions",
        ["user_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tutor_voice_sessions_user_started", "tutor_voice_sessions")
    op.drop_table("tutor_voice_sessions")
    op.drop_index("ix_tutor_message_audio_conversation_id", "tutor_message_audio")
    op.drop_table("tutor_message_audio")
