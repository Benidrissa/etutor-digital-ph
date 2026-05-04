"""Course Quality Agent: schema for unit-level quality scoring & loop (#2215).

Revision ID: 090
Revises: 089
Create Date: 2026-05-03

After review of an AI-generated course we observed terminology drift —
the same term defined one way in unit 1.1 and differently in unit 2.3.
The Course Quality Agent fixes this gap by scoring each generated unit
on six dimensions, building a canonical course glossary as the
cross-unit source of truth, auto-regenerating failing units (≤ 2
attempts) with the flags fed back as prompt constraints, and surfacing
remaining failures to the admin.

This migration is the structural base. It:

1. ALTERs ``generated_content`` to add per-row quality state
   (``quality_score``, ``quality_status``, ``quality_flags``,
   ``quality_assessed_at``, ``regeneration_attempts``,
   ``last_quality_run_id`` FK, ``content_revision``). The existing
   ``validated`` boolean stays — it becomes the *human-override* flag.
   ``quality_status`` is the agent's state.
2. Creates ``course_quality_runs`` with a partial unique index that
   makes "one active run per course" enforceable at the DB layer (no
   double-clicks queueing duplicates) and an idempotency-key compound
   unique that collapses same-day re-clicks into a no-op.
3. Creates ``unit_quality_assessments`` with full token/cost accounting
   and a back-link to the ``credit_transactions`` row.
4. Creates ``course_glossary_terms`` — the canonical-definition table
   used by the assessor to detect cross-unit terminology drift.
5. Creates ``generated_content_revisions`` so ``force_regenerate`` no
   longer destroys the prior payload (one row per overwrite, full
   pre-image preserved). Lets us roll back regressions.
6. Backfills ``quality_status='manual_override'`` for every existing
   row already locked via ``is_manually_edited=true`` so the very first
   quality run respects admin locks without an extra branch in the
   service code.

Forward-only: ``downgrade`` drops everything; reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "090"
down_revision: str | None = "089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. course_quality_runs.
    op.create_table(
        "course_quality_runs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "course_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("run_kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column(
            "triggered_by_user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("units_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("units_passing", sa.Integer, nullable=False, server_default="0"),
        sa.Column("units_regenerated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("budget_credits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("spent_credits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "course_id", "idempotency_key", name="uq_course_quality_run_idempotency"
        ),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_one_active_run_per_course
          ON course_quality_runs (course_id)
          WHERE status IN ('queued','scoring','regenerating');
        """
    )

    # 2. course_glossary_terms.
    op.create_table(
        "course_glossary_terms",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "course_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("term_normalized", sa.String(160), nullable=False),
        sa.Column("term_display", sa.String(160), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("canonical_definition", sa.Text, nullable=False),
        sa.Column(
            "first_unit_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("module_units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "occurrences",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="auto"),
        sa.Column("consistency_status", sa.String(24), nullable=False, server_default="consistent"),
        sa.Column("drift_details", sa.Text, nullable=True),
        sa.Column(
            "source_citations",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "alt_phrasings",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "course_id", "term_normalized", "language", name="uq_glossary_course_term_lang"
        ),
    )

    # 3. unit_quality_assessments.
    op.create_table(
        "unit_quality_assessments",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("course_quality_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "generated_content_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("generated_content.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "dimension_scores",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "flags",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("cache_read_tokens", sa.Integer, nullable=True),
        sa.Column("cache_write_tokens", sa.Integer, nullable=True),
        sa.Column("cost_cents", sa.Integer, nullable=True),
        sa.Column(
            "credit_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_uqa_genc_created",
        "unit_quality_assessments",
        ["generated_content_id", "created_at"],
    )

    # 4. ALTER generated_content.
    op.add_column("generated_content", sa.Column("quality_score", sa.Numeric(5, 2), nullable=True))
    op.add_column(
        "generated_content",
        sa.Column("quality_status", sa.String(24), nullable=False, server_default="pending"),
    )
    op.add_column(
        "generated_content",
        sa.Column(
            "quality_flags",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "generated_content",
        sa.Column("quality_assessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generated_content",
        sa.Column("regeneration_attempts", sa.SmallInteger, nullable=False, server_default="0"),
    )
    op.add_column(
        "generated_content",
        sa.Column(
            "last_quality_run_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("course_quality_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "generated_content",
        sa.Column("content_revision", sa.SmallInteger, nullable=False, server_default="1"),
    )
    op.create_index("ix_genc_quality_status", "generated_content", ["quality_status"])
    op.create_index("ix_genc_module_quality", "generated_content", ["module_id", "quality_status"])
    op.execute(
        """
        CREATE INDEX ix_genc_quality_flags_gin
          ON generated_content
          USING GIN (quality_flags jsonb_path_ops);
        """
    )

    # 5. Backfill: locked rows go to manual_override.
    op.execute(
        """
        UPDATE generated_content
           SET quality_status = 'manual_override'
         WHERE is_manually_edited = true;
        """
    )

    # 6. generated_content_revisions.
    op.create_table(
        "generated_content_revisions",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "generated_content_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("generated_content.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("revision", sa.SmallInteger, nullable=False),
        sa.Column("content", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("sources_cited", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("quality_score_before", sa.Numeric(5, 2), nullable=True),
        sa.Column("quality_flags_before", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column(
            "triggered_by_user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("generated_content_id", "revision", name="uq_genc_revision"),
    )


def downgrade() -> None:
    op.drop_table("generated_content_revisions")
    op.execute("DROP INDEX IF EXISTS ix_genc_quality_flags_gin;")
    op.drop_index("ix_genc_module_quality", table_name="generated_content")
    op.drop_index("ix_genc_quality_status", table_name="generated_content")
    op.drop_column("generated_content", "content_revision")
    op.drop_column("generated_content", "last_quality_run_id")
    op.drop_column("generated_content", "regeneration_attempts")
    op.drop_column("generated_content", "quality_assessed_at")
    op.drop_column("generated_content", "quality_flags")
    op.drop_column("generated_content", "quality_status")
    op.drop_column("generated_content", "quality_score")
    op.drop_index("ix_uqa_genc_created", table_name="unit_quality_assessments")
    op.drop_table("unit_quality_assessments")
    op.drop_table("course_glossary_terms")
    op.execute("DROP INDEX IF EXISTS ux_one_active_run_per_course;")
    op.drop_table("course_quality_runs")
