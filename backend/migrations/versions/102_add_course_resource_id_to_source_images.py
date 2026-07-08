"""add course_resource_id to source_images for resource-keyed image cache

Revision ID: 102_add_course_resource_id_to_source_images
Revises: 101_add_image_overlay_text
Create Date: 2026-07-08

Links each source image back to its originating course_resource so the RAG
pipeline can find a donor course by content identity (file_hash / content_hash)
and clone images WITHOUT re-running PDF extraction — mirroring how
document_chunks.course_resource_id enables the text donor-clone
(_find_donor_chunks). Closes #2580.

Nullable + ON DELETE SET NULL: existing rows keep NULL (they simply can't act
as donors via the join; the per-image image_hash path still covers them). New
indexations populate it going forward.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "102_add_course_resource_id_to_source_images"
down_revision: str | None = "101_add_image_overlay_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_images",
        sa.Column("course_resource_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_source_images_course_resource_id",
        "source_images",
        "course_resources",
        ["course_resource_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_source_images_course_resource_id",
        "source_images",
        ["course_resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_images_course_resource_id", table_name="source_images")
    op.drop_constraint(
        "fk_source_images_course_resource_id",
        "source_images",
        type_="foreignkey",
    )
    op.drop_column("source_images", "course_resource_id")
