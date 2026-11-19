"""Shared stock art for story mode (#2714): drawn once, reused by every course.

A course's cast and places used to be drawn again for each course, although
the roles (hero girl and boy, friend, mentor, family, the tutor lizard) and the
generic places (classroom, market, home, clinic...) hardly differ. Stock art
is one image per slot, shared by all the courses of a stack:

* ``kind="character"``: ``theme`` is the cast role (``hero``, ``friend``,
  ``mentor``, ``family``, ``tutor``), ``variant`` the hero's variant
  (``girl``, ``boy``, ``woman``, ``man``) or the audience (``kids``,
  ``adult``) of the other roles, or empty when one image fits every audience;
  ``pose`` is one of :data:`app.domain.models.story_art.STOCK_CHARACTER_POSES`.
* ``kind="place"``: ``theme`` is the place theme
  (:func:`app.domain.services.story_stock_art.place_theme`), ``variant`` a
  place id when the image is specific to it (``river_bank``), else empty;
  ``pose`` is ``backdrop``.
* ``pack`` is the regional pack (skin tones, clothes, landscapes), reviewed by
  a human: ``west_africa`` is the only one today.

**Nothing is served or adopted before a human approves it.** A row starts as a
``candidate`` (promoted from an existing course's art by
``scripts/promote_story_stock.py``, no AI call) and becomes ``approved`` with
``--approve``. A ``retired`` row is no longer adopted by new courses but keeps
serving the courses that already use it. A stock image is never changed: a
better one is a new row (new id, so a new immutable URL) and the old one is
retired.

A course adopts stock by getting ``story_art`` rows that point here
(``stock_id``, no bytes of their own). The art map then serves the stock
image's URL, ``/api/v1/story-art/{stock id}/data``, the same for every course.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Index, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base
from app.domain.models.story_art import KINDS, POSES

STOCK_CANDIDATE = "candidate"
STOCK_APPROVED = "approved"
STOCK_RETIRED = "retired"
STOCK_STATUSES = (STOCK_CANDIDATE, STOCK_APPROVED, STOCK_RETIRED)
#: The regional pack used when no other is configured.
DEFAULT_PACK = "west_africa"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class StoryStockArt(Base):
    """One stock image (one slot of kind, theme, variant, pack and pose)."""

    __tablename__ = "story_stock_art"
    __table_args__ = (
        CheckConstraint(_in("kind", KINDS), name="ck_story_stock_art_kind"),
        CheckConstraint(_in("pose", POSES), name="ck_story_stock_art_pose"),
        CheckConstraint(_in("status", STOCK_STATUSES), name="ck_story_stock_art_status"),
        # One live image per slot; retired ones are history.
        Index(
            "uq_story_stock_art_slot",
            "kind",
            "theme",
            "variant",
            "pack",
            "pose",
            unique=True,
            postgresql_where=sa.text("status <> 'retired'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    theme: Mapped[str] = mapped_column(String(60), nullable=False)
    variant: Mapped[str] = mapped_column(String(60), nullable=False, server_default="")
    pack: Mapped[str] = mapped_column(String(40), nullable=False, server_default=DEFAULT_PACK)
    pose: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STOCK_CANDIDATE)
    #: The WebP, as stored in ``story_art`` (characters keep their alpha channel).
    #: Deferred: the stock index needs none of the bytes.
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The image model that drew it.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: The look it was drawn from (provenance for the human review).
    look: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Where a promoted image came from: the course and the ``story_art`` row.
    #: Plain ids, no foreign key: the stock outlives the course it came from.
    source_course_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_art_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StorySeedState(Base):
    """Which version of a bundled seed (the prop library) a stack has applied."""

    __tablename__ = "story_seed_state"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: sha256 of the bundled library.json, so a changed pack with the same
    #: version number is still noticed.
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
