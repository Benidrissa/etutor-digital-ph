"""Backfill synthetic email for phone-only users.

Revision ID: 073
Revises: 072
Create Date: 2026-04-20

Phone-only users (email IS NULL, phone_number IS NOT NULL) have no email,
which prevents them from being added to organizations via the add-member
endpoint that looks users up by email.  Assigning a deterministic synthetic
address <phone>@sira.app gives every user a stable, unique email without
requiring them to own a real inbox.  The EmailService._is_synthetic() guard
ensures no mail is ever dispatched to these addresses.
"""

from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET email = phone_number || '@sira.app'
        WHERE email IS NULL
          AND phone_number IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET email = NULL
        WHERE email LIKE '%@sira.app'
          AND phone_number IS NOT NULL
        """
    )
