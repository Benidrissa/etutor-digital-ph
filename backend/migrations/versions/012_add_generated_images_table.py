"""Add generated_images table for DALL-E 3 async image generation (US-025, FR-03.2)

Revision ID: 012_add_generated_images_table
Revises: 011_add_email_otps_table
Create Date: 2026-04-01 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012_add_generated_images_table"
down_revision: str | None = "011_add_email_otps_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generated_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("dalle_prompt", sa.Text(), nullable=True),
        sa.Column("semantic_tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("key_concept", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("alt_text_fr", sa.Text(), nullable=True),
        sa.Column("alt_text_en", sa.Text(), nullable=True),
        sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_images_lesson_id", "generated_images", ["lesson_id"])
    op.create_index("ix_generated_images_module_id", "generated_images", ["module_id"])
    op.create_index("ix_generated_images_status", "generated_images", ["status"])


def downgrade() -> None:
    op.drop_index("ix_generated_images_status", table_name="generated_images")
    op.drop_index("ix_generated_images_module_id", table_name="generated_images")
    op.drop_index("ix_generated_images_lesson_id", table_name="generated_images")
    op.drop_table("generated_images")
