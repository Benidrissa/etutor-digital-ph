"""add creation_step to courses

Revision ID: 038
Revises: 037
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "creation_step",
            sa.String(20),
            server_default="upload",
            nullable=False,
        ),
    )

    op.execute("UPDATE courses SET creation_step = 'published' WHERE status = 'published'")

    op.execute(
        """
        UPDATE courses
        SET creation_step = 'indexed'
        WHERE status = 'draft'
          AND creation_step = 'upload'
          AND id IN (
              SELECT DISTINCT source::uuid
              FROM document_chunks
              JOIN courses c2 ON c2.rag_collection_id = document_chunks.source
              WHERE c2.status = 'draft'
          )
        """
    )

    op.execute(
        """
        UPDATE courses
        SET creation_step = 'generated'
        WHERE status = 'draft'
          AND creation_step = 'upload'
          AND module_count > 0
        """
    )


def downgrade() -> None:
    op.drop_column("courses", "creation_step")
