"""Add module_media table for audio/video/podcast summaries.

Revision ID: 025_add_module_media
Revises: 025_marketplace_and_credits
Create Date: 2026-04-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025c"
down_revision: str | None = "025b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE mediatype AS ENUM ('audio_summary', 'video_summary', 'podcast_summary');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE mediastatus AS ENUM ('pending', 'generating', 'ready', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    op.create_table(
        "module_media",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "module_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_type",
            sa.Enum("audio_summary", "video_summary", "podcast_summary", name="mediatype"),
            nullable=False,
        ),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("storage_url", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "generating", "ready", "failed", name="mediastatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "module_id", "media_type", "language", name="uq_module_media_module_type_lang"
        ),
    )
    op.create_index("ix_module_media_module_id", "module_media", ["module_id"])


def downgrade() -> None:
    op.drop_index("ix_module_media_module_id", table_name="module_media")
    op.drop_table("module_media")
    op.execute("DROP TYPE IF EXISTS mediatype")
    op.execute("DROP TYPE IF EXISTS mediastatus")
