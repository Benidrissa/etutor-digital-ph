"""Add syllabus fields to modules and unit_type to module_units.

Revision ID: 047
Revises: 046
Create Date: 2026-04-08

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("modules", sa.Column("learning_objectives_fr", JSONB(), nullable=True))
    op.add_column("modules", sa.Column("learning_objectives_en", JSONB(), nullable=True))
    op.add_column("modules", sa.Column("quiz_topics_fr", JSONB(), nullable=True))
    op.add_column("modules", sa.Column("quiz_topics_en", JSONB(), nullable=True))
    op.add_column("modules", sa.Column("flashcard_categories_fr", JSONB(), nullable=True))
    op.add_column("modules", sa.Column("flashcard_categories_en", JSONB(), nullable=True))
    op.add_column("modules", sa.Column("case_study_fr", sa.Text(), nullable=True))
    op.add_column("modules", sa.Column("case_study_en", sa.Text(), nullable=True))
    op.add_column("module_units", sa.Column("unit_type", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("module_units", "unit_type")
    op.drop_column("modules", "case_study_en")
    op.drop_column("modules", "case_study_fr")
    op.drop_column("modules", "flashcard_categories_en")
    op.drop_column("modules", "flashcard_categories_fr")
    op.drop_column("modules", "quiz_topics_en")
    op.drop_column("modules", "quiz_topics_fr")
    op.drop_column("modules", "learning_objectives_en")
    op.drop_column("modules", "learning_objectives_fr")
