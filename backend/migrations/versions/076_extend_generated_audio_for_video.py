"""Extend ``generated_audio`` to carry lesson-scoped videos too.

Revision ID: 076
Revises: 075
Create Date: 2026-04-21

Per issue #1802 we've decided the right scope for both audio and
video summaries is per-lesson — not per-module. The lesson-scoped
table ``generated_audio`` was already correct for audio; this
migration widens it so it can also hold HeyGen-rendered videos,
letting both media kinds share the cache, status machine, storage
key, and poller infrastructure.

Changes:

* ``media_type`` (text, NOT NULL, default ``'audio'``) — discriminator
  between the two kinds. Existing rows backfill to ``'audio'`` so
  everything keeps working without a code-side branch.
* ``provider_video_id`` (text, nullable) — HeyGen's async job id,
  needed by the poller to reconcile ``generating`` rows. Unused for
  audio.
* ``media_metadata`` (JSONB, nullable) — api_version (``v2`` vs
  ``v3-agent``) and ``is_kids`` flag for video rows; unused for
  audio today but kept for future per-row metadata.
* Unique constraint ``uq_generated_audio_module_unit_lang`` (on
  module_id/unit_id/language) is replaced with a 4-tuple that adds
  ``media_type`` so audio and video for the same lesson can co-exist.
* Partial unique index on ``provider_video_id`` (same shape as the
  old ModuleMedia one — matches how the poller correlates HeyGen
  events back to rows).

Table name stays ``generated_audio`` for now — renaming it is a
cosmetic follow-up that can ship without touching any downstream
code.
"""

import sqlalchemy as sa
from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_audio",
        sa.Column(
            "media_type",
            sa.String(length=20),
            server_default="audio",
            nullable=False,
        ),
    )
    op.add_column(
        "generated_audio",
        sa.Column("provider_video_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "generated_audio",
        sa.Column(
            "media_metadata",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # Backfill is covered by the server_default; drop the old unique
    # constraint and replace it with the 4-tuple variant.
    #
    # Defensive drop: the constraint name baked into the model
    # (``uq_generated_audio_module_unit_lang``) wasn't actually the
    # name Postgres assigned on every environment — staging's DB
    # ended up with a differently-named (or no) constraint for the
    # legacy 3-tuple, so a plain ``op.drop_constraint`` fails with
    # ``UndefinedObjectError``. Pulling the actual pg_constraint
    # rows and dropping each by its live name keeps the migration
    # idempotent across environments that drifted.
    op.execute(
        """
        DO $$
        DECLARE
            c text;
        BEGIN
            FOR c IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class cls ON cls.oid = con.conrelid
                WHERE cls.relname = 'generated_audio'
                  AND con.contype = 'u'
                  AND con.conname <> 'uq_generated_audio_module_unit_mediatype_lang'
            LOOP
                EXECUTE format(
                    'ALTER TABLE generated_audio DROP CONSTRAINT %I',
                    c
                );
            END LOOP;
        END $$;
        """
    )
    op.create_unique_constraint(
        "uq_generated_audio_module_unit_mediatype_lang",
        "generated_audio",
        ["module_id", "unit_id", "media_type", "language"],
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ix_generated_audio_provider_video_id "
        "ON generated_audio (provider_video_id) "
        "WHERE provider_video_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_generated_audio_provider_video_id")
    op.drop_constraint(
        "uq_generated_audio_module_unit_mediatype_lang",
        "generated_audio",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_generated_audio_module_unit_lang",
        "generated_audio",
        ["module_id", "unit_id", "language"],
    )
    op.drop_column("generated_audio", "media_metadata")
    op.drop_column("generated_audio", "provider_video_id")
    op.drop_column("generated_audio", "media_type")
