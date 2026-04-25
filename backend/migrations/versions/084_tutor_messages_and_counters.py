"""Tutor: durable per-message store + non-destructive compaction counters (#1978).

Revision ID: 084
Revises: 083
Create Date: 2026-04-25

Three defects fixed by this migration:

1. Compaction was destructive — old messages were dropped from
   ``tutor_conversations.messages`` once a conversation crossed the trigger.
   This migration introduces ``tutor_messages``: one row per turn, immune to
   compaction, so the user can scroll back to message #1 forever.

2. Daily-limit counter was computed as ``len(messages where role=user)`` and
   shrank when compaction truncated the JSON array — making "messages
   restants" oscillate. We add ``user_messages_sent`` (increment-only) on
   ``tutor_conversations`` and the service code sums it instead.

3. Sidebar thread count was ``len(messages)`` — it shrank from 25 to 5 the
   moment compaction ran. We add ``total_messages`` (increment-only) so the
   UI count is monotonic per conversation.

We also add ``compacted_through_position`` so compaction can mark the high-
water mark of summarised messages without mutating the messages array.

Forward-only with IF NOT EXISTS guards so partial-retry deploys are safe.
"""

from alembic import op

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tutor_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES tutor_conversations(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            extra JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tutor_messages_conversation_id "
        "ON tutor_messages (conversation_id);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_tutor_messages_conversation_position "
        "ON tutor_messages (conversation_id, position);"
    )

    op.execute(
        """
        ALTER TABLE tutor_conversations
            ADD COLUMN IF NOT EXISTS user_messages_sent INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS total_messages INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS compacted_through_position INTEGER NOT NULL DEFAULT 0;
        """
    )

    # Backfill counters from the existing JSON array. For already-compacted
    # rows we add a best-effort estimate of what was lost (using the previous
    # default summarize_up_to=15) so the daily counter doesn't suddenly drop
    # for users who already crossed the old trigger today.
    op.execute(
        """
        UPDATE tutor_conversations
        SET total_messages = COALESCE(jsonb_array_length(messages::jsonb), 0)
                             + CASE WHEN compacted_at IS NOT NULL THEN 30 ELSE 0 END,
            user_messages_sent = COALESCE((
                SELECT COUNT(*) FROM jsonb_array_elements(messages::jsonb) AS m
                WHERE m->>'role' = 'user'
            ), 0)
            + CASE WHEN compacted_at IS NOT NULL THEN 15 ELSE 0 END,
            compacted_through_position = CASE WHEN compacted_at IS NOT NULL THEN 30 ELSE 0 END
        WHERE messages IS NOT NULL;
        """
    )

    # Backfill tutor_messages rows from the JSON array. Stable ordering:
    # use the array index from `WITH ORDINALITY` so positions match the
    # in-memory order Claude already saw. Already-compacted/dropped messages
    # are unrecoverable (that's the bug we're fixing forward).
    op.execute(
        """
        INSERT INTO tutor_messages (conversation_id, position, role, content, extra, created_at)
        SELECT
            c.id,
            (idx - 1)::int + COALESCE(c.compacted_through_position, 0) AS position,
            COALESCE(m->>'role', 'user') AS role,
            COALESCE(m->>'content', '') AS content,
            CASE
                WHEN (m::jsonb - 'role' - 'content') = '{}'::jsonb THEN NULL
                ELSE (m::jsonb - 'role' - 'content')
            END AS extra,
            now()
        FROM tutor_conversations c,
             jsonb_array_elements(c.messages::jsonb) WITH ORDINALITY AS m(m, idx)
        WHERE c.messages IS NOT NULL
          AND jsonb_array_length(c.messages::jsonb) > 0
        ON CONFLICT (conversation_id, position) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tutor_conversations
            DROP COLUMN IF EXISTS compacted_through_position,
            DROP COLUMN IF EXISTS total_messages,
            DROP COLUMN IF EXISTS user_messages_sent;
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_tutor_messages_conversation_position;")
    op.execute("DROP INDEX IF EXISTS ix_tutor_messages_conversation_id;")
    op.execute("DROP TABLE IF EXISTS tutor_messages;")
