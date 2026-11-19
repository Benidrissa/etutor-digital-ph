"""Add the story asset catalogue: the course's own pictures a module story may show.

#2709. ``story_asset_catalogues`` holds, per module, the catalogue of course
figures and lesson illustrations built in code before any model call, the
admin's pins and exclusions, and the binding of the story's props to it. See
``app/domain/models/story_asset.py``.

The upgrade is additive and nothing reads the table until a catalogue is
built. The downgrade drops it: the catalogue is built again on demand.

Revision ID: 113_story_asset_catalogues
Revises: 112_story_prop_library
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "113_story_asset_catalogues"
down_revision = "112_story_prop_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_asset_catalogues",
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("story_asset_catalogues")
