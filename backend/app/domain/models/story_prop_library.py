"""The shared prop library of story mode (docs/story-mode-3d-assets.md, Phase A).

Pictures rendered from free 3D models by the asset foundry
(``infrastructure/asset-foundry``) and imported with
``scripts/import_story_library.py``. One library serves every course:

* :class:`StoryLibraryAsset` is one picture: a ``sticker`` (an everyday prop
  in the stage's cartoon style) or a ``closeup`` (a realistic "Look closely"
  render of an educational object, with a 960 px version). It carries its
  licence, its credit line in both languages and where it came from. Every
  stored image gets a fresh ``id``: the data route serves it as immutable, so
  a changed picture never reuses the URL of the one it replaces.
* :class:`StoryPropMatch` caches what a prop's search phrase (``prop.query``)
  matched: one row per normalised phrase and prop kind, pointing at an asset
  or at nothing (a miss). Phrases are matched once, by a background task, never
  while a story is served; the misses are the library's to-do list. An import
  clears the cache, so every phrase is matched again against the new library.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base

ASSET_STICKER = "sticker"
ASSET_CLOSEUP = "closeup"
ASSET_KINDS = (ASSET_STICKER, ASSET_CLOSEUP)

#: The prop kinds a library asset can serve (a "figure" prop shows the course's own).
PROP_STICKER = "sticker"
PROP_REAL = "real"
PROP_KINDS = (PROP_STICKER, PROP_REAL)

#: How a phrase was matched: by embeddings, by its head noun only, or not at
#: all because the library was empty.
METHODS = ("embedding", "lexical", "empty")


class StoryLibraryAsset(Base):
    """One picture of the shared prop library."""

    __tablename__ = "story_library_assets"
    __table_args__ = (
        CheckConstraint("kind IN ('sticker', 'closeup')", name="ck_story_library_assets_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The foundry manifest's id (snake_case); stable across re-imports.
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: ``{"en": ..., "fr": ...}``: alt text and close-up title.
    label: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    #: WebP, at most 400 px on its long side. Deferred: matching never needs it.
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    #: Close-ups only: the WebP at most 960 px (``PropPicture.src_large``).
    image_large: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Size of ``image_data``, for the player's data-saver prompt.
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    #: sha256 of ``image_data`` and ``image_large``: a change means a new ``id``.
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: "CC0-1.0", "PDM", "CC-BY-4.0", "CC-BY-SA-4.0"...
    licence: Mapped[str] = mapped_column(String(32), nullable=False)
    attribution_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: ``{"en": ..., "fr": ...}``: the credit line, as the foundry wrote it.
    credit: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: The manifest's ``source``: author, licence, page, site, title...
    source: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: text-embedding-3-small of the label and tags; null until computed.
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    library_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StoryPropMatch(Base):
    """What one search phrase matched in the library, or a miss."""

    __tablename__ = "story_prop_matches"
    __table_args__ = (
        CheckConstraint("prop_kind IN ('sticker', 'real')", name="ck_story_prop_matches_kind"),
        CheckConstraint(
            "method IN ('embedding', 'lexical', 'empty')", name="ck_story_prop_matches_method"
        ),
    )

    #: The normalised search phrase (``story_prop_library.normalise_query``).
    query: Mapped[str] = mapped_column(String(200), primary_key=True)
    prop_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    #: Null: no asset matched (a miss, the library's to-do list).
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("story_library_assets.id", ondelete="SET NULL"), nullable=True
    )
    #: Cosine similarity of the match, when embeddings were used.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
