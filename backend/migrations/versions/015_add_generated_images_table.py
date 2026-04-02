"""Add generated_images table for DALL-E 3 async image generation with semantic reuse

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


def upgrade() -> None:
    op.create_table(
        "generated_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=True),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("unit_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("dalle_prompt", sa.String(), nullable=True),
        sa.Column(
            "semantic_tags",
            postgresql.ARRAY(sa.String()),
            nullable=True,
            server_default="{}",
        ),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("alt_text_fr", sa.String(), nullable=True),
        sa.Column("alt_text_en", sa.String(), nullable=True),
        sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["generated_content.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_images_lesson_id", "generated_images", ["lesson_id"])
    op.create_index("ix_generated_images_module_id", "generated_images", ["module_id"])
    op.create_index("ix_generated_images_unit_id", "generated_images", ["unit_id"])
    op.create_index("ix_generated_images_status", "generated_images", ["status"])


def downgrade() -> None:
    op.drop_index("ix_generated_images_status", table_name="generated_images")
    op.drop_index("ix_generated_images_unit_id", table_name="generated_images")
    op.drop_index("ix_generated_images_module_id", table_name="generated_images")
    op.drop_index("ix_generated_images_lesson_id", table_name="generated_images")
    op.drop_table("generated_images")
