"""Add source, content_type, updated_at to qbank_question_audio.

Revision ID: 072
Revises: 071
Create Date: 2026-04-20

Introduces ``source`` (enum: tts / manual) so admins, sub-admins and
experts can override generated TTS with a human recording or uploaded
clip on a per-question, per-language basis (#1747). Every pre-existing
row is backfilled to ``tts`` since all clips on the platform today
came from OpenAI TTS or MMS-VITS. Batch TTS regeneration and
translation backfills skip rows where ``source = 'manual'`` so a
recording is never silently overwritten.

Adds ``content_type`` because manual uploads can be webm/mp3/m4a/wav
in addition to TTS's Opus/OGG; the playback endpoint needs the real
MIME to hand the browser a decodable Content-Type header.

Also adds ``updated_at`` because the frontend audio manager needs a
cache-buster that changes when a clip is replaced — ``created_at``
stays frozen on the initial insert.
"""

import sqlalchemy as sa
from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None

SOURCE_ENUM_NAME = "qbankaudiosource"


def upgrade() -> None:
    # Postgres enum types are created lazily with create_type=False on
    # the column below; we create the type up front here so the default
    # expression can reference it.
    source_enum = sa.Enum("tts", "manual", name=SOURCE_ENUM_NAME)
    source_enum.create(op.get_bind(), checkfirst=True)

    source_col_type = sa.Enum(
        "tts",
        "manual",
        name=SOURCE_ENUM_NAME,
        create_type=False,
    )
    op.add_column(
        "qbank_question_audio",
        sa.Column(
            "source",
            source_col_type,
            server_default="tts",
            nullable=False,
        ),
    )
    op.add_column(
        "qbank_question_audio",
        sa.Column(
            "content_type",
            sa.String(100),
            nullable=True,
        ),
    )
    op.add_column(
        "qbank_question_audio",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("qbank_question_audio", "updated_at")
    op.drop_column("qbank_question_audio", "content_type")
    op.drop_column("qbank_question_audio", "source")
    sa.Enum(name=SOURCE_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
