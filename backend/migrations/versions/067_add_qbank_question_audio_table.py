"""Add qbank_question_audio table for per-question TTS audio (FR + Moore + Dioula).

Revision ID: 067
Revises: 066
Create Date: 2026-04-16

"""

import sqlalchemy as sa
from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE qbank_audio_status_enum AS ENUM ('pending', 'generating', 'ready', 'failed')")

    op.create_table(
        "qbank_question_audio",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="fr"),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_manual_upload", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "generating",
                "ready",
                "failed",
                name="qbank_audio_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "language", name="uq_qbank_question_audio_question_lang"),
    )

    op.create_index("ix_qbank_question_audio_question_id", "qbank_question_audio", ["question_id"])
    op.create_index("ix_qbank_question_audio_status", "qbank_question_audio", ["status"])


def downgrade() -> None:
    op.drop_index("ix_qbank_question_audio_status", table_name="qbank_question_audio")
    op.drop_index("ix_qbank_question_audio_question_id", table_name="qbank_question_audio")
    op.drop_table("qbank_question_audio")
    op.execute("DROP TYPE IF EXISTS qbank_audio_status_enum")
