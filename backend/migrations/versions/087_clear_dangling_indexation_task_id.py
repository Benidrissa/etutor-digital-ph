"""Backfill: clear dangling courses.indexation_task_id pointers (#2085).

Revision ID: 087
Revises: 086
Create Date: 2026-04-28

The Celery task lifecycle didn't always clear ``indexation_task_id``
on terminal exits (success / raised exception / worker SIGKILL),
leaving stale references that wedge the AI-course-creation wizard's
"Indexation RAG" step on the next page reload. The code-side fix
(``RAGTask`` / ``ImageIndexTask`` lifecycle callbacks owning the
state transition) prevents future leaks; this migration clears
pointers already in the broken state so existing wedged courses heal
on first poll after deploy.

Conservative cleanup: only nulls pointers on courses where
``creation_step`` proves the task can't be live. Skips ``'indexing'``
(an actively running text+image indexation) and ``'published'`` (a
``reindex_course_images`` task can legitimately run there). The
read-side guard added in this PR catches the ``'published'`` cases on
next poll.

Forward-only: downgrade is a no-op (the cleared values were dead
task IDs that had no useful state to restore).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "087"
down_revision: str | None = "086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            UPDATE courses SET indexation_task_id = NULL
            WHERE indexation_task_id IS NOT NULL
              AND creation_step IN ('generated', 'indexed')
            """
        )
    )
    print(
        f"[087] Cleared {result.rowcount} dangling indexation_task_id pointer(s)"
    )


def downgrade() -> None:
    pass
