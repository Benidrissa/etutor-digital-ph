"""Raise qbank_question_banks.time_per_question_sec server_default 25 → 60.

Revision ID: 071
Revises: 070
Create Date: 2026-04-19

Migration 067 created the column with server_default="25". The Python
model default was bumped to 60 in PR #1691 but no migration altered the
column, so rows inserted via direct SQL or via code paths that don't
pass an explicit value were still getting 25. This migration:

- Alters the column server_default from "25" to "60" so future inserts
  without an explicit value land on 60.
- Backfills any existing row with time_per_question_sec = 25 to 60. We
  only touch the legacy-default value; banks admins have explicitly set
  to some other timer (e.g. 45 or 90) are left alone.

Part of issue #1714.
"""

import sqlalchemy as sa
from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "qbank_question_banks",
        "time_per_question_sec",
        server_default=sa.text("60"),
    )
    op.execute(
        "UPDATE qbank_question_banks SET time_per_question_sec = 60 "
        "WHERE time_per_question_sec = 25"
    )


def downgrade() -> None:
    op.alter_column(
        "qbank_question_banks",
        "time_per_question_sec",
        server_default=sa.text("25"),
    )
    # Intentionally not reverting UPDATE: we cannot distinguish rows
    # touched by the backfill from rows the admin later set to 60.
