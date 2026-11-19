"""Record the kind of every story model call in the AI usage ledger (#2735).

``ai_usage_events`` gains ``call_kind`` (what the call was for: ``bible``,
``plan``, ``pack``, ``story``, ``rally``...; for a repair, the kind it repairs)
and ``is_repair``. A plain string, no enum, as ``feature`` is. No backfill: rows
written before this migration keep NULL / false. An index on
``(module_id, created_at)`` serves the story cost report; it is built
CONCURRENTLY, outside the migration transaction, so writes to the ledger are
not blocked.

Revision ID: 115_ai_usage_call_kind
Revises: 114_story_stock_art
"""

import sqlalchemy as sa
from alembic import op

revision = "115_ai_usage_call_kind"
down_revision = "114_story_stock_art"
branch_labels = None
depends_on = None

_INDEX = "ix_ai_usage_events_module_created"


def upgrade() -> None:
    op.add_column("ai_usage_events", sa.Column("call_kind", sa.String(30), nullable=True))
    op.add_column(
        "ai_usage_events",
        sa.Column("is_repair", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON ai_usage_events (module_id, created_at)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
    op.drop_column("ai_usage_events", "is_repair")
    op.drop_column("ai_usage_events", "call_kind")
