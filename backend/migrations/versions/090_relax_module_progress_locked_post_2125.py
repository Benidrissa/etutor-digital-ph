"""Backfill: relax 'locked' module progress rows to 'not_started' (#2218).

Revision ID: 090
Revises: 089
Create Date: 2026-05-04

Follow-up to migration 088. PR #2125 removed sequential module gating, and
088 backfilled legacy ``'locked'`` rows to ``'not_started'``. However,
``enrollment_helper.enroll_user_in_course()`` was missed and continued to
write ``status='locked'`` for every non-first module at enrollment time,
re-introducing the same locked rows that 088 had just cleaned up.

PR #2219 fixes the write path. This migration relaxes any ``'locked'``
rows that the buggy enrollment path persisted between the deploy of #2125
(2026-04-30) and the deploy of #2219, so the database matches the new
"every module accessible after enrollment" semantics.

Forward-only: downgrade is a no-op. Reversing ``'not_started'`` →
``'locked'`` would require knowing which rows had been buggy-locked vs.
intentionally locked, and that distinction is no longer meaningful.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "090"
down_revision: str | None = "089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text("UPDATE user_module_progress SET status = 'not_started' WHERE status = 'locked'")
    )
    print(f"[090] Relaxed {result.rowcount} 'locked' module progress row(s) to 'not_started'")


def downgrade() -> None:
    pass
