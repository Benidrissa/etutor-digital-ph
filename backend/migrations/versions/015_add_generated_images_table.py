"""Add generated_images table for storing AI-generated lesson illustrations

Revision ID: 015_add_generated_images_table
Revises: 014_add_compacted_context_to_conversations
Create Date: 2026-04-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015_add_generated_images_table"
down_revision: str | None = "014_add_compacted_context_to_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

image_status_enum = postgresql.ENUM(
    "pending", "generating", "ready", "failed", name="image_status_enum"
)


def upgrade() -> None:
    image_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "generated_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=True),
        sa.Column("module_id", sa.UUID(), nullable=True),
        sa.Column("unit_id", sa.Text(), nullable=True),
        sa.Column("concept", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("format", sa.String(20), server_default="webp", nullable=False),
        sa.Column("width", sa.Integer(), server_default="512", nullable=False),
        sa.Column("alt_text_fr", sa.Text(), nullable=True),
        sa.Column("alt_text_en", sa.Text(), nullable=True),
        sa.Column("semantic_tags", postgresql.JSONB(), nullable=True),
        sa.Column("reuse_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "generating",
                "ready",
                "failed",
                name="image_status_enum",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["generated_content.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_generated_images_semantic_tags_gin",
        "generated_images",
        ["semantic_tags"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_generated_images_status",
        "generated_images",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_generated_images_status", table_name="generated_images")
    op.drop_index("ix_generated_images_semantic_tags_gin", table_name="generated_images")
    op.drop_table("generated_images")
    image_status_enum.drop(op.get_bind(), checkfirst=True)
