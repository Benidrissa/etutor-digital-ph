"""Rename module_media.metadata to media_metadata.

The column name 'metadata' is reserved by SQLAlchemy's Declarative API.

Revision ID: 027_rename_module_media_metadata_column
Revises: 026_refactor_taxonomy_to_lookup_table
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "027_rename_module_media_metadata_column"
down_revision: str | None = "026_refactor_taxonomy_to_lookup_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE module_media RENAME COLUMN metadata TO media_metadata")


def downgrade() -> None:
    op.execute("ALTER TABLE module_media RENAME COLUMN media_metadata TO metadata")
