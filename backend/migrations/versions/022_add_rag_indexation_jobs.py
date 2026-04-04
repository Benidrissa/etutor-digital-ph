"""Add rag_indexation_jobs table and set rag_collection_id on default course.

Revision ID: 022_add_rag_indexation_jobs
Revises: 021_add_courses_and_enrollment
Create Date: 2026-04-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "022_add_rag_indexation_jobs"
down_revision: str | None = "021_add_courses_and_enrollment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_COURSE_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_COURSE_RAG_COLLECTION_ID = "sante-publique-aof"


def upgrade() -> None:
    op.create_table(
        "rag_indexation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "extracting",
                "chunking",
                "embedding",
                "complete",
                "failed",
                name="ragindexationstate",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rag_indexation_jobs_course_id", "rag_indexation_jobs", ["course_id"])
    op.create_index("ix_rag_indexation_jobs_state", "rag_indexation_jobs", ["state"])

    op.execute(
        f"""
        UPDATE courses
        SET rag_collection_id = '{DEFAULT_COURSE_RAG_COLLECTION_ID}'
        WHERE id = '{DEFAULT_COURSE_ID}'
          AND (rag_collection_id IS NULL OR rag_collection_id = '')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_rag_indexation_jobs_state", table_name="rag_indexation_jobs")
    op.drop_index("ix_rag_indexation_jobs_course_id", table_name="rag_indexation_jobs")
    op.drop_table("rag_indexation_jobs")
    op.execute("DROP TYPE ragindexationstate")
