"""Create generated_audio table.

Revision ID: 056
Revises: 055
Create Date: 2026-04-11

"""

import sqlalchemy as sa
from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type (IF NOT EXISTS for idempotency)
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE audio_status_enum AS ENUM ('pending', 'generating', 'ready', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    audio_status_enum = sa.Enum(
        "pending", "generating", "ready", "failed", name="audio_status_enum", create_type=False
    )

    op.create_table(
        "generated_audio",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "lesson_id",
            sa.Uuid(),
            sa.ForeignKey("generated_content.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "module_id",
            sa.Uuid(),
            sa.ForeignKey("modules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("unit_id", sa.Text(), nullable=True),
        sa.Column("language", sa.String(5), server_default="fr", nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("script_text", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("status", audio_status_enum, server_default="pending", nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_generated_audio_lesson_id", "generated_audio", ["lesson_id"])
    op.create_index("ix_generated_audio_status", "generated_audio", ["status"])


def downgrade() -> None:
    op.drop_index("ix_generated_audio_status", table_name="generated_audio")
    op.drop_index("ix_generated_audio_lesson_id", table_name="generated_audio")
    op.drop_table("generated_audio")
    sa.Enum(name="audio_status_enum").drop(op.get_bind(), checkfirst=True)
