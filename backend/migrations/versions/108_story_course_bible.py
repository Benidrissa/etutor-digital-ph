"""Add story_course_bibles: one story cast and set of places per course (#2674).

Story mode tells every module of a course with the same characters in the
same places, so their art (#2675) is made once per course. The bible is
written by one model call the first time a story of the course is needed and
reused by every module story after that.

One row per course: ``content`` (JSONB: cast, places, facts, missions), its
``digest`` (sha256 of the canonical JSON), the ``model`` that wrote it and
timestamps. Deleting the course deletes its bible.

The upgrade is additive; module stories built before it carry no bible and
are made stale by the generator version they record, not by this migration.
The downgrade drops the table.

Revision ID: 108_story_course_bible
Revises: 107_story_module_binding
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "108_story_course_bible"
down_revision = "107_story_module_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_course_bibles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "course_id",
            UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("story_course_bibles")
