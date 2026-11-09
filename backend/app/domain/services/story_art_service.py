"""Cartoon art for story mode (#2675): the cast's poses and the places' backdrops.

A course's story documents share one cast and one set of places (#2674), each
with a ``look``: an English sentence for the image model. This module turns
those looks into images, once per course, and tells the story routes which
images are ready.

* :func:`collect_looks` reads the looks out of story documents: ``cast[].look``
  (keyed by cast id), each ``cast[].variants[].look`` of the hero (keyed
  ``hero:<variant id>``) and ``places[].look`` (keyed by place id).
* :class:`StoryArtGenerator` draws what is missing or stale. A character's
  ``idle`` pose comes first: full body, front view, on a transparent
  background. ``talk``, ``happy`` and ``think`` are then **image edits** of the
  idle image that change only the expression and the arms, so the face and the
  outfit stay the same. A place gets one 1536x1024 backdrop with no people and
  no text. Each image is tried at most twice, then stored as ``failed``.
* :func:`build_art_map` is the ``art`` map the story routes attach to the
  document they serve (the contract in #2672). It is never stored.

Every image call goes through :mod:`app.ai.providers.image_provider`, which
records each attempt in ``ai_usage_events``.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models.story_art import (
    CHARACTER_POSES,
    KIND_CHARACTER,
    KIND_PLACE,
    POSE_BACKDROP,
    POSE_IDLE,
    STATUS_FAILED,
    STATUS_READY,
    StoryArt,
)
from app.domain.models.story_course import StoryCourseRecord
from app.domain.services.image_service import PEOPLE_CONSTRAINT

logger = structlog.get_logger(__name__)

#: Ledger feature for every image call of an art run (``ai_usage_events.feature``).
FEATURE_STORY_ART = "story_art"

#: Part of every look digest. Bump it to redraw every course's art (a prompt or
#: post-processing change worth paying for); leave it alone otherwise.
ART_VERSION = 1

#: Cost guard: images one run may draw (about 26 for a usual course: two hero
#: variants and four other cast members at four poses each, plus the places).
#: Anything beyond is skipped, logged, and left for the next run.
MAX_IMAGES_PER_RUN = 40
#: Image calls in flight at once.
CONCURRENCY = 3
#: Tries per image: the first and one retry.
ATTEMPTS_PER_IMAGE = 2

#: A look longer than this is cut: it is one sentence by contract.
MAX_LOOK_CHARS = 600
#: Keys are stored in ``story_art.key`` (VARCHAR 100).
MAX_KEY_CHARS = 100

CHARACTER_SIZE = "1024x1536"
BACKDROP_SIZE = "1536x1024"
#: Characters are stored at most this tall, after trimming.
MAX_CHARACTER_HEIGHT = 768
BACKDROP_WIDTH = 1536
BACKDROP_ASPECT = 1.5
#: Alpha at or below this counts as background when trimming (anti-aliasing haze).
ALPHA_THRESHOLD = 16

#: The shared style line, first in every prompt. Modelled on the owner's Scratch
#: prototype: flat vector cartoon, thick dark outlines, warm palette.
STYLE_LINE = (
    "Art style: flat 2D vector cartoon in the style of a children's picture book, with thick "
    "dark outlines, flat colour fills with soft gradients, a warm palette (ochre, terracotta, "
    "golden yellow, leaf green, sky blue), simple rounded shapes, friendly and expressive. "
    "West African people and places."
)

#: What each pose changes from the idle image: the expression and the arms only.
#: Hands stay at or below the top of the head, so every pose trims to about the
#: same height and the character keeps its size when the pose changes.
POSE_CHANGES: dict[str, str] = {
    "talk": (
        "the mouth open mid-sentence as if speaking, one hand raised to chest height in an "
        "open, explaining gesture, the other arm relaxed at the side."
    ),
    "happy": (
        "a big joyful open smile and bright, happy eyes, both hands raised beside the cheeks "
        "in delight, no higher than the top of the head."
    ),
    "think": (
        "a thoughtful look: the eyes glancing up to one side, the mouth closed, one hand "
        "touching the chin, the other arm relaxed at the side."
    ),
}

ArtStatus = Literal["ready", "pending", "partial", "none"]


# -- Looks ---------------------------------------------------------------------


@dataclass(frozen=True)
class ArtItem:
    """One thing to draw: a character (four poses) or a place (one backdrop)."""

    kind: str
    key: str
    look: str

    @property
    def digest(self) -> str:
        return look_digest(self.look)

    @property
    def poses(self) -> tuple[str, ...]:
        return CHARACTER_POSES if self.kind == KIND_CHARACTER else (POSE_BACKDROP,)


def normalise_look(look: str) -> str:
    """One line, single spaces, at most :data:`MAX_LOOK_CHARS`."""
    return re.sub(r"\s+", " ", look).strip()[:MAX_LOOK_CHARS]


def look_digest(look: str) -> str:
    """sha256 of the art version and the normalised look."""
    canonical = json.dumps([ART_VERSION, normalise_look(look)], ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hero_prefix(member: Mapping[str, Any]) -> str | None:
    """``hero`` for the learner's hero (the contract's key), else the cast id."""
    if member.get("role") == "hero" or member.get("id") == "hero":
        return "hero"
    cast_id = member.get("id")
    return cast_id if isinstance(cast_id, str) and cast_id.strip() else None


def collect_looks(documents: Iterable[Any]) -> list[ArtItem]:
    """The characters and places to draw, from story documents, deduplicated by key.

    The first document that names a key wins, so pass the newest first. Only
    the hero has ``variants``; it is drawn once per variant (``hero:girl``,
    ``hero:boy``) and never as a bare ``hero``. Entries without a usable id or
    look are skipped: an old story has no looks, and draws nothing.
    """
    items: list[ArtItem] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, key: Any, look: Any) -> None:
        if not isinstance(key, str) or not key.strip():
            return
        if not isinstance(look, str) or not look.strip():
            return
        key = key.strip()[:MAX_KEY_CHARS]
        if (kind, key) in seen:
            return
        seen.add((kind, key))
        items.append(ArtItem(kind=kind, key=key, look=normalise_look(look)))

    for document in documents:
        if not isinstance(document, Mapping):
            continue
        cast = document.get("cast")
        for member in cast if isinstance(cast, list) else []:
            if not isinstance(member, Mapping):
                continue
            variants = member.get("variants")
            if isinstance(variants, list) and variants:
                prefix = _hero_prefix(member)
                for variant in variants:
                    if not isinstance(variant, Mapping) or prefix is None:
                        continue
                    variant_id = variant.get("id")
                    if isinstance(variant_id, str) and variant_id.strip():
                        add(KIND_CHARACTER, f"{prefix}:{variant_id.strip()}", variant.get("look"))
            else:
                add(KIND_CHARACTER, member.get("id"), member.get("look"))
        places = document.get("places")
        for place in places if isinstance(places, list) else []:
            if isinstance(place, Mapping):
                add(KIND_PLACE, place.get("id"), place.get("look"))
    # Characters first: when the cap cuts a run short, the cast matters most.
    return sorted(items, key=lambda item: item.kind != KIND_CHARACTER)


async def load_course_looks(session: AsyncSession, course_id: uuid.UUID) -> list[ArtItem]:
    """The looks of every story of the course, the newest story first.

    Reads only each document's ``cast`` and ``places``, not the whole document.
    Archived stories are left out.
    """
    result = await session.execute(
        select(StoryCourseRecord.content["cast"], StoryCourseRecord.content["places"])
        .where(
            StoryCourseRecord.course_id == course_id,
            StoryCourseRecord.status != "archived",
        )
        .order_by(StoryCourseRecord.updated_at.desc())
    )
    return collect_looks({"cast": cast, "places": places} for cast, places in result.all())


async def load_art_rows(session: AsyncSession, course_id: uuid.UUID) -> list[StoryArt]:
    """Every art row of the course, without the image bytes (deferred)."""
    result = await session.execute(select(StoryArt).where(StoryArt.course_id == course_id))
    return list(result.scalars().all())


# -- The art map served with a story --------------------------------------------


def art_url(art_id: uuid.UUID | str) -> str:
    return f"/api/v1/story-art/{art_id}/data"


def empty_art(status: ArtStatus = "none") -> dict[str, Any]:
    return {"status": status, "characters": {}, "places": {}}


@dataclass
class ArtMap:
    """The ``art`` map of one document, and whether a run should be started."""

    art: dict[str, Any]
    #: Images the document needs that are neither ready nor failed for its look.
    outstanding: int = 0


def _covers(row: Any, item: ArtItem, document_updated_at: datetime | None) -> bool:
    """Whether ``row`` is the art for ``item`` as this document describes it.

    Its digest matches; or it was drawn after this document was last written,
    from a newer story's look (stories share the course's cast; the newest
    one's look wins, and an older document must not ask for it again).
    """
    if row.look_digest == item.digest:
        return True
    updated = getattr(row, "updated_at", None)
    return bool(document_updated_at and updated and updated >= document_updated_at)


def build_art_map(
    items: Iterable[ArtItem],
    rows: Iterable[Any],
    *,
    document_updated_at: datetime | None = None,
) -> ArtMap:
    """The contract's ``art`` map for a document whose looks are ``items``.

    ``status`` is ``none`` when the document has no looks, ``ready`` when every
    image is ready, ``pending`` when none is ready yet and some are still to be
    drawn, and ``partial`` otherwise: some are ready, and the rest are still to
    be drawn or failed. The player draws a placeholder for anything missing.
    """
    by_item = {(row.kind, row.key, row.pose): row for row in rows}
    characters: dict[str, dict[str, str]] = {}
    places: dict[str, str] = {}
    ready = failed = outstanding = 0
    for item in items:
        for pose in item.poses:
            row = by_item.get((item.kind, item.key, pose))
            if row is None or not _covers(row, item, document_updated_at):
                outstanding += 1
            elif row.status == STATUS_READY:
                ready += 1
                if item.kind == KIND_CHARACTER:
                    characters.setdefault(item.key, {})[pose] = art_url(row.id)
                else:
                    places[item.key] = art_url(row.id)
            else:
                failed += 1
    total = ready + failed + outstanding
    status: ArtStatus
    if total == 0:
        status = "none"
    elif ready == total:
        status = "ready"
    elif outstanding and not ready:
        status = "pending"
    else:
        status = "partial"
    return ArtMap(
        art={"status": status, "characters": characters, "places": places},
        outstanding=outstanding,
    )


# -- Prompts -------------------------------------------------------------------


def character_prompt(look: str) -> str:
    """The idle pose: full body, front view, standing, transparent background."""
    return (
        f"{STYLE_LINE}\n"
        f"One cartoon character, alone: {look}\n"
        "Cute proportions with a large round head and big, round, expressive eyes. Full body "
        "from the top of the head to the feet, standing upright and facing the viewer (front "
        "view), arms relaxed at the sides, a calm friendly smile with the mouth closed. "
        "Centred, the whole figure visible with a small margin, the feet near the bottom edge.\n"
        "Transparent background: no scenery, no floor, no ground shadow, no frame, no text, no "
        "letters, no logos." + PEOPLE_CONSTRAINT
    )


def pose_prompt(look: str, pose: str) -> str:
    """An edit of the idle image that changes only the expression and the arms."""
    return (
        f"{STYLE_LINE}\n"
        f"Redraw this exact character in a new pose. The character: {look}\n"
        "Keep everything else identical: the same face, skin tone, hair, eyes, outfit, colours "
        "and accessory, the same body proportions, the same art style and line weight, the same "
        "size, framing and position in the frame, full body in front view with the feet near "
        "the bottom edge, on a transparent background.\n"
        f"Change only the facial expression and the arms: {POSE_CHANGES[pose]}\n"
        "No scenery, no floor, no ground shadow, no text." + PEOPLE_CONSTRAINT
    )


def place_prompt(look: str) -> str:
    """A wide, empty backdrop with open ground in the lower third."""
    return (
        f"{STYLE_LINE}\n"
        f"A wide landscape backdrop (3:2) for a scene of an animated cartoon: {look}\n"
        "An empty set: no people, no animals, no characters, no text, no letters, no numbers, "
        "no signs with writing, no logos. Seen at eye level. The ground or floor fills the "
        "lower third of the image and stays open and uncluttered, so characters can stand on "
        "it; the details sit in the upper two thirds and at the sides."
    )


# -- Post-processing -------------------------------------------------------------


class ArtProcessingError(ValueError):
    """The model's image cannot be used (unreadable, or nothing drawn)."""


