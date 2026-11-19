"""Shared stock art for story mode (#2714): look it up, and adopt it for a course.

Before an art run draws a character or a place, it asks this module for a
reviewed stock image of the same role (or place theme), variant, region pack
and pose (:class:`app.domain.models.story_stock_art.StoryStockArt`). A hit
costs no image call: the course gets ``story_art`` rows that point at the
stock image (``stock_id``, no bytes of their own). A miss falls back to
drawing, exactly as before, so a stack whose stock is empty still gets art.

Slots, most specific first (:func:`slot_candidates`):

* a character: ``(role, variant)``, then ``(role, "")``. The hero's variant is
  its variant id (``girl``); another role's is the course's audience
  (``kids``, ``adult``). A character is adopted whole: stock must hold all
  four base poses (idle, talk, happy, think), because the poses are edits of
  the idle and must share its face. Stock never mixes with a course's own
  drawing of the same character;
* a place: ``(theme, place id)``, then ``(theme, "")``, where the theme is
  :func:`place_theme`, a port of the player's ``placeTheme`` (``places.ts``).

Only ``approved`` stock is adopted or served, never a candidate.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.story_art import (
    CHARACTER_POSES,
    EXTRA_CHARACTER_POSES,
    KIND_CHARACTER,
    KIND_PLACE,
    POSE_BACKDROP,
    STATUS_READY,
    StoryArt,
)
from app.domain.models.story_stock_art import STOCK_APPROVED, StoryStockArt

logger = structlog.get_logger(__name__)

#: ``model`` stored on a ``story_art`` row that adopted stock.
STOCK_MODEL = "stock"

#: The player's catalogue of older places (``places.ts`` ``CATALOG``).
_CATALOG = {
    "home": "home",
    "kitchen": "kitchen",
    "market": "market",
    "classroom": "classroom",
    "school_yard": "yard",
    "mango_farm": "farm",
    "bus_station": "road",
    "shop": "shop",
    "desk": "desk",
    "montreal": "city",
}

#: ``places.ts`` ``KEYWORDS``, in the same order (first match wins).
_KEYWORDS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), theme)
    for pattern, theme in (
        (r"class ?room|lecture|tutorial room|salle de classe|chalkboard|blackboard", "classroom"),
        (r"clinic|hospital|health|sant[eé]|dispensar|maternit|pharmac|\bward\b|surgery", "clinic"),
        (r"\blab|laborator", "lab"),
        (r"office|bureau|meeting|workplace|ministry|headquarter|council|desk", "office"),
        (r"market|march[eé]|stall", "market"),
        (r"shop|store|boutique|kiosk|pharmacy counter", "shop"),
        (r"kitchen|cuisine", "kitchen"),
        (r"farm|field|garden|orchard|verger|champ|plantation|crop", "farm"),
        (r"school ?yard|playground|cour d|school", "yard"),
        (r"road|bus|station|street|gare|route|taxi|truck", "road"),
        (r"city|town|ville|downtown|skyline", "city"),
        (r"home|house|maison|compound|living room|bedroom", "home"),
        (r"village|well|puits|pond|river|mare|borehole|water point", "village"),
        (r"savann|bush|baobab|desert|sahel", "savanna"),
    )
)


def place_theme(place_id: str, look: str = "") -> str | None:
    """The theme of a place, as the player decides it; None when the player would guess.

    The player falls back to a hash of the id for a place no keyword fits.
    That is a coin toss, not a theme, so no stock is looked up for it.
    """
    pid = (place_id or "").lower()
    if pid in _CATALOG:
        return _CATALOG[pid]
    spaced = re.sub(r"[_-]+", " ", pid)
    for pattern, theme in _KEYWORDS:
        if pattern.search(spaced):
            return theme
    words = f"{spaced} {(look or '').lower()}"
    for pattern, theme in _KEYWORDS:
        if pattern.search(words):
            return theme
    return None


def slug(value: str | None) -> str:
    """A slot component: lower case, ``[a-z0-9_]`` only."""
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")[:60]


#: ``(kind, theme, variant)``: a stock slot without its pose and pack.
Slot = tuple[str, str, str]


def slot_candidates(
    kind: str, key: str, role: str = "", variant: str = "", look: str = ""
) -> list[Slot]:
    """The stock slots an item may adopt, most specific first (empty: no stock applies)."""
    if kind == KIND_CHARACTER:
        theme = slug(role)
        if not theme:
            return []
        specific = slug(variant)
        slots = [(KIND_CHARACTER, theme, specific)] if specific else []
        return [*slots, (KIND_CHARACTER, theme, "")]
    if kind == KIND_PLACE:
        theme = place_theme(key, look)
        if not theme:
            return []
        own = slug(key)
        slots = [(KIND_PLACE, theme, own)] if own else []
        return [*slots, (KIND_PLACE, theme, "")]
    return []


@dataclass(frozen=True)
class StockImage:
    """An approved stock image as the art map needs it (never its bytes)."""

    id: uuid.UUID
    pose: str


#: ``slot`` -> ``pose`` -> image.
StockIndex = dict[Slot, dict[str, StockImage]]


async def load_stock_index(session: AsyncSession, pack: str) -> StockIndex:
    """Every approved stock image of ``pack``, by slot and pose (one query, no bytes)."""
    rows = await session.execute(
        select(
            StoryStockArt.id,
            StoryStockArt.kind,
            StoryStockArt.theme,
            StoryStockArt.variant,
            StoryStockArt.pose,
        ).where(StoryStockArt.status == STOCK_APPROVED, StoryStockArt.pack == pack)
    )
    index: StockIndex = {}
    for stock_id, kind, theme, variant, pose in rows.all():
        index.setdefault((kind, theme, variant), {})[pose] = StockImage(stock_id, pose)
    return index


def _complete(images: Mapping[str, StockImage], kind: str) -> bool:
    needed = (POSE_BACKDROP,) if kind == KIND_PLACE else CHARACTER_POSES
    return all(pose in images for pose in needed)


def find_stock(
    index: StockIndex, kind: str, key: str, role: str = "", variant: str = "", look: str = ""
) -> dict[str, StockImage] | None:
    """The stock images an item adopts (all its base poses), or None."""
    for slot in slot_candidates(kind, key, role, variant, look):
        images = index.get(slot)
        if images and _complete(images, kind):
            return images
    return None


def stock_poses(kind: str, images: Mapping[str, StockImage]) -> list[str]:
    """The poses to adopt: the base ones, then the extras the stock also has."""
    if kind == KIND_PLACE:
        return [POSE_BACKDROP]
    return [*CHARACTER_POSES, *(p for p in EXTRA_CHARACTER_POSES if p in images)]


def stock_row(
    course_id: uuid.UUID,
    kind: str,
    key: str,
    pose: str,
    digest: str,
    image: StockImage,
    version: int,
) -> StoryArt:
    """The ``story_art`` row of a course that adopts ``image``."""
    return StoryArt(
        id=uuid.uuid4(),
        course_id=course_id,
        kind=kind,
        key=key,
        pose=pose,
        look_digest=digest,
        image_data=None,
        model=STOCK_MODEL,
        status=STATUS_READY,
        art_version=version,
        failed_runs=0,
        stock_id=image.id,
    )


def stock_ids(rows: Iterable[StoryArt]) -> set[uuid.UUID]:
    return {row.stock_id for row in rows if getattr(row, "stock_id", None)}


__all__: Sequence[str] = (
    "STOCK_MODEL",
    "StockImage",
    "find_stock",
    "load_stock_index",
    "place_theme",
    "slot_candidates",
    "stock_poses",
    "stock_row",
)
