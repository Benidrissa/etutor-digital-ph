"""Add courses, user_course_enrollments tables and modules.course_id FK

Revision ID: 014_add_courses_and_enrollment_tables
Revises: 013_add_learner_memory_table
Create Date: 2026-04-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_add_courses_and_enrollment_tables"
down_revision: str | None = "013_add_learner_memory_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("languages", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("estimated_hours", sa.Integer(), server_default="20"),
        sa.Column("module_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(), server_default="draft"),
        sa.Column("cover_image_url", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rag_collection_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_courses_slug", "courses", ["slug"], unique=True)
    op.create_index("idx_courses_status", "courses", ["status"])
    op.create_index("idx_courses_domain", "courses", ["domain"])

    op.create_table(
        "user_course_enrollments",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("status", sa.String(), server_default="active"),
        sa.Column("completion_pct", sa.Float(), server_default="0.0"),
        sa.PrimaryKeyConstraint("user_id", "course_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
    )
    op.create_index("idx_enrollment_user_id", "user_course_enrollments", ["user_id"])
    op.create_index("idx_enrollment_course_id", "user_course_enrollments", ["course_id"])
    op.create_index("idx_enrollment_status", "user_course_enrollments", ["status"])

    op.add_column(
        "modules",
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_modules_course_id", "modules", ["course_id"])
    op.create_foreign_key(
        "fk_modules_course_id",
        "modules",
        "courses",
        ["course_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_modules_course_id", "modules", type_="foreignkey")
    op.drop_index("idx_modules_course_id", table_name="modules")
    op.drop_column("modules", "course_id")
    op.drop_table("user_course_enrollments")
    op.drop_table("courses")
