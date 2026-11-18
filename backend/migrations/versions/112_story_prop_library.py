"""Add the story prop library: assets rendered from free 3D models, and phrase matches.

Phase A of docs/story-mode-3d-assets.md. ``story_library_assets`` holds the
pictures the asset foundry renders (stickers and close-ups, with licence,
credit and provenance); ``story_prop_matches`` caches what each prop search
phrase matched, or a miss. See ``app/domain/models/story_prop_library.py``.

The upgrade is additive and nothing reads the tables until a library is
imported. The downgrade drops both tables: the library is imported again
from the foundry's output and the matches are recomputed on demand.

Revision ID: 112_story_prop_library
Revises: 111_story_line_audio
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "112_story_prop_library"
down_revision = "111_story_line_audio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_library_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(60), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", JSONB(), nullable=False),
        sa.Column("tags", JSONB(), nullable=False, server_default="[]"),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column("image_large", sa.LargeBinary(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("licence", sa.String(32), nullable=False),
        sa.Column("attribution_required", sa.Boolean(), nullable=False),
        sa.Column("credit", JSONB(), nullable=False),
        sa.Column("source", JSONB(), nullable=False),
        sa.Column("embedding", ARRAY(sa.Float()), nullable=True),
        sa.Column("library_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('sticker', 'closeup')", name="ck_story_library_assets_kind"),
    )
    op.create_table(
        "story_prop_matches",
        sa.Column("query", sa.String(200), primary_key=True),
        sa.Column("prop_kind", sa.String(16), primary_key=True),
        sa.Column(
            "asset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("story_library_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("prop_kind IN ('sticker', 'real')", name="ck_story_prop_matches_kind"),
        sa.CheckConstraint(
            "method IN ('embedding', 'lexical', 'empty')", name="ck_story_prop_matches_method"
        ),
    )


def downgrade() -> None:
    op.drop_table("story_prop_matches")
    op.drop_table("story_library_assets")
