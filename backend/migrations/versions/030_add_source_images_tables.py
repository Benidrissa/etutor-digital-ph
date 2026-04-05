"""add source_images and source_image_chunks tables

Revision ID: 030
Revises: 029
Create Date: 2026-04-05

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE source_image_type_enum AS ENUM "
        "('diagram', 'chart', 'photo', 'formula', 'icon', 'unknown')"
    )
    op.execute("CREATE TYPE image_chunk_reference_type_enum AS ENUM ('explicit', 'contextual')")

    op.create_table(
        "source_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("rag_collection_id", sa.String(), nullable=True),
        sa.Column("figure_number", sa.String(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column(
            "image_type",
            sa.Enum(
                "diagram",
                "chart",
                "photo",
                "formula",
                "icon",
                "unknown",
                name="source_image_type_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chapter", sa.String(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("alt_text_fr", sa.Text(), nullable=True),
        sa.Column("alt_text_en", sa.Text(), nullable=True),
        sa.Column("surrounding_text", sa.Text(), nullable=True),
        sa.Column("embedding", sa.ARRAY(sa.Float()), nullable=True),
        sa.Column("extra_meta", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_images_source", "source_images", ["source"])
    op.create_index("ix_source_images_rag_collection_id", "source_images", ["rag_collection_id"])
    op.create_index("ix_source_images_image_type", "source_images", ["image_type"])

    op.create_table(
        "source_image_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("image_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column(
            "reference_type",
            sa.Enum(
                "explicit",
                "contextual",
                name="image_chunk_reference_type_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="contextual",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["source_images.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_image_chunks_chunk_id", "source_image_chunks", ["chunk_id"])
    op.create_index("ix_source_image_chunks_image_id", "source_image_chunks", ["image_id"])
    op.create_index(
        "ix_source_image_chunks_reference_type",
        "source_image_chunks",
        ["reference_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_image_chunks_reference_type", "source_image_chunks")
    op.drop_index("ix_source_image_chunks_image_id", "source_image_chunks")
    op.drop_index("ix_source_image_chunks_chunk_id", "source_image_chunks")
    op.drop_table("source_image_chunks")

    op.drop_index("ix_source_images_image_type", "source_images")
    op.drop_index("ix_source_images_rag_collection_id", "source_images")
    op.drop_index("ix_source_images_source", "source_images")
    op.drop_table("source_images")

    op.execute("DROP TYPE IF EXISTS image_chunk_reference_type_enum")
    op.execute("DROP TYPE IF EXISTS source_image_type_enum")
