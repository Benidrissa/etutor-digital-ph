"""Add ``caption_fr`` and ``caption_en`` columns to ``source_images``.

Revision ID: 078
Revises: 077
Create Date: 2026-04-21

Per issue #1820 (epic #1819) — bilingual figure translation Phase 1.

Today ``source_images`` has a single ``caption`` column populated from the
raw English PDF text, plus ``alt_text_fr`` / ``alt_text_en`` columns that
have existed since earlier migrations but are NULL. The serialisers in
``lesson_service`` / ``tutor_service`` fake the ``caption_fr`` /
``caption_en`` API fields by duplicating the English ``caption`` into
both, so FR learners see English captions under every figure.

This migration adds persistent locale columns so translated captions can
be stored alongside the English original. All three locale surfaces
(``caption``, ``caption_fr``, ``caption_en``) coexist: ``caption`` remains
the raw-from-PDF value used as a fallback when translations haven't run
yet; the new columns hold the translated text once Phase 1's translator
and backfill task populate them.
"""

import sqlalchemy as sa
from alembic import op

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_images",
        sa.Column("caption_fr", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_images",
        sa.Column("caption_en", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_images", "caption_en")
    op.drop_column("source_images", "caption_fr")
