"""add chunk_summaries table for resilient syllabus generation retry

Revision ID: 043
Revises: 042
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk_summaries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("book_name", sa.String(512), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "book_name", "chunk_index", name="uq_chunk_summary"),
    )
    op.create_index("ix_chunk_summaries_course_id", "chunk_summaries", ["course_id"])


def downgrade() -> None:
    op.drop_index("ix_chunk_summaries_course_id", table_name="chunk_summaries")
    op.drop_table("chunk_summaries")
