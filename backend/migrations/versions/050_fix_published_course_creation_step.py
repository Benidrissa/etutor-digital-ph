"""Fix creation_step for published courses with incorrect state

Revision ID: 050
Revises: 049
Create Date: 2026-04-08 17:00:00.000000

Fixes courses where status='published' but creation_step is not 'published',
which can happen when a user clicks "Generate structure" on an already-published
course, setting creation_step='generating' and corrupting the wizard state.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE courses
        SET creation_step = 'published'
        WHERE status = 'published'
          AND creation_step != 'published'
        """
    )


def downgrade() -> None:
    pass
