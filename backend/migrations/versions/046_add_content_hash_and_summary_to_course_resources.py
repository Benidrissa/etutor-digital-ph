"""Add content_hash, summary_text, summary_model to course_resources + backfill hashes.

Revision ID: 046
Revises: 045
Create Date: 2026-04-08

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_resources",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "course_resources",
        sa.Column("summary_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "course_resources",
        sa.Column("summary_model", sa.String(50), nullable=True),
    )
    op.add_column(
        "course_resources",
        sa.Column("summary_status", sa.String(10), nullable=True),
    )
    op.create_index(
        "ix_course_resources_content_hash",
        "course_resources",
        ["content_hash"],
    )

    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, raw_text FROM course_resources WHERE raw_text IS NOT NULL")
    )
    from hashlib import sha256

    for row in rows:
        hash_val = sha256(row.raw_text.encode("utf-8")).hexdigest()
        conn.execute(
            text("UPDATE course_resources SET content_hash = :hash WHERE id = :id"),
            {"hash": hash_val, "id": row.id},
        )


def downgrade() -> None:
    op.drop_index("ix_course_resources_content_hash", table_name="course_resources")
    op.drop_column("course_resources", "summary_status")
    op.drop_column("course_resources", "summary_model")
    op.drop_column("course_resources", "summary_text")
    op.drop_column("course_resources", "content_hash")
