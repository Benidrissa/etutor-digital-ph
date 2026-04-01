"""Add generated_images table

Revision ID: 013_add_generated_images_table
Revises: 012_merge_module_units_and_email_otps
Create Date: 2026-04-01 14:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_add_generated_images_table"
down_revision: str | None = "012_merge_module_units_and_email_otps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    imagestatus_enum = postgresql.ENUM(
        "pending", "generating", "ready", "failed", name="imagestatus", create_type=False
    )
    imagestatus_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "generated_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            sa.Enum("pending", "generating", "ready", "failed", name="imagestatus"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["lesson_id"], ["generated_content.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_generated_images_status",
        "generated_images",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_generated_images_semantic_tags",
        "generated_images",
        ["semantic_tags"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_generated_images_semantic_tags", table_name="generated_images")
    op.drop_index("ix_generated_images_status", table_name="generated_images")
    op.drop_table("generated_images")

    sa.Enum(name="imagestatus").drop(op.get_bind(), checkfirst=True)
