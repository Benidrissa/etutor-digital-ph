"""Reset stuck course creation_step values for failed/stale tasks

Revision ID: bad7400491c8
Revises: 0d1135672916
Create Date: 2026-04-08 16:30:00.000000

Resets courses where creation_step is stuck in a transient state due to
task crashes or event-loop failures that prevented on_failure handlers from
running:
  - creation_step='indexing'  → 'generated'  (allows re-triggering indexation)
  - creation_step='generating' → 'info'       (allows re-triggering syllabus gen)

Only resets courses where the Celery task is not actively running.
Since we cannot query Celery from inside a migration, we reset all such
courses conservatively — a running task will simply re-set the step to
its terminal value upon completion.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bad7400491c8"
down_revision: str | None = "0d1135672916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE courses
        SET creation_step = 'generated'
        WHERE creation_step = 'indexing'
          AND status = 'draft'
        """
    )
    op.execute(
        """
        UPDATE courses
        SET creation_step = 'info'
        WHERE creation_step = 'generating'
          AND status = 'draft'
        """
    )


def downgrade() -> None:
    pass
