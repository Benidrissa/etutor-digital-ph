"""Add qbank_question_translations table.

Revision ID: 070
Revises: 069
Create Date: 2026-04-18

Stores NLLB-200 translations of French qbank questions into the four
West African target languages (mos/dyu/bam/ful) so MMS TTS receives
native-language text and produces intelligible audio (#1690).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qbank_question_translations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("qbank_questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_model", sa.String(50), nullable=False),
        sa.Column(
            "edited_by_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "question_id",
            "language",
            name="uq_qbank_question_translation_lang",
        ),
    )


def downgrade() -> None:
    op.drop_table("qbank_question_translations")
