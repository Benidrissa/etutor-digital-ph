"""add course_bundles table for ZIP export jobs

Revision ID: 097_add_course_bundles
Revises: 096_add_file_hash_to_course_resources
Create Date: 2026-05-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

revision: str = "097_add_course_bundles"
down_revision: str | None = "096_add_file_hash_to_course_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent enum creation — staging may have the type from a prior
    # partial migration run that failed before the table was created.
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE bundlestatus AS ENUM ('pending', 'generating', 'ready', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )

    op.create_table(
        "course_bundles",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "course_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("level", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("country", sa.String(4), server_default="SN", nullable=False),
        sa.Column(
            "status",
            PG_ENUM(
                "pending",
                "generating",
                "ready",
                "failed",
                name="bundlestatus",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("task_id", sa.String(255), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("file_count", sa.SmallInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_course_bundles_course_id", "course_bundles", ["course_id"])
    op.create_index("ix_course_bundles_status", "course_bundles", ["status"])
    op.create_index("ix_course_bundles_requested_by", "course_bundles", ["requested_by"])


def downgrade() -> None:
    op.drop_index("ix_course_bundles_requested_by", table_name="course_bundles")
    op.drop_index("ix_course_bundles_status", table_name="course_bundles")
    op.drop_index("ix_course_bundles_course_id", table_name="course_bundles")
    op.drop_table("course_bundles")
    op.execute("DROP TYPE IF EXISTS bundlestatus")
