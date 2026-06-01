"""add file_hash to course_resources for upload-time dedup

Revision ID: 096_add_file_hash_to_course_resources
Revises: 095_add_image_hash_to_source_images
Create Date: 2026-05-16

SHA-256 of the raw PDF bytes computed at upload time. Allows the upload
endpoint to detect binary-identical PDFs before writing to disk or enqueuing
extraction — the most aggressive deduplication gate. content_hash (SHA-256 of
extracted text) fires only after extraction completes; file_hash fires at the
moment of upload.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "096_add_file_hash_to_course_resources"
down_revision: str | None = "095_add_image_hash_to_source_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_resources",
        sa.Column("file_hash", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_course_resources_file_hash",
        "course_resources",
        ["file_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_course_resources_file_hash", table_name="course_resources")
    op.drop_column("course_resources", "file_hash")
