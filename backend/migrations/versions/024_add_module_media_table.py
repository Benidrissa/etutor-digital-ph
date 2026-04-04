"""Add module_media table for audio summaries and other module-level media assets.

Revision ID: 024_add_module_media_table
Revises: 021_add_admin_syllabus_audit_log
Create Date: 2026-04-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "024_add_module_media_table"
down_revision: str | None = "021_add_admin_syllabus_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

media_status_enum = postgresql.ENUM(
    "pending", "generating", "ready", "failed", name="media_status_enum"
)


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "module_media"):
        return

    media_status_enum.create(conn, checkfirst=True)

    op.create_table(
        "module_media",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("media_type", sa.String(50), server_default="audio_summary", nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "generating",
                "ready",
                "failed",
                name="media_status_enum",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("script_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_module_media_module_id", "module_media", ["module_id"])
    op.create_index("ix_module_media_status", "module_media", ["status"])
    op.create_index(
        "ix_module_media_module_language_type",
        "module_media",
        ["module_id", "language", "media_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_module_media_module_language_type", table_name="module_media")
    op.drop_index("ix_module_media_status", table_name="module_media")
    op.drop_index("ix_module_media_module_id", table_name="module_media")
    op.drop_table("module_media")
    media_status_enum.drop(op.get_bind(), checkfirst=True)
