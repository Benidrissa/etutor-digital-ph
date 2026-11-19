"""Add the shared story stock art and the seed state (#2714).

``story_stock_art`` holds images shared by every course of a stack (cast roles
and generic places, drawn once, reviewed by a human before use).
``story_art.stock_id`` lets a course's art row adopt one without copying its
bytes. ``story_seed_state`` records which version of the bundled prop library a
stack has imported. ``ck_story_art_pose`` also accepts the two extra poses
(surprised, sad) that only stock may hold.

Additive and nothing changes for existing courses: their rows keep their own
images and ``stock_id`` stays null. The downgrade removes the extra poses (rows
using them are deleted), the column and both tables.

Revision ID: 114_story_stock_art
Revises: 113_story_asset_catalogues
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "114_story_stock_art"
down_revision = "113_story_asset_catalogues"
branch_labels = None
depends_on = None

_POSES = "'idle', 'talk', 'happy', 'think', 'surprised', 'sad', 'backdrop'"
_OLD_POSES = "'idle', 'talk', 'happy', 'think', 'backdrop'"


def upgrade() -> None:
    op.create_table(
        "story_stock_art",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("theme", sa.String(60), nullable=False),
        sa.Column("variant", sa.String(60), nullable=False, server_default=""),
        sa.Column("pack", sa.String(40), nullable=False, server_default="west_africa"),
        sa.Column("pose", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("look", sa.Text(), nullable=True),
        sa.Column("source_course_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source_art_id", UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('character', 'place')", name="ck_story_stock_art_kind"),
        sa.CheckConstraint(f"pose IN ({_POSES})", name="ck_story_stock_art_pose"),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'retired')", name="ck_story_stock_art_status"
        ),
    )
    op.create_index(
        "uq_story_stock_art_slot",
        "story_stock_art",
        ["kind", "theme", "variant", "pack", "pose"],
        unique=True,
        postgresql_where=sa.text("status <> 'retired'"),
    )
    op.create_table(
        "story_seed_state",
        sa.Column("name", sa.String(60), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column(
            "applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "story_art",
        sa.Column(
            "stock_id",
            UUID(as_uuid=True),
            sa.ForeignKey("story_stock_art.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.drop_constraint("ck_story_art_pose", "story_art", type_="check")
    op.create_check_constraint("ck_story_art_pose", "story_art", f"pose IN ({_POSES})")


def downgrade() -> None:
    op.execute("DELETE FROM story_art WHERE pose IN ('surprised', 'sad') OR stock_id IS NOT NULL")
    op.drop_constraint("ck_story_art_pose", "story_art", type_="check")
    op.create_check_constraint("ck_story_art_pose", "story_art", f"pose IN ({_OLD_POSES})")
    op.drop_column("story_art", "stock_id")
    op.drop_table("story_seed_state")
    op.drop_index("uq_story_stock_art_slot", table_name="story_stock_art")
    op.drop_table("story_stock_art")
