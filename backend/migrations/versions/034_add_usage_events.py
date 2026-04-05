"""add usage_events table

Revision ID: 034
Revises: 032
Create Date: 2026-04-05

"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "034"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_name", sa.String(100), nullable=False),
        sa.Column("properties", JSONB, nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_usage_events_event_name", "usage_events", ["event_name"])
    op.create_index("ix_usage_events_event_created", "usage_events", ["event_name", "created_at"])
    op.create_index("ix_usage_events_user_created", "usage_events", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_user_created", table_name="usage_events")
    op.drop_index("ix_usage_events_event_created", table_name="usage_events")
    op.drop_index("ix_usage_events_event_name", table_name="usage_events")
    op.drop_table("usage_events")
