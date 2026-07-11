"""Add ai_usage_events ledger table (#2629).

Revision ID: 104_add_ai_usage_events
Revises: 103_add_update_api_key_audit_action
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "104_add_ai_usage_events"
down_revision = "103_add_update_api_key_audit_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("feature", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "course_id",
            UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("api_key_source", sa.String(10), nullable=False, server_default="platform"),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("images_count", sa.Integer(), nullable=True),
        sa.Column("audio_seconds", sa.Integer(), nullable=True),
        sa.Column("characters", sa.Integer(), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cost_cents", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("cost_estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_ai_usage_events_created", "ai_usage_events", ["created_at"])
    op.create_index(
        "ix_ai_usage_events_feature_created", "ai_usage_events", ["feature", "created_at"]
    )
    op.create_index("ix_ai_usage_events_user_created", "ai_usage_events", ["user_id", "created_at"])
    op.create_index(
        "ix_ai_usage_events_provider_created", "ai_usage_events", ["provider", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_provider_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_user_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_feature_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_created", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
