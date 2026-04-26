"""Add module_unit_id FK to generated_content; replace JSON unit_id join.

Revision ID: 086
Revises: 085
Create Date: 2026-04-26

Renumbered from 084 → 086: the tutor message store (#1978, revision 084)
and tutor course_id column (revision 085) merged to dev in parallel.
Linear chain on dev is now: 083 → 084_tutor_messages →
085_tutor_conversation_course → 086_module_unit_id.

The link between ``generated_content`` (cached lessons / quizzes / case
studies) and the ``module_units`` row that defines the unit's title and
description was previously a JSON-string match
(``content->>'unit_id' = '1.3'``). That made every read at-best a string
join across an unindexed JSON expression, and at-worst a way for a
content row to silently outlive a unit-title edit — leaving the lesson
showing module-level text under the wrong unit (issue #2007).

This migration:

1. Adds ``generated_content.module_unit_id`` UUID FK to
   ``module_units.id`` with ``ON DELETE CASCADE``. The column is
   nullable because flashcards and summative quizzes are intentionally
   module-scoped (no unit binding).
2. Backfills ``module_unit_id`` from the legacy ``content->>'unit_id'``
   value by joining on ``(module_id, unit_number)``.
3. Deletes orphan rows whose JSON ``unit_id`` no longer matches any
   current unit. These are precisely the stale-cache entries causing
   the live mismatches; deleting them lets the next user access
   regenerate clean, unit-bound content.
4. Replaces ``idx_unique_lesson_per_unit`` (the JSON-keyed partial
   unique index) with two cleaner partial indexes:
     - ``idx_unique_content_per_module_unit`` keyed on the FK for
       unit-scoped content;
     - ``idx_unique_module_scoped_content`` keyed on
       ``(module_id, content_type, language, level, country_context,
       content->>'unit_id')`` for module-scoped content (flashcards +
       summative quizzes whose JSON unit_id is the literal "summative").

Step 5 — stripping ``unit_id`` from the JSON for unit-scoped rows — is
intentionally deferred to a follow-up migration, after this code is
fully deployed and verified. That guarantees fall-back compatibility if
any reader was missed.

Forward-only: downgrade is intentionally not implemented (rollback via
code revert + manual ALTER if ever needed).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "086"
down_revision: str | None = "085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the FK column (nullable for module-scoped content).
    op.add_column(
        "generated_content",
        sa.Column(
            "module_unit_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("module_units.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_generated_content_module_unit_id",
        "generated_content",
        ["module_unit_id"],
    )

    bind = op.get_bind()

    # 2. Backfill from JSON unit_id → module_units.id.
    backfill = bind.execute(
        sa.text(
            """
            UPDATE generated_content gc
            SET module_unit_id = mu.id
            FROM module_units mu
            WHERE gc.module_id = mu.module_id
              AND gc.content->>'unit_id' = mu.unit_number
              AND gc.content->>'unit_id' IS NOT NULL
              AND gc.content->>'unit_id' NOT IN ('', 'summative')
              AND gc.module_unit_id IS NULL
            """
        )
    )
    print(f"[084] Backfilled module_unit_id on {backfill.rowcount} row(s)")

    # 3. Delete orphan rows: had a non-summative JSON unit_id but no
    # matching module_units row. These are the stale-cache rows
    # producing observable topic mismatches.
    #
    # Repoint media tables (generated_images, generated_audio) that
    # reference generated_content via lesson_id. The model declares
    # ondelete="SET NULL" but the actual FK shape on prod can predate
    # that declaration, so we explicitly NULL them out before the DELETE.
    # Idempotent and safe regardless of the live FK definition.
    bind.execute(
        sa.text(
            """
            UPDATE generated_images
            SET lesson_id = NULL
            WHERE lesson_id IN (
                SELECT id FROM generated_content
                WHERE content->>'unit_id' IS NOT NULL
                  AND content->>'unit_id' NOT IN ('', 'summative')
                  AND module_unit_id IS NULL
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE generated_audio
            SET lesson_id = NULL
            WHERE lesson_id IN (
                SELECT id FROM generated_content
                WHERE content->>'unit_id' IS NOT NULL
                  AND content->>'unit_id' NOT IN ('', 'summative')
                  AND module_unit_id IS NULL
            )
            """
        )
    )
    orphans = bind.execute(
        sa.text(
            """
            DELETE FROM generated_content
            WHERE content->>'unit_id' IS NOT NULL
              AND content->>'unit_id' NOT IN ('', 'summative')
              AND module_unit_id IS NULL
            """
        )
    )
    print(f"[086] Deleted {orphans.rowcount} orphan generated_content row(s)")

    # 4. Swap the unique indexes.
    op.execute("DROP INDEX IF EXISTS idx_unique_lesson_per_unit")

    op.execute(
        """
        CREATE UNIQUE INDEX idx_unique_content_per_module_unit
        ON generated_content (
            module_unit_id,
            content_type,
            language,
            level,
            country_context
        )
        WHERE module_unit_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX idx_unique_module_scoped_content
        ON generated_content (
            module_id,
            content_type,
            language,
            level,
            country_context,
            (content->>'unit_id')
        )
        WHERE module_unit_id IS NULL
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration; rollback via code revert and redeploy.")
