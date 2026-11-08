"""Bind story_courses rows to lesson units (per-lesson story mode).

Every lesson unit gets a story mode, generated on demand from that unit's own
lesson and quiz and cached here. A lesson story is keyed by
``(module_unit_id, language)`` and records the ``generated_content`` rows it
was derived from — their ``content_revision`` and a sha256 digest of their
content — so it goes stale when either the lesson or the quiz is regenerated
or edited (an admin's manual edit does not bump the revision).

Every new column is nullable: hand-authored weeks keep all of them null and are
untouched. PostgreSQL treats NULLs as distinct in a unique constraint, so the
``(module_unit_id, language)`` constraint never applies to them.

Revision ID: 106_add_story_unit_binding
Revises: 105_add_story_courses
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "106_add_story_unit_binding"
down_revision = "105_add_story_courses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "story_courses",
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "story_courses",
        sa.Column(
            "module_unit_id",
            UUID(as_uuid=True),
            sa.ForeignKey("module_units.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("story_courses", sa.Column("language", sa.String(2), nullable=True))
    op.add_column(
        "story_courses",
        sa.Column(
            "source_lesson_content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("generated_content.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "story_courses", sa.Column("source_lesson_revision", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "story_courses",
        sa.Column(
            "source_quiz_content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("generated_content.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "story_courses", sa.Column("source_quiz_revision", sa.SmallInteger(), nullable=True)
    )
    op.add_column("story_courses", sa.Column("source_lesson_digest", sa.String(64), nullable=True))
    op.add_column("story_courses", sa.Column("source_quiz_digest", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_story_courses_unit_language", "story_courses", ["module_unit_id", "language"]
    )
    op.create_index("ix_story_courses_module_language", "story_courses", ["module_id", "language"])


def downgrade() -> None:
    op.drop_index("ix_story_courses_module_language", table_name="story_courses")
    op.drop_constraint("uq_story_courses_unit_language", "story_courses", type_="unique")
    op.drop_column("story_courses", "source_quiz_digest")
    op.drop_column("story_courses", "source_lesson_digest")
    op.drop_column("story_courses", "source_quiz_revision")
    op.drop_column("story_courses", "source_quiz_content_id")
    op.drop_column("story_courses", "source_lesson_revision")
    op.drop_column("story_courses", "source_lesson_content_id")
    op.drop_column("story_courses", "language")
    op.drop_column("story_courses", "module_unit_id")
    op.drop_column("story_courses", "module_id")
