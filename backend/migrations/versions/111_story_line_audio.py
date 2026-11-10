"""Add story_line_audio: OpenAI TTS clips for story read-aloud (#2704).

One row per unique spoken line: ``text_hash`` (sha256 of TTS model, voice
profile, language, voice version and text, unique), ``language``, ``voice``
(the profile, e.g. ``narrator`` or ``girl``), ``model``, the MinIO
``storage_key`` and size, and timestamps. A row is written only once its clip
is stored.

The upgrade is additive and changes no other table. The downgrade drops the
table; the clips in MinIO under ``story-audio/`` are left for a bucket cleanup.

Revision ID: 111_story_line_audio
Revises: 110_story_module_plans
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "111_story_line_audio"
down_revision = "110_story_module_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_line_audio",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(5), nullable=False),
        sa.Column("voice", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("text_hash", name="uq_story_line_audio_text_hash"),
    )


def downgrade() -> None:
    op.drop_table("story_line_audio")
