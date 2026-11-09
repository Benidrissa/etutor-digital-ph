"""Cartoon art for story mode (#2675): the cast's poses and the places' backdrops.

A course's story documents share one cast and one set of places (#2674), each
with a ``look``: an English sentence for the image model. This module turns
those looks into images, once per course, and tells the story routes which
images are ready.

* :func:`collect_looks` reads the looks out of story documents: ``cast[].look``
  (keyed by cast id), each ``cast[].variants[].look`` of the hero (keyed
  ``hero:<variant id>``) and ``places[].look`` (keyed by place id).
  The course-level looks come from the course's story bible (#2674, one small
  row): :func:`load_course_looks` gives a run the bible's looks, plus the keys
  the bible lacks from *published* hand-authored weeks (a course without a
  bible has only those). Drafts never feed the art. A story whose look of a
  bible key differs is served the bible's art; it never asks for its own.
  A view judges exactly as a run plans (:func:`art_for_view`): a generated
  story reads only the bible row, a hand-authored week the run's whole looks.
* :func:`plan_art` is what a run must draw, and :func:`build_art_map` the
  ``art`` map the story routes attach to the document they serve (the
  contract in #2672; never stored). Both judge every image by the same rule
  (:func:`row_state`) against the same course-level looks, so a view starts a
  run exactly when the run has something to draw.
* :class:`StoryArtGenerator` draws it. A character's ``idle`` pose comes
  first: full body, front view, on a transparent background. ``talk``,
  ``happy`` and ``think`` are then **image edits** of the idle image that
  change only the expression and the arms, so the face and the outfit stay
  the same. A place gets one 1536x1024 backdrop with no people and no text.
  Each image is tried at most twice per run (the SDK's own retries are off),
  then stored as ``failed``: for good when the failure is deterministic, or
  to be tried again by a later run after a backoff when it is transient.

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
from datetime import UTC, datetime, timedelta
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

#: Stored on every row (``story_art.art_version``). Bump it to redraw every
#: course's art (a prompt or post-processing change worth paying for): rows of
#: an older version are stale, so the next view of each course starts a run.
ART_VERSION = 1

#: Cost guard: images one run may draw (about 26 for a usual course: two hero
#: variants and four other cast members at four poses each, plus the places).
#: Anything beyond is skipped, logged, and left for the next run.
MAX_IMAGES_PER_RUN = 40
#: Image calls in flight at once.
CONCURRENCY = 3
#: Tries per image and run: the first and one retry. The SDK's own retries are
#: turned off (``max_retries=0``), so this is the real bound on paid calls.
ATTEMPTS_PER_IMAGE = 2
#: SDK retries for story-art calls: none (see ATTEMPTS_PER_IMAGE).
SDK_MAX_RETRIES = 0
#: A 1024x1536 edit with ``input_fidelity="high"`` is the slowest image call:
#: it gets more than the client's 120 s rather than an SDK re-send.
EDIT_TIMEOUT_S = 210.0
#: Wait before the second attempt after a 429 (not billed): the server's
#: ``retry-after`` when it sends one, else the default, never more than the cap.
RATE_LIMIT_WAIT_S = 20.0
RATE_LIMIT_WAIT_CAP_S = 60.0
#: A transient failure (outage, auth, quota, rate limit, timeout, 5xx) is not
#: final: later runs try the image again after these waits, one per failed
#: run, and give up after the last (the failure is then final, like a
#: deterministic one, until the look changes).
TRANSIENT_RETRY_BACKOFF = (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))
#: A client-side timeout is likely billed (the server often finishes the image
#: the client gave up on), so it gets one later run, not three.
TIMEOUT_LATER_RUNS = 1

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
    """sha256 of the normalised look (the art version is a column of its own)."""
    canonical = json.dumps([normalise_look(look)], ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _learner_first_name(document: Mapping[str, Any]) -> str | None:
    """The learner's first name of a document, unless it is a ``{placeholder}``."""
    learner = document.get("learner")
    first = learner.get("first_name") if isinstance(learner, Mapping) else None
    if not isinstance(first, str) or not first.strip() or "{" in first:
        return None
    return first.strip()


def is_hero(member: Mapping[str, Any], first_name: str | None) -> bool:
    """The learner's own character, by the player's rule (``cast.ts`` ``isHero``).

    By role or id ``hero``, or, in a hand-authored week, the member named
    like the learner (``learner.first_name``, when it is not a placeholder).
    """
    if member.get("role") == "hero" or member.get("id") == "hero":
        return True
    name = member.get("name")
    return bool(first_name) and isinstance(name, str) and name.strip() == first_name


