"""Add unit_type and books_sources columns to module_units

Revision ID: 023_add_unit_type_books_sources
Revises: 0d1135672916
Create Date: 2026-04-04 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023_add_unit_type_books_sources"
down_revision: str | None = "0d1135672916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='module_units' AND column_name='unit_type'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "module_units",
            sa.Column("unit_type", sa.String(20), server_default="lesson", nullable=False),
        )

    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='module_units' AND column_name='books_sources'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "module_units",
            sa.Column("books_sources", sa.JSON(), nullable=True),
        )

    op.execute("""
        UPDATE module_units
        SET unit_type = CASE
            WHEN unit_number LIKE '%.Q' THEN 'quiz'
            WHEN unit_number LIKE '%.C' THEN 'case-study'
            ELSE 'lesson'
        END
        WHERE unit_type = 'lesson'
          AND (unit_number LIKE '%.Q' OR unit_number LIKE '%.C')
    """)


def downgrade() -> None:
    op.drop_column("module_units", "books_sources")
    op.drop_column("module_units", "unit_type")
