"""add generation_task_id, question_count, sources_cited, notes to course_preassessments

Revision ID: 032
Revises: 031
Create Date: 2026-04-05

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_preassessments",
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "course_preassessments",
        sa.Column("sources_cited", JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "course_preassessments",
        sa.Column("generation_task_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "course_preassessments",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("course_preassessments", "notes")
    op.drop_column("course_preassessments", "generation_task_id")
    op.drop_column("course_preassessments", "sources_cited")
    op.drop_column("course_preassessments", "question_count")
