"""Normalize generated_content.content->>unit_id to canonical `X.Y` form.

Revision ID: 081
Revises: 080
Create Date: 2026-04-24

Historical rows stored `unit_id` as the legacy zero-padded `M01-U04` string
(produced by the now-removed `_unit_number_to_unit_id` helper). This migration
rewrites every such value to the canonical `module_number.unit_ordinal` form
used everywhere else in the codebase and on the `module_units.unit_number`
column.

Strict behaviour: if any row's `unit_id` matches neither the canonical nor the
legacy pattern, the migration raises and aborts. Pre-migration DB triage must
resolve those rows first. See #1897 / #1898.

Rows with missing `unit_id` key or empty string are left untouched (flashcards
store module-level content with no unit scope).

Forward-only: downgrade is intentionally not implemented. Rollback is via
code revert.
"""

import re
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None

LEGACY_RE = re.compile(r"^M0*(\d+)-U0*(\d+)$")
CANONICAL_RE = re.compile(r"^\d+\.\d+$")


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT id, content->>'unit_id' AS uid
            FROM generated_content
            WHERE content->>'unit_id' IS NOT NULL AND content->>'unit_id' <> ''
            """
        )
    ).fetchall()

    to_update: list[tuple[UUID, str]] = []
    unexpected: list[tuple[str, str]] = []

    for row in rows:
        uid = row.uid
        if CANONICAL_RE.match(uid):
            continue
        m = LEGACY_RE.match(uid)
        if m:
            canonical = f"{int(m.group(1))}.{int(m.group(2))}"
            to_update.append((row.id, canonical))
        else:
            unexpected.append((str(row.id), uid))

    if unexpected:
        raise RuntimeError(
            f"Strict migration abort: {len(unexpected)} generated_content row(s) "
            f"have unexpected unit_id format. Triage before re-running. "
            f"Samples: {unexpected[:5]}"
        )

    for id_, canonical in to_update:
        conn.execute(
            sa.text(
                """
                UPDATE generated_content
                SET content = CAST(
                    jsonb_set(
                        CAST(content AS jsonb),
                        '{unit_id}',
                        to_jsonb(CAST(:val AS text))
                    ) AS json
                )
                WHERE id = :id
                """
            ),
            {"id": id_, "val": canonical},
        )


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration; rollback via code revert and redeploy.")
