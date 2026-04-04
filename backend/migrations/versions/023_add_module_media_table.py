"""Add module_media table for AI-generated audio/video summaries.

Revision ID: 023_add_module_media_table
Revises: 022_add_settings_audit_actions
Create Date: 2026-04-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "023_add_module_media_table"
down_revision: str | None = "022_add_settings_audit_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

media_type_enum = postgresql.ENUM(
    "audio_summary",
    "video_summary",
    name="module_media_type_enum",
)

media_status_enum = postgresql.ENUM(
    "pending",
    "generating",
    "ready",
    "failed",
    name="module_media_status_enum",
)


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "module_media"):
        return

    media_type_enum.create(conn, checkfirst=True)
    media_status_enum.create(conn, checkfirst=True)

    op.create_table(
        "module_media",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column(
            "media_type",
            postgresql.ENUM(
                "audio_summary",
                "video_summary",
                name="module_media_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "generating",
                "ready",
                "failed",
                name="module_media_status_enum",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("media_data", sa.LargeBinary(), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_module_media_module_id", "module_media", ["module_id"])
    op.create_index("ix_module_media_status", "module_media", ["status"])
    op.create_index(
        "ix_module_media_module_type_lang",
        "module_media",
        ["module_id", "media_type", "language"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_module_media_module_type_lang", table_name="module_media")
    op.drop_index("ix_module_media_status", table_name="module_media")
    op.drop_index("ix_module_media_module_id", table_name="module_media")
    op.drop_table("module_media")
    media_type_enum.drop(op.get_bind(), checkfirst=True)
    media_status_enum.drop(op.get_bind(), checkfirst=True)
