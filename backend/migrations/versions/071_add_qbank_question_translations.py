"""Add qbank_question_translations table for NLLB-cached translations.

Revision ID: 071
Revises: 069
Create Date: 2026-04-18

Caches NLLB-200 per-question, per-language translations (#1694) so the
audio pregen pipeline doesn't call the sidecar for the same text every
time a bank is republished. Content hash lets us invalidate when a
question is edited.
"""

import sqlalchemy as sa
from alembic import op

revision = "071"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qbank_question_translations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("qbank_questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "translator",
            sa.String(64),
            nullable=False,
            server_default="nllb-200-distilled-600M",
        ),
        sa.Column(
            "reviewed_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "question_id", "language", name="uq_qbank_question_translation_lang"
        ),
    )


def downgrade() -> None:
    op.drop_table("qbank_question_translations")
