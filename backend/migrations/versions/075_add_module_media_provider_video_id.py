"""Add provider_video_id to module_media for HeyGen video summaries.

Revision ID: 075
Revises: 074
Create Date: 2026-04-21

Part of #1791 (HeyGen-backed 3-min lesson summary videos). When a
video summary generation request is dispatched, the async API call to
HeyGen returns a ``video_id`` that we must retain so the completion
webhook can match the push payload back to the pending ``ModuleMedia``
row. ``media_type`` is already ``String(50)`` so no enum alteration is
needed; ``MediaType.video_summary`` already exists in the model enum.

A partial unique index enforces one-to-one correspondence between
HeyGen videos and ``ModuleMedia`` rows, which keeps webhook handling
idempotent without requiring the webhook handler to do its own
collision check.
"""

import sqlalchemy as sa
from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "module_media",
        sa.Column(
            "provider_video_id",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ix_module_media_provider_video_id "
        "ON module_media (provider_video_id) "
        "WHERE provider_video_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_module_media_provider_video_id")
    op.drop_column("module_media", "provider_video_id")
