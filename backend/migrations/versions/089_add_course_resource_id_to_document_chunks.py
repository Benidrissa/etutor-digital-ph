"""Add course_resource_id FK to document_chunks (#2186).

Revision ID: 089
Revises: 088
Create Date: 2026-05-03

The citation rewriter at ``backend/app/domain/services/citation_formatter.py``
currently has to *back-derive* which PDF a given chunk came from by
substring-matching ``DocumentChunk.content`` against each
``CourseResource.raw_text`` (#2178/#2179) and using
``SourceImage.surrounding_text`` as a tiebreaker (#2181). The fingerprint
heuristics top out around 25-37% per-PDF resolution on real multi-PDF
courses because PDFs covering overlapping subject matter share text.

The information *was* known at ingest time — both ingestion paths
(``rag_indexation.py`` DB-resources path line 228, PDF-on-disk path line
290) have the originating ``CourseResource`` in scope. It was simply
discarded when the chunker stored ``source = rag_collection_id``.

This migration adds a nullable FK column so that:

- New chunks from this point on land with ``course_resource_id`` populated
  directly at ingest — read-side resolution becomes a single indexed JOIN
  and is exact, not heuristic.
- Existing chunks keep ``course_resource_id = NULL`` and continue to use
  the existing fingerprint-match fallback path. A separate one-shot
  backfill script can be run per-environment to populate them after deploy.

ON DELETE SET NULL keeps the index safe if a CourseResource is later
removed (e.g. PDF replaced); chunks fall back to the heuristic path.

Forward-only: ``downgrade`` drops the column + index. Reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "089"
down_revision: str | None = "088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "course_resource_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("course_resources.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_chunks_course_resource_id",
        "document_chunks",
        ["course_resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_course_resource_id", table_name="document_chunks")
    op.drop_column("document_chunks", "course_resource_id")