def _variants(member: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The member's variants that have an id."""
    variants = member.get("variants")
    return [
        variant
        for variant in (variants if isinstance(variants, list) else [])
        if isinstance(variant, Mapping)
        and isinstance(variant.get("id"), str)
        and variant["id"].strip()
    ]


def collect_looks(documents: Iterable[Any]) -> list[ArtItem]:
    """The characters and places to draw, from story documents, deduplicated by key.

    Keys follow the player (``cast.ts``): the hero (:func:`is_hero`) with at
    least two variants is drawn once per variant, ``hero:<variant id>``,
    never as a bare id; with fewer, the player offers no choice and looks the
    hero up by its cast id, so it is drawn once under that id, with its one
    variant's look or its own. Every other member is drawn under its cast id
    with its own look (``variants`` are the hero's only). The first document
    that names a key wins, so pass the newest first. Entries without a usable
    id or look are skipped: an old story has no looks, and draws nothing.
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
        first_name = _learner_first_name(document)
        cast = document.get("cast")
        for member in cast if isinstance(cast, list) else []:
            if not isinstance(member, Mapping):
                continue
            variants = _variants(member)
            if is_hero(member, first_name) and len(variants) >= 2:
                for variant in variants:
                    add(KIND_CHARACTER, f"hero:{variant['id'].strip()}", variant.get("look"))
                continue
            look = member.get("look")
            if len(variants) == 1 and is_hero(member, first_name):
                look = variants[0].get("look") or look
            add(KIND_CHARACTER, member.get("id"), look)
        places = document.get("places")
        for place in places if isinstance(places, list) else []:
            if isinstance(place, Mapping):
                add(KIND_PLACE, place.get("id"), place.get("look"))
    # Characters first: when the cap cuts a run short, the cast matters most.
    return sorted(items, key=lambda item: item.kind != KIND_CHARACTER)


#: ``(kind, key)`` -> ``{look digest: look}``: the looks that count as current.
AcceptedLooks = Mapping[tuple[str, str], Mapping[str, str]]


@dataclass
class CourseLooks:
    """The course-level look of each key: the one look its art must match.

    ``items`` is what a run draws; ``accepted`` maps each ``(kind, key)`` to
    ``{digest: look}`` of that look, the form :func:`row_state` judges with.
    ``final`` is False while the looks come from a bible of defaults waiting
    for its retry (:data:`app.domain.services.story_bible.DEFAULTED`): it is
    likely to be replaced, so no art is paid for it.
    """

    items: list[ArtItem] = field(default_factory=list)
    accepted: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    final: bool = True

    def has(self, item: ArtItem) -> bool:
        return (item.kind, item.key) in self.accepted


def collect_course_looks(documents: Iterable[Any], *, final: bool = True) -> CourseLooks:
    """:class:`CourseLooks` of ``documents``, given in authority order (first wins)."""
    items = collect_looks(documents)
    return CourseLooks(
        items=items,
        accepted={(item.kind, item.key): {item.digest: item.look} for item in items},
        final=final,
    )


def _merged(first: CourseLooks, extra: Iterable[ArtItem]) -> CourseLooks:
    """``first`` plus the ``extra`` items whose keys it lacks (characters first).

    ``first``'s own items are drawn only when it is final: a bible of defaults
    waiting for its retry is judged against (its keys stay its own) but not
    paid for.
    """
    items = list(first.items) if first.final else []
    accepted = {key: dict(looks) for key, looks in first.accepted.items()}
    for item in extra:
        if (item.kind, item.key) not in accepted:
            items.append(item)
            accepted[(item.kind, item.key)] = {item.digest: item.look}
    items.sort(key=lambda item: item.kind != KIND_CHARACTER)
    return CourseLooks(items=items, accepted=accepted, final=first.final)


async def load_bible_looks(session: AsyncSession, course_id: uuid.UUID) -> CourseLooks | None:
    """The looks of the course's story bible (#2674), or None without a bible.

    The bible is the course's one cast and set of places; every module story
    is told with it. One small row: only its ``cast`` and ``places`` are read.
    """
    from app.domain.models.story_bible import StoryCourseBible
    from app.domain.services.story_bible import DEFAULTED

    row = (
        await session.execute(
            select(
                StoryCourseBible.content["cast"],
                StoryCourseBible.content["places"],
                StoryCourseBible.model,
            ).where(StoryCourseBible.course_id == course_id)
        )
    ).first()
    if row is None:
        return None
    cast, places, model = row
    return collect_course_looks([{"cast": cast, "places": places}], final=model != DEFAULTED)


def is_authored_week(record: Any) -> bool:
    """A hand-authored week: a story bound to no module (not generated)."""
    return getattr(record, "module_id", None) is None and (
        getattr(record, "module_unit_id", None) is None
    )


async def load_published_week_looks(session: AsyncSession, course_id: uuid.UUID) -> list[ArtItem]:
    """The looks of the course's *published* hand-authored weeks, newest first.

    Drafts never feed the art (an unpublished week must not change, or pay
    for, what learners see), and generated stories are told with the bible.
    Reads each week's ``cast``, ``places`` and ``learner`` (its hero may be
    the member named like the learner).
    """
    result = await session.execute(
        select(
            StoryCourseRecord.content["cast"],
            StoryCourseRecord.content["places"],
            StoryCourseRecord.content["learner"],
        )
        .where(
            StoryCourseRecord.course_id == course_id,
            StoryCourseRecord.status == "published",
            StoryCourseRecord.module_id.is_(None),
            StoryCourseRecord.module_unit_id.is_(None),
        )
        .order_by(StoryCourseRecord.updated_at.desc())
    )
    return collect_looks(
        {"cast": cast, "places": places, "learner": learner}
        for cast, places, learner in result.all()
    )


async def load_course_looks(session: AsyncSession, course_id: uuid.UUID) -> CourseLooks:
    """What a run draws for the course: the bible, then published weeks' extra keys.

    With a bible, its looks are the course's; a published hand-authored week
    only adds keys the bible lacks. Without one (a course of hand-authored
    weeks only), the published weeks' looks, the newest week first.
    """
    bible = await load_bible_looks(session, course_id)
    weeks = await load_published_week_looks(session, course_id)
    return _merged(bible or CourseLooks(), weeks)


async def load_bible_course_looks(session: AsyncSession, course_id: uuid.UUID) -> CourseLooks:
    """:func:`load_course_looks` without the weeks: the bible's part of a run.

    For a generated story's view (a module story, a chapter): its keys are
    the bible's, and this reads one small row, never another story.
    """
    return _merged(await load_bible_looks(session, course_id) or CourseLooks(), [])


@dataclass
class ViewArt:
    """What one story view shows, and the run it would start."""

    art_map: ArtMap
    #: What a run would draw now: :func:`plan_art` of the course's looks.
    plan: list[ArtJob]


def art_for_view(
    document_items: list[ArtItem],
    course: CourseLooks,
    rows: Iterable[Any],
    *,
    now: datetime | None = None,
) -> ViewArt:
    """The art map of one story view, judged exactly as a run plans.

    ``course`` is what a run draws (:func:`load_course_looks`, or its
    bible part for a generated story). Each of the document's images is
    judged against the course's look for its key; only a key the course
    does not know (a draft's own) is judged against the document's look.
    An image counts as outstanding only when the run's plan draws it: an
    unscheduled one (a draft's own key, a bible of defaults awaiting its
    retry) is missing, so the map never says ``pending`` for work nobody
    will do.
    """
    now = now or datetime.now(UTC)
    rows = list(rows)
    plan = plan_art(course.items, rows, accepted=course.accepted, now=now)
    scheduled = {(job.item.kind, job.item.key, pose) for job in plan for pose in job.poses}
    accepted = {key: dict(looks) for key, looks in course.accepted.items()}
    for item in document_items:
        accepted.setdefault((item.kind, item.key), {item.digest: item.look})
    art_map = build_art_map(document_items, rows, accepted=accepted, now=now, scheduled=scheduled)
    return ViewArt(art_map=art_map, plan=plan)


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
    """The ``art`` map of one document, and how much of it a run still has to draw."""

    art: dict[str, Any]
    #: Images the document shows that a run would (re)draw now.
    outstanding: int = 0


RowState = Literal["ready", "failed", "outstanding"]


def row_state(row: Any, accepted: Mapping[str, str], *, now: datetime) -> RowState:
    """How one stored image stands against the looks that count as current.

    ``outstanding`` (a run draws it): no row, a look that is not the course's
    any more, an older :data:`ART_VERSION`, or a transient failure whose wait
    is over. ``failed``: a final failure, or a transient one still waiting. A
    row of a *newer* version is current: code rolled back after a version bump
    keeps serving the newer art instead of redrawing every course.
    """
    if row is None or row.look_digest not in accepted or row.art_version < ART_VERSION:
        return "outstanding"
    if row.status == STATUS_READY:
        return "ready"
    if row.retry_after is not None and row.retry_after <= now:
        return "outstanding"
    return "failed"


def _accepted_for(item: ArtItem, accepted: AcceptedLooks | None) -> Mapping[str, str]:
    """The current looks of ``item``'s key; its own look when the course has none."""
    return (accepted or {}).get((item.kind, item.key)) or {item.digest: item.look}


def item_states(
    item: ArtItem,
    by_item: Mapping[tuple[str, str, str], Any],
    accepted: Mapping[str, str],
    *,
    now: datetime,
) -> dict[str, RowState]:
    """:func:`row_state` of each of ``item``'s images.

    A character's poses are edits of its idle, so while the idle is not ready
    they share its state: redrawn with it, or failed with it.
    """
    states = {
        pose: row_state(by_item.get((item.kind, item.key, pose)), accepted, now=now)
        for pose in item.poses
    }
    if item.kind == KIND_CHARACTER and states[POSE_IDLE] != "ready":
        for pose in CHARACTER_POSES[1:]:
            states[pose] = states[POSE_IDLE]
    return states


def _by_item(rows: Iterable[Any]) -> dict[tuple[str, str, str], Any]:
    return {(row.kind, row.key, row.pose): row for row in rows}


def build_art_map(
    items: Iterable[ArtItem],
    rows: Iterable[Any],
    *,
    accepted: AcceptedLooks | None = None,
    now: datetime | None = None,
    scheduled: set[tuple[str, str, str]] | None = None,
) -> ArtMap:
    """The contract's ``art`` map for a document whose looks are ``items``.

    Each image is judged by :func:`row_state` against ``accepted``, the
    course's current looks (:attr:`CourseLooks.accepted`), as :func:`plan_art`
    judges it; a key the course does not know is judged against the
    document's own look. With ``scheduled`` (the ``(kind, key, pose)`` a run
    would draw now), an image to draw that no run will draw counts as
    missing, not outstanding (:func:`art_for_view`).

    ``status`` is ``ready`` when every image is ready, ``pending`` when none is
    ready yet and some are being drawn, ``partial`` when some are ready and the
    rest are being drawn, failed or missing, and ``none`` when nothing is
    ready nor being drawn (no looks, or nothing that will be drawn). The
    player shows "being drawn" for ``pending`` only, and a placeholder for
    anything missing.
    """
    now = now or datetime.now(UTC)
    by_item = _by_item(rows)
    characters: dict[str, dict[str, str]] = {}
    places: dict[str, str] = {}
    ready = failed = outstanding = 0
    for item in items:
        states = item_states(item, by_item, _accepted_for(item, accepted), now=now)
        for pose, state in states.items():
            if state == "outstanding" and (
                scheduled is None or (item.kind, item.key, pose) in scheduled
            ):
                outstanding += 1
            elif state == "ready":
                ready += 1
                row = by_item[(item.kind, item.key, pose)]
                if item.kind == KIND_CHARACTER:
                    characters.setdefault(item.key, {})[pose] = art_url(row.id)
                else:
                    places[item.key] = art_url(row.id)
            else:
                failed += 1
    total = ready + failed + outstanding  # failed: failed, or not to be drawn
    status: ArtStatus
    if total and ready == total:
        status = "ready"
    elif ready:
        status = "partial"
    elif outstanding:
        status = "pending"
    else:
        status = "none"
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
        """Images this job draws."""
        return len(self.poses)


def plan_art(
    items: Iterable[ArtItem],
    rows: Iterable[Any],
    *,
    accepted: AcceptedLooks | None = None,
    retry_failed: bool = False,
    now: datetime | None = None,
) -> list[ArtJob]:
    """What a run must draw: every image :func:`row_state` calls ``outstanding``.

    ``items`` are the newest looks (what is drawn), ``accepted`` the looks that
    count as current (:class:`CourseLooks`). A ``failed`` image is drawn again
    only when its wait is over, or when ``retry_failed`` (operators). When a
    character's idle is (re)drawn, its other poses are redrawn with it: they
    are edits of the idle, and a new idle has a new face. A pose missing beside
    a kept idle is an edit of the stored idle, drawn as the look of that idle.
    """
    now = now or datetime.now(UTC)
    by_item = _by_item(rows)
    jobs: list[ArtJob] = []
    for item in items:
        looks = _accepted_for(item, accepted)
        states = item_states(item, by_item, looks, now=now)
        needed = [
            pose
            for pose, state in states.items()
            if state == "outstanding" or (state == "failed" and retry_failed)
        ]
        if not needed:
            continue
        if item.kind != KIND_CHARACTER or POSE_IDLE in needed:
            jobs.append(ArtJob(item=item, poses=item.poses))
            continue
        idle = by_item[(item.kind, item.key, POSE_IDLE)]  # ready, or the idle were needed
        drawn = ArtItem(item.kind, item.key, looks.get(idle.look_digest, item.look))
        jobs.append(ArtJob(item=drawn, poses=tuple(needed), idle_row_id=idle.id))
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


# -- Failures ----------------------------------------------------------------------


@dataclass(frozen=True)
class Failure:
    """How an image failed: the stored error, and whether a later run tries again."""

    error: str
    #: Runs in a row that failed it transiently (0 for a deterministic failure).
    failed_runs: int = 0
    #: When a later run may try again; None when the failure is final.
    retry_after: datetime | None = None


#: Error codes of a refused request (400) that are about the account, not the
#: request: the image succeeds once the account is topped up.
ACCOUNT_ERROR_CODES = frozenset({"billing_hard_limit_reached", "insufficient_quota"})


def _error_code(exc: BaseException) -> str | None:
    """The API's error ``code`` (``exc.code``, or the body's own ``error.code``)."""
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    body = getattr(exc, "body", None)
    if isinstance(body, Mapping):
        inner = body.get("error") if isinstance(body.get("error"), Mapping) else body
        code = inner.get("code")
        return code if isinstance(code, str) else None
    return None


def failure_is_timeout(exc: BaseException | None) -> bool:
    """A client-side timeout: the server may well have finished, and billed, the image."""
    import httpx
    import openai

    return isinstance(exc, openai.APITimeoutError | TimeoutError | httpx.TimeoutException)


def failure_is_transient(exc: BaseException | None) -> bool:
    """Whether a later run may succeed where this one failed.

    Deterministic (final until the look changes): the image was unusable
    (:class:`ArtProcessingError`), the model cannot do the call, or the request
    was refused (400, including moderation; 422). Transient: an outage or the
    account (authentication, permission, unknown model, rate limit or quota,
    a 400 saying the account is out of credit, timeout, connection, 5xx).
    Anything else is treated as deterministic, so an unknown error never keeps
    being paid for.
    """
    import httpx
    import openai

    from app.ai.providers.image_provider import ImageCapabilityError

    if exc is None:
        return False
    if isinstance(exc, openai.BadRequestError) and _error_code(exc) in ACCOUNT_ERROR_CODES:
        return True  # out of credit: works again once the account is topped up
    if isinstance(
        exc,
        ArtProcessingError
        | ImageCapabilityError
        | openai.BadRequestError
        | openai.UnprocessableEntityError,
    ):
        return False
    if isinstance(
        exc,
        openai.AuthenticationError
        | openai.PermissionDeniedError
        | openai.NotFoundError
        | openai.ConflictError
        | openai.RateLimitError
        | openai.InternalServerError
        | openai.APIConnectionError,  # APITimeoutError included
    ):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code >= 500 or exc.status_code == 408
    return isinstance(exc, TimeoutError | ConnectionError | httpx.TransportError)


def classify_failure(
    exc: BaseException | None, previous: Any, digest: str, *, now: datetime
) -> Failure:
    """The :class:`Failure` to store for an image that just failed every attempt.

    A transient failure waits :data:`TRANSIENT_RETRY_BACKOFF` (one more step
    per run that failed it in a row, for the same look) and is final once the
    waits are used up. A timeout is likely billed even though no image came
    back, so it gets at most :data:`TIMEOUT_LATER_RUNS` later run(s) before it
    is final. ``previous`` is the row the run found; only this image's own
    failed runs count (a pose never attempted because its idle failed is
    stored with ``failed_runs=0``).
    """
    error = _error_text(exc or ImageFailed())
    if not failure_is_transient(exc):
        return Failure(error=error)
    runs = 1
    if (
        previous is not None
        and previous.status == STATUS_FAILED
        and previous.look_digest == digest
        and previous.art_version == ART_VERSION
        and previous.failed_runs
    ):
        runs = previous.failed_runs + 1
    later_runs = TIMEOUT_LATER_RUNS if failure_is_timeout(exc) else len(TRANSIENT_RETRY_BACKOFF)
    retry_after = now + TRANSIENT_RETRY_BACKOFF[runs - 1] if runs <= later_runs else None
    return Failure(error=error, failed_runs=runs, retry_after=retry_after)


def rate_limit_wait(exc: BaseException) -> float | None:
    """Seconds to wait before retrying a 429 (``retry-after``), or None if not one."""
    import openai

    if not isinstance(exc, openai.RateLimitError):
        return None
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    wait = RATE_LIMIT_WAIT_S
    try:
        if headers.get("retry-after-ms") is not None:
            wait = float(headers["retry-after-ms"]) / 1000
        elif headers.get("retry-after") is not None:
            wait = float(headers["retry-after"])
    except (TypeError, ValueError):
        wait = RATE_LIMIT_WAIT_S
    return max(0.0, min(wait, RATE_LIMIT_WAIT_CAP_S))


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

    ``generate``, ``edit`` and ``sleep`` default to the provider functions and
    :func:`asyncio.sleep`; tests pass fakes. Every image is written in its own
    short transaction as soon as it is ready, so a run cut short keeps what it
    drew.
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
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        from app.ai.providers.image_provider import edit_image, generate_image

        self._session_factory = session_factory
        self._model = model
        self._max_images = max_images
        self._concurrency = concurrency
        self._retry_failed = retry_failed
        self._generate = generate or generate_image
        self._edit = edit or edit_image
        self._sleep = sleep or asyncio.sleep
        self._semaphore: asyncio.Semaphore | None = None
        #: The rows as the run found them, for the transient-failure count.
        self._previous: dict[tuple[str, str, str], Any] = {}

    async def run(self, course_id: uuid.UUID) -> dict[str, Any]:
        async with self._session_factory() as session:
            looks = await load_course_looks(session, course_id)
            rows = await load_art_rows(session, course_id)
        if not looks.final:
            logger.info(
                "story_art.bible_not_final",
                course_id=str(course_id),
                detail="a bible of defaults awaits its retry: its looks are not drawn",
            )
        self._previous = _by_item(rows)
        jobs = plan_art(looks.items, rows, accepted=looks.accepted, retry_failed=self._retry_failed)
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
            items=len(looks.items),
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
                    place_prompt(item.look),
                    model=self._model,
                    size=BACKDROP_SIZE,
                    max_retries=SDK_MAX_RETRIES,
                ),
                process_backdrop,
                report,
            )
            return

        if POSE_IDLE in job.poses:
            raw_idle, _ = await self._draw(
                course_id,
                item,
                POSE_IDLE,
                lambda: self._generate(
                    character_prompt(item.look),
                    model=self._model,
                    size=CHARACTER_SIZE,
                    background="transparent",
                    max_retries=SDK_MAX_RETRIES,
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
            # not drawn at all (nothing is paid). While the idle is not ready
            # they share its state (item_states), and they are drawn again with
            # it. They were never attempted, so none of the idle's failed runs
            # count against them (failed_runs=0): their own count starts when
            # they are first tried.
            for pose in poses:
                await self._store_failed(
                    course_id, item, pose, Failure(error="idle pose unavailable")
                )
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
                        max_retries=SDK_MAX_RETRIES,
                        timeout=EDIT_TIMEOUT_S,
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
    ) -> tuple[bytes | None, Failure | None]:
        """Draw, post-process and store one image.

        Returns ``(raw bytes, None)``, or ``(None, failure)`` when every
        attempt failed. A rate-limited (429, not billed) first attempt waits
        for the server's ``retry-after`` before the second, outside the
        semaphore.
        """
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
                wait = rate_limit_wait(exc)
                if wait and attempt < ATTEMPTS_PER_IMAGE:
                    await self._sleep(wait)
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
            return raw, None
        failure = classify_failure(
            last,
            self._previous.get((item.kind, item.key, pose)),
            item.digest,
            now=datetime.now(UTC),
        )
        await self._store_failed(course_id, item, pose, failure)
        report.failed += 1
        return None, failure

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
        self, course_id: uuid.UUID, item: ArtItem, pose: str, failure: Failure
    ) -> None:
        await self._store(
            course_id,
            item,
            pose,
            status=STATUS_FAILED,
            error=failure.error,
            failed_runs=failure.failed_runs,
            retry_after=failure.retry_after,
        )

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
        failed_runs: int = 0,
        retry_after: datetime | None = None,
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
                        art_version=ART_VERSION,
                        failed_runs=failed_runs,
                        retry_after=retry_after,
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
