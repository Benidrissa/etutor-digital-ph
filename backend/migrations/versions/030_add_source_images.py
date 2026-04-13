"""add source_images and source_image_chunks tables

Revision ID: 030
Revises: 029
Create Date: 2026-04-05

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN CREATE TYPE source_image_type_enum AS ENUM "
        "('diagram', 'photo', 'chart', 'formula', 'icon', 'unknown'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    op.create_table(
        "source_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("rag_collection_id", sa.String(), nullable=True),
        sa.Column("figure_number", sa.String(20), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column(
            "image_type",
            postgresql.ENUM(
                "diagram",
                "photo",
                "chart",
                "formula",
                "icon",
                "unknown",
                name="source_image_type_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chapter", sa.String(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("surrounding_text", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("format", sa.String(20), nullable=False, server_default="webp"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("original_format", sa.String(20), nullable=True),
        sa.Column("embedding", ARRAY(sa.Float()), nullable=True),
        sa.Column("alt_text_fr", sa.Text(), nullable=True),
        sa.Column("alt_text_en", sa.Text(), nullable=True),
        sa.Column("semantic_tags", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_source_images_semantic_tags_gin",
        "source_images",
        ["semantic_tags"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_source_images_source_figure",
        "source_images",
        ["source", "figure_number"],
    )
    op.create_index(
        "ix_source_images_source_chapter",
        "source_images",
        ["source", "chapter"],
    )
    op.create_index(
        "ix_source_images_rag_collection_id",
        "source_images",
        ["rag_collection_id"],
    )
    op.create_index(
        "ix_source_images_image_type",
        "source_images",
        ["image_type"],
    )

    op.create_table(
        "source_image_chunks",
        sa.Column("source_image_id", sa.UUID(), nullable=False),
        sa.Column("document_chunk_id", sa.UUID(), nullable=False),
        sa.Column("reference_type", sa.String(20), nullable=False, server_default="contextual"),
        sa.ForeignKeyConstraint(
            ["source_image_id"],
            ["source_images.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_chunk_id"],
            ["document_chunks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_image_id", "document_chunk_id"),
    )

    op.create_index(
        "ix_source_image_chunks_document_chunk_id",
        "source_image_chunks",
        ["document_chunk_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_image_chunks_document_chunk_id", table_name="source_image_chunks")
    op.drop_table("source_image_chunks")

    op.drop_index("ix_source_images_image_type", table_name="source_images")
    op.drop_index("ix_source_images_rag_collection_id", table_name="source_images")
    op.drop_index("ix_source_images_source_chapter", table_name="source_images")
    op.drop_index("ix_source_images_source_figure", table_name="source_images")
    op.drop_index("ix_source_images_semantic_tags_gin", table_name="source_images")
    op.drop_table("source_images")

    sa.Enum(name="source_image_type_enum").drop(op.get_bind())
