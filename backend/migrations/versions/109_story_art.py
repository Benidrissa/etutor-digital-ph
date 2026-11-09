"""Add story_art: generated character poses and place backdrops per course (#2675).

Story mode plays as a cartoon (#2672). Each course has one cast and one set of
places (the course bible, migration 108), and this table holds their art: one
row per ``(course_id, kind, key, pose)``.

* ``kind`` ``character``: ``key`` is a cast id or ``hero:<variant>``; ``pose``
  is ``idle``, ``talk``, ``happy`` or ``think``.
* ``kind`` ``place``: ``key`` is a place id; ``pose`` is ``backdrop``.

``image_data`` is a WebP (characters with alpha). ``look_digest`` names the
look it was drawn from and ``art_version`` the prompts' version, so a changed
look or a new version is redrawn. ``status`` is ``ready`` or ``failed`` (with
``error``); a transient failure records ``failed_runs`` and ``retry_after``,
when a later run may try again. Plain strings with CHECK constraints rather
than PG enums, so a new pose never needs an enum migration.

The upgrade is additive. The downgrade drops the table: the art is generated
and regenerates on demand.

Revision ID: 109_story_art
Revises: 108_story_course_bible
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "109_story_art"
down_revision = "108_story_course_bible"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_art",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("pose", sa.String(16), nullable=False),
        sa.Column("look_digest", sa.String(64), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("art_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failed_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("course_id", "kind", "key", "pose", name="uq_story_art_course_item"),
        sa.CheckConstraint("kind IN ('character', 'place')", name="ck_story_art_kind"),
        sa.CheckConstraint(
            "pose IN ('idle', 'talk', 'happy', 'think', 'backdrop')", name="ck_story_art_pose"
        ),
        sa.CheckConstraint("status IN ('ready', 'failed')", name="ck_story_art_status"),
    )


def downgrade() -> None:
    op.drop_table("story_art")
