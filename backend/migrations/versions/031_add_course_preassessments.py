"""add course_preassessments table

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
    op.create_table(
        "course_preassessments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("preassessment_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("questions", JSONB, nullable=False),
        sa.Column("answer_key", JSONB, nullable=False),
        sa.Column("question_levels", JSONB, nullable=False),
        sa.Column("time_limit_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("retake_cooldown_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("instructions_fr", sa.Text(), nullable=True),
        sa.Column("instructions_en", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", name="uq_course_preassessments_course_id"),
    )
    op.create_index(
        "ix_course_preassessments_course_id",
        "course_preassessments",
        ["course_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_course_preassessments_course_id", table_name="course_preassessments")
    op.drop_table("course_preassessments")
