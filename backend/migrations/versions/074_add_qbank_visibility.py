"""Add visibility to question_banks; make organization_id nullable.

Revision ID: 074
Revises: 073
Create Date: 2026-04-20

Adds a ``visibility`` enum column (``public`` | ``org_restricted``) to
``question_banks`` so platform admins can publish banks accessible to
every authenticated user without requiring org membership (#1782).

Existing banks default to ``org_restricted`` (no behaviour change).
``organization_id`` is made nullable because public banks belong to no
organisation; a CHECK constraint enforces that org-restricted banks
always carry an ``organization_id``.
"""

import sqlalchemy as sa
from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None

VISIBILITY_ENUM_NAME = "qbankvisibility"
CONSTRAINT_NAME = "ck_qbank_org_required_for_org_restricted"


def upgrade() -> None:
    visibility_enum = sa.Enum("public", "org_restricted", name=VISIBILITY_ENUM_NAME)
    visibility_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "question_banks",
        sa.Column(
            "visibility",
            sa.Enum("public", "org_restricted", name=VISIBILITY_ENUM_NAME, create_type=False),
            server_default="org_restricted",
            nullable=False,
        ),
    )

    op.alter_column("question_banks", "organization_id", nullable=True)

    op.create_check_constraint(
        CONSTRAINT_NAME,
        "question_banks",
        "organization_id IS NOT NULL OR visibility = 'public'",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "question_banks", type_="check")

    # Restore NOT NULL — set any public banks' org to NULL first isn't needed
    # because downgrade implies no public banks exist (or data loss is accepted).
    op.alter_column("question_banks", "organization_id", nullable=False)

    op.drop_column("question_banks", "visibility")

    sa.Enum(name=VISIBILITY_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
