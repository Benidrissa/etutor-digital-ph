"""add curricula and curriculum_courses tables

Revision ID: 042
Revises: 041
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE curriculumstatus AS ENUM ('draft', 'published', 'archived')")

    op.create_table(
        "curricula",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("cover_image_url", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "published", "archived", name="curriculumstatus", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_curricula_slug", "curricula", ["slug"])

    op.create_table(
        "curriculum_courses",
        sa.Column("curriculum_id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["curriculum_id"], ["curricula.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("curriculum_id", "course_id"),
    )


def downgrade() -> None:
    op.drop_table("curriculum_courses")
    op.drop_index("ix_curricula_slug", table_name="curricula")
    op.drop_table("curricula")
    op.execute("DROP TYPE curriculumstatus")