def _open(raw: bytes):
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise ArtProcessingError(f"unreadable image: {exc}") from exc
    return image


def _clear_flat_background(image) -> None:
    """Make a flat background transparent, flood-filling from the corners (in place).

    For a model that ignored ``background="transparent"``: an opaque cut-out on
    a plain backdrop. Only pixels connected to a corner and close to its colour
    are cleared, so the character itself is left alone.
    """
    from PIL import ImageDraw

    width, height = image.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if image.getpixel(corner)[3] == 0:
            continue
        ImageDraw.floodfill(image, corner, (0, 0, 0, 0), thresh=24)


def process_character(raw: bytes) -> tuple[bytes, int, int]:
    """Trim, stand on the bottom edge, cap the height, and save as WebP with alpha.

    Trimming to the opaque bounding box puts the lowest drawn pixel (the feet)
    on the bottom edge, so the player can stand every pose on the same ground
    line. Returns ``(webp, width, height)``.
    """
    from PIL import Image

    image = _open(raw).convert("RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] == 255:  # no transparency at all
        _clear_flat_background(image)
        alpha = image.getchannel("A")
    bbox = alpha.point(lambda a: 255 if a > ALPHA_THRESHOLD else 0).getbbox()
    if bbox is None:
        raise ArtProcessingError("the image is empty (fully transparent)")
    image = image.crop(bbox)
    if image.height > MAX_CHARACTER_HEIGHT:
        width = max(1, round(image.width * MAX_CHARACTER_HEIGHT / image.height))
        image = image.resize((width, MAX_CHARACTER_HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=90, method=4)
    return buffer.getvalue(), image.width, image.height


def process_backdrop(raw: bytes) -> tuple[bytes, int, int]:
    """Crop to 3:2 if needed (centred), cap at 1536 wide, and save as WebP.

    gpt-image-1 returns 1536x1024 already; Gemini sets the aspect from the
    prompt and may not honour it. Returns ``(webp, width, height)``.
    """
    from PIL import Image

    image = _open(raw).convert("RGB")
    width, height = image.size
    aspect = width / height
    if abs(aspect - BACKDROP_ASPECT) > 0.02:
        if aspect > BACKDROP_ASPECT:  # too wide: trim the sides
            new_width = round(height * BACKDROP_ASPECT)
            left = (width - new_width) // 2
            image = image.crop((left, 0, left + new_width, height))
        else:  # too tall: trim the top and the bottom
            new_height = round(width / BACKDROP_ASPECT)
            top = (height - new_height) // 2
            image = image.crop((0, top, width, top + new_height))
    if image.width > BACKDROP_WIDTH:
        new_height = round(image.height * BACKDROP_WIDTH / image.width)
        image = image.resize((BACKDROP_WIDTH, new_height), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=88, method=4)
    return buffer.getvalue(), image.width, image.height


def png_reference(raw: bytes) -> bytes:
    """The idle image as the PNG the edit endpoint is sent (as is when already PNG)."""
    image = _open(raw)
    if image.format == "PNG":
        return raw
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def stored_reference(webp: bytes) -> bytes:
    """A stored (trimmed) idle image back on a 2:3 transparent canvas, as PNG.

    For a later run that redraws a pose but keeps the idle: the figure is put
    back where a fresh render has it (centred, feet near the bottom, a margin
    around), so the edit keeps the same framing.
    """
    from PIL import Image

    figure = _open(webp).convert("RGBA")
    height = round(figure.height / 0.88)
    width = max(round(height * 2 / 3), figure.width + 2 * round(height * 0.04))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    top = height - figure.height - round(height * 0.04)
    canvas.paste(figure, ((width - figure.width) // 2, top), figure)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


# -- Planning ----------------------------------------------------------------------


@dataclass(frozen=True)
class ArtJob:
    """The images of one item to draw in a run."""

    item: ArtItem
    poses: tuple[str, ...]
    #: For a character whose idle is kept: the stored idle row the edits start from.
    idle_row_id: uuid.UUID | None = None

    @property
    def cost(self) -> int:
        """Images this job draws (the edits of a character with no idle draw nothing)."""
        if self.item.kind == KIND_CHARACTER and POSE_IDLE not in self.poses:
            return len(self.poses) if self.idle_row_id is not None else 0
        return len(self.poses)


def plan_art(
    items: Iterable[ArtItem],
    rows: Iterable[Any],
    *,
    retry_failed: bool = False,
) -> list[ArtJob]:
    """What a run must draw: every image missing, or stale for its current look.

    A ``ready`` row with the current digest is kept. A ``failed`` one is kept
    too (it was tried twice already) unless ``retry_failed``. When a
    character's idle is (re)drawn, its other poses are redrawn with it: they
    are edits of the idle, and a new idle has a new face.
    """
    by_item = {(row.kind, row.key, row.pose): row for row in rows}
    jobs: list[ArtJob] = []
    for item in items:

        def needed(pose: str, item: ArtItem = item) -> bool:
            row = by_item.get((item.kind, item.key, pose))
            if row is None or row.look_digest != item.digest:
                return True
            return row.status != STATUS_READY and retry_failed

        if item.kind != KIND_CHARACTER:
            if needed(POSE_BACKDROP):
                jobs.append(ArtJob(item=item, poses=(POSE_BACKDROP,)))
            continue
        if needed(POSE_IDLE):
            jobs.append(ArtJob(item=item, poses=CHARACTER_POSES))
            continue
        poses = tuple(pose for pose in CHARACTER_POSES[1:] if needed(pose))
        if poses:
            idle = by_item[(item.kind, item.key, POSE_IDLE)]
            jobs.append(
                ArtJob(
                    item=item,
                    poses=poses,
                    idle_row_id=idle.id if idle.status == STATUS_READY else None,
                )
            )
    return jobs


def apply_cap(jobs: list[ArtJob], cap: int) -> tuple[list[ArtJob], list[ArtJob]]:
    """``(kept, skipped)``: whole jobs, in order, while their images fit in ``cap``.

    A character's poses are never split from its idle: a pose drawn without
    its idle in the same run could not share its face.
    """
    kept: list[ArtJob] = []
    skipped: list[ArtJob] = []
    used = 0
    for job in jobs:
        if used + job.cost <= cap:
            kept.append(job)
            used += job.cost
        else:
            skipped.append(job)
    return kept, skipped


# -- The run -----------------------------------------------------------------------


class ImageFailed(RuntimeError):
    """An image failed every attempt; ``str()`` is the stored error."""


@dataclass
class RunReport:
    ready: int = 0
    failed: int = 0
    skipped: list[str] = field(default_factory=list)

    def as_dict(self, planned: int) -> dict[str, Any]:
        return {
            "status": "complete",
            "planned": planned,
            "ready": self.ready,
            "failed": self.failed,
            "skipped": self.skipped,
        }


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


class StoryArtGenerator:
    """Draws a course's missing or stale story art (one run).

    ``generate`` and ``edit`` default to the provider functions; tests pass
    fakes. Every image is written in its own short transaction as soon as it
    is ready, so a run cut short keeps what it drew.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        model: str,
        max_images: int = MAX_IMAGES_PER_RUN,
        concurrency: int = CONCURRENCY,
        retry_failed: bool = False,
        generate: Callable[..., Awaitable[tuple[bytes, str]]] | None = None,
        edit: Callable[..., Awaitable[tuple[bytes, str]]] | None = None,
    ) -> None:
        from app.ai.providers.image_provider import edit_image, generate_image

        self._session_factory = session_factory
        self._model = model
        self._max_images = max_images
        self._concurrency = concurrency
        self._retry_failed = retry_failed
        self._generate = generate or generate_image
        self._edit = edit or edit_image
        self._semaphore: asyncio.Semaphore | None = None

    async def run(self, course_id: uuid.UUID) -> dict[str, Any]:
        async with self._session_factory() as session:
            items = await load_course_looks(session, course_id)
            rows = await load_art_rows(session, course_id)
        jobs = plan_art(items, rows, retry_failed=self._retry_failed)
        kept, skipped = apply_cap(jobs, self._max_images)
        report = RunReport(skipped=[job.item.key for job in skipped])
        if skipped:
            logger.warning(
                "story_art.cap_reached",
                course_id=str(course_id),
                cap=self._max_images,
                skipped=[{"key": job.item.key, "images": job.cost} for job in skipped],
            )
        planned = sum(job.cost for job in kept)
        logger.info(
            "story_art.run_started",
            course_id=str(course_id),
            items=len(items),
            jobs=len(kept),
            images=planned,
            model=self._model,
        )
        self._semaphore = asyncio.Semaphore(self._concurrency)
        results = await asyncio.gather(
            *(self._run_job(course_id, job, report) for job in kept), return_exceptions=True
        )
        for job, result in zip(kept, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "story_art.job_crashed",
                    course_id=str(course_id),
                    key=job.item.key,
                    error=_error_text(result),
                )
        logger.info("story_art.run_finished", course_id=str(course_id), **report.as_dict(planned))
        return report.as_dict(planned)

    # -- one item -----------------------------------------------------------------

    async def _run_job(self, course_id: uuid.UUID, job: ArtJob, report: RunReport) -> None:
        item = job.item
        if item.kind == KIND_PLACE:
            await self._draw(
                course_id,
                item,
                POSE_BACKDROP,
                lambda: self._generate(
                    place_prompt(item.look), model=self._model, size=BACKDROP_SIZE
                ),
                process_backdrop,
                report,
            )
            return

        if POSE_IDLE in job.poses:
            raw_idle = await self._draw(
                course_id,
                item,
                POSE_IDLE,
                lambda: self._generate(
                    character_prompt(item.look),
                    model=self._model,
                    size=CHARACTER_SIZE,
                    background="transparent",
                ),
                process_character,
                report,
            )
            reference = png_reference(raw_idle) if raw_idle is not None else None
        else:
            reference = await self._stored_idle(job.idle_row_id)

        poses = [pose for pose in job.poses if pose != POSE_IDLE]
        if reference is None:
            # No idle to edit from: the poses cannot share its face, so they are
            # not drawn at all (nothing is paid) and stay failed until the look
            # changes or a run is asked to retry failures.
            for pose in poses:
                await self._store_failed(course_id, item, pose, "idle pose unavailable")
                report.failed += 1
            return

        await asyncio.gather(
            *(
                self._draw(
                    course_id,
                    item,
                    pose,
                    lambda pose=pose: self._edit(
                        pose_prompt(item.look, pose),
                        reference,
                        model=self._model,
                        size=CHARACTER_SIZE,
                        background="transparent",
                    ),
                    process_character,
                    report,
                )
                for pose in poses
            )
        )

    async def _draw(
        self,
        course_id: uuid.UUID,
        item: ArtItem,
        pose: str,
        call: Callable[[], Awaitable[tuple[bytes, str]]],
        process: Callable[[bytes], tuple[bytes, int, int]],
        report: RunReport,
    ) -> bytes | None:
        """Draw, post-process and store one image; its raw bytes, or None if it failed."""
        assert self._semaphore is not None
        last: BaseException | None = None
        for attempt in range(1, ATTEMPTS_PER_IMAGE + 1):
            try:
                async with self._semaphore:
                    raw, model = await call()
                data, width, height = await asyncio.to_thread(process, raw)
            except Exception as exc:
                last = exc
                logger.warning(
                    "story_art.attempt_failed",
                    course_id=str(course_id),
                    key=item.key,
                    pose=pose,
                    attempt=attempt,
                    error=_error_text(exc),
                )
                continue
            await self._store(
                course_id,
                item,
                pose,
                status=STATUS_READY,
                image_data=data,
                width=width,
                height=height,
                model=model,
            )
            report.ready += 1
            return raw
        await self._store_failed(course_id, item, pose, _error_text(last or ImageFailed()))
        report.failed += 1
        return None

    async def _stored_idle(self, idle_row_id: uuid.UUID | None) -> bytes | None:
        if idle_row_id is None:
            return None
        async with self._session_factory() as session:
            data = (
                await session.execute(select(StoryArt.image_data).where(StoryArt.id == idle_row_id))
            ).scalar_one_or_none()
        if not data:
            return None
        try:
            return await asyncio.to_thread(stored_reference, data)
        except ArtProcessingError as exc:
            logger.warning("story_art.idle_unreadable", idle_id=str(idle_row_id), error=str(exc))
            return None

    async def _store_failed(
        self, course_id: uuid.UUID, item: ArtItem, pose: str, error: str
    ) -> None:
        await self._store(course_id, item, pose, status=STATUS_FAILED, error=error)

    async def _store(
        self,
        course_id: uuid.UUID,
        item: ArtItem,
        pose: str,
        *,
        status: str,
        image_data: bytes | None = None,
        width: int | None = None,
        height: int | None = None,
        model: str | None = None,
        error: str | None = None,
    ) -> None:
        """Replace the item's row with a new one (a new id, so a new immutable URL)."""
        try:
            async with self._session_factory() as session:
                await session.execute(
                    delete(StoryArt).where(
                        StoryArt.course_id == course_id,
                        StoryArt.kind == item.kind,
                        StoryArt.key == item.key,
                        StoryArt.pose == pose,
                    )
                )
                session.add(
                    StoryArt(
                        id=uuid.uuid4(),
                        course_id=course_id,
                        kind=item.kind,
                        key=item.key,
                        pose=pose,
                        look_digest=item.digest,
                        image_data=image_data,
                        width=width,
                        height=height,
                        model=model,
                        status=status,
                        error=error,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.error(
                "story_art.store_failed",
                course_id=str(course_id),
                key=item.key,
                pose=pose,
                error=_error_text(exc),
            )
