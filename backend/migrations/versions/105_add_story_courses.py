"""Add story_courses table for the story-course/1 course file format.

Revision ID: 105_add_story_courses
Revises: 104_add_ai_usage_events
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "105_add_story_courses"
down_revision = "104_add_ai_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_courses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column(
            "course_id",
            UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("course_label", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("title", JSONB(), nullable=False),
        sa.Column("languages", JSONB(), nullable=False),
        sa.Column("format_version", sa.String(40), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "published", "archived", name="story_course_status_enum"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("is_valid", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("validation_report", JSONB(), nullable=True),
        sa.Column("max_points", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_story_courses_course_week", "story_courses", ["course_id", "week"])
    op.create_index("ix_story_courses_status", "story_courses", ["status"])


def downgrade() -> None:
    op.drop_index("ix_story_courses_status", table_name="story_courses")
    op.drop_index("ix_story_courses_course_week", table_name="story_courses")
    op.drop_table("story_courses")
    sa.Enum(name="story_course_status_enum").drop(op.get_bind(), checkfirst=True)
