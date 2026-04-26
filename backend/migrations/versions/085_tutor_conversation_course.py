"""Tutor: per-conversation course_id (regression #YRyXI).

Revision ID: 085
Revises: 084
Create Date: 2026-04-26

The chat panel persisted the active course in a single global ``localStorage``
key, so switching course in one thread bled into every other thread. The
backend made it worse: ``tutor_conversations`` only stored ``module_id``,
forcing the API to re-resolve the course on every request from whatever the
client currently happened to be sending. This migration adds a durable
``course_id`` column so each conversation owns its course.

Backfill: where the conversation has a module, copy the module's course_id.
Conversations without a module remain NULL and will be filled on the next
user message.

Forward-only with IF NOT EXISTS guards so partial-retry deploys are safe.
"""

from alembic import op

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tutor_conversations
            ADD COLUMN IF NOT EXISTS course_id UUID
                REFERENCES courses(id) ON DELETE SET NULL;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tutor_conversations_course_id "
        "ON tutor_conversations (course_id);"
    )

    op.execute(
        """
        UPDATE tutor_conversations tc
           SET course_id = m.course_id
          FROM modules m
         WHERE tc.module_id = m.id
           AND tc.course_id IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tutor_conversations_course_id;")
    op.execute("ALTER TABLE tutor_conversations DROP COLUMN IF EXISTS course_id;")
