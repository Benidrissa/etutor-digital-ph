"""Bind a story_courses row to a whole module (module story mode).

Story mode moves from one story per lesson unit to one story per
``(module, language)``, assembled from one chapter per unit. The lesson-bound
rows of migration 106 stay as they are: they are now the chapter cache.

A module story is a row with ``module_id`` set and ``module_unit_id`` null,
slug ``module-{module hex}-{lang}``. Two nullable columns describe what it was
merged from:

* ``source_rows`` — its manifest: the assembler version and, per unit, the
  chapter row (id and ``updated_at``) it was built from;
* ``source_units_digest`` — sha256 of the module's roster (ids, numbers,
  order, roles and titles), so a renamed or added unit re-merges it.

The partial unique index allows one module story per ``(module_id,
language)``; chapter rows share that pair, hence ``WHERE module_unit_id IS
NULL``. Hand-authored weeks (``module_id`` null) are untouched.

The upgrade is additive. The downgrade deletes the module stories first: at
106, a row with ``module_unit_id`` null is a hand-authored week, so the
catalog and the slug route would serve them publicly. An image rollback runs
no downgrade, so DEPLOY.md ("Rolling back below a migration") says to run
this one before an older image starts.

Revision ID: 107_story_module_binding
Revises: 106_add_story_unit_binding
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "107_story_module_binding"
down_revision = "106_add_story_unit_binding"
branch_labels = None
depends_on = None

#: Module stories, as opposed to hand-authored weeks and lesson chapters.
MODULE_ROWS = "module_id IS NOT NULL AND module_unit_id IS NULL"


def upgrade() -> None:
    op.add_column("story_courses", sa.Column("source_rows", JSONB(), nullable=True))
    op.add_column("story_courses", sa.Column("source_units_digest", sa.String(64), nullable=True))
    op.create_index(
        "uq_story_courses_module_story",
        "story_courses",
        ["module_id", "language"],
        unique=True,
        postgresql_where=sa.text("module_unit_id IS NULL"),
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM story_courses WHERE {MODULE_ROWS}")
    op.drop_index("uq_story_courses_module_story", table_name="story_courses")
    op.drop_column("story_courses", "source_units_digest")
    op.drop_column("story_courses", "source_rows")
