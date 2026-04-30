"""Backfill: relax legacy 'locked' module progress rows to 'not_started' (#2125).

Revision ID: 088
Revises: 087
Create Date: 2026-04-30

Sequential module gating was removed per issue #2125 — once a learner enrolls
in a course, every module is immediately accessible. The read-side default for
modules without a ``user_module_progress`` row was flipped from ``'locked'`` to
``'not_started'``. This migration relaxes any rows that the legacy
``_unlock_next_module`` path persisted as ``'locked'`` so they match the new
semantics on next read.

Forward-only: downgrade is a no-op. Reversing ``not_started`` → ``locked``
would require recomputing which rows had been locked in the legacy ordering,
and that information is no longer business-meaningful.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "088"
down_revision: str | None = "087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "UPDATE user_module_progress "
            "SET status = 'not_started' "
            "WHERE status = 'locked'"
        )
    )
    print(f"[088] Relaxed {result.rowcount} 'locked' module progress row(s) to 'not_started'")


def downgrade() -> None:
    pass
