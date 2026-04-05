"""add course_preassessments table and preassessment_enabled to courses

Revision ID: 031
Revises: 030
Create Date: 2026-04-05

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("preassessment_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "course_preassessments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "course_id",
            sa.UUID(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.String(10), nullable=False, server_default="fr"),
        sa.Column("questions", JSONB, nullable=False, server_default="[]"),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sources_cited", JSONB, nullable=False, server_default="[]"),
        sa.Column("generated_by", sa.String(50), nullable=False, server_default="ai"),
        sa.Column("generation_task_id", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_course_preassessments_course_id",
        "course_preassessments",
        ["course_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_course_preassessments_course_id", table_name="course_preassessments")
    op.drop_table("course_preassessments")
    op.drop_column("courses", "preassessment_enabled")
