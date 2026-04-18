"""Add visibility column to question_banks.

Revision ID: 070
Revises: 069
Create Date: 2026-04-18

Supports cross-org discovery in the top-level QBank list (#1692). Existing
banks remain org-scoped (default ``org_only``); admins can opt into
``public`` to surface a bank in the authenticated-user cross-org list.
"""

import sqlalchemy as sa
from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "question_banks",
        sa.Column(
            "visibility",
            sa.String(10),
            server_default="org_only",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("question_banks", "visibility")
