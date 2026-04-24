"""Add ``figure_kind`` column to ``source_images``.

Revision ID: 080
Revises: 079
Create Date: 2026-04-22

Per issue #1844 (epic #1819, Phase 2 slice 2). Stores the Claude-Vision
classification of each figure — ``clean_flowchart``, ``chart``, ``table``,
``photo``, ``photo_with_callouts``, ``formula``, ``micrograph``,
``decorative``, or ``complex_diagram``. Later slices (3+) use this to
route figures through different translation strategies (SVG re-derive,
raster+overlay, caption-only, etc.).

Stored as ``Text`` (not an enum) so we can add new kinds in later slices
without another migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_images",
        sa.Column("figure_kind", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_images", "figure_kind")
