"""Endpoints for ``story-course/1`` course files.

Learners read the catalog and download a week whole, because the player keeps
it in IndexedDB and runs offline. Authors validate and publish through the
admin routes, and a week can only reach ``published`` with zero validator
errors — the format's own rule, enforced here rather than trusted.

Story mode tells each module as one story
(``GET /story-courses/module/{module_id}``), one chapter per unit: generated
from the module's lessons and quizzes the first time a learner opens it, then
cached like lessons and quizzes are. A generated row (a module story, or the
lesson chapter it was assembled from) is reachable only through that route,
which applies the module's subscription gate, the story-mode switch and the
staleness check. The catalog never lists one, the slug route never serves one
to a learner, and the authoring routes cannot write one.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Sequence
from typing import Literal

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import (
    AuthenticatedUser,
    get_current_user,
    module_story_access,
    require_role,
    require_subscription_or_free_module,
)
from app.api.v1._task_status import mark_dispatched as mark_task_dispatched
from app.api.v1._task_status import vouch_while_owned
from app.api.v1.schemas.story_course import (
    Languages,
    StoryCourse,
    StoryCourseListItem,
    StoryCourseListResponse,
    ValidationReport,
)
from app.domain.models.module import Module
from app.domain.models.story_course import StoryCourseRecord
from app.domain.models.user import UserRole
from app.domain.services.country_utils import canonicalize_country
from app.domain.services.story_art_service import (
    build_art_map,
    collect_looks,
    empty_art,
    load_art_rows,
)
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import (
    RELEASE_IF_OWNER_SCRIPT,
    story_mode_enabled,
    upsert_story_course,
)
from app.domain.services.story_module_assembly import StoryUnit
from app.domain.services.story_module_service import (
    find_module_story,
    load_story_units,
    module_story_is_fresh,
)
from app.domain.services.story_module_service import (
    story_dispatch_key as module_story_dispatch_key,
)
from app.tasks.content_generation import MODULE_STORY_DISPATCH_TTL_S, generate_module_story_task
from app.tasks.story_art import (
    STORY_ART_DISPATCH_TTL_S,
    generate_story_art,
    story_art_dispatch_key,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/story-courses", tags=["Story courses"])

_ADMIN = require_role(UserRole.admin, UserRole.sub_admin)
_ADMIN_ROLES = {UserRole.admin.value, UserRole.sub_admin.value}


def _actor_id(user: AuthenticatedUser) -> uuid.UUID | None:
    """The acting user as a UUID; the JWT carries it as a string."""
    try:
        return uuid.UUID(str(user.id))
    except (TypeError, ValueError):
        return None


class SaveStoryCourseRequest(BaseModel):
    """A whole authored course file, plus where it belongs."""

    content: dict = Field(..., description="The course.json document")
    course_id: uuid.UUID | None = Field(
        None, description="Optional Sira course this week belongs to"
    )
    publish: bool = Field(
        False,
        description="Publish straight away. Refused when the validator finds errors.",
    )


class SaveStoryCourseResponse(BaseModel):
    id: uuid.UUID
    slug: str
    status: str
    is_valid: bool
    validation: ValidationReport


def _parse(content: dict) -> StoryCourse:
    """Parse an authored file, turning schema failures into a 422."""
    try:
        return StoryCourse.model_validate(content)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "malformed_course_file",
                "message": "The course file does not match story-course/1",
                "detail": str(exc)[:2000],
            },
        )


#: Slugs the story generator owns: ``lesson-{unit hex}-{lang}`` (a chapter)
#: and ``module-{module hex}-{lang}`` (a module story).
_RESERVED_SLUG_PREFIXES = ("lesson-", "module-")


def _is_generated(record: StoryCourseRecord) -> bool:
    """A module story or a lesson chapter: bound to a module, made by the generator."""
    return record.module_id is not None or record.module_unit_id is not None


def _reserved_slug(slug: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "error": "reserved_slug",
            "message": f"{slug!r} is a generated story's id; the 'lesson-' and 'module-'"
            " prefixes are reserved for story mode.",
        },
    )


def _to_list_item(record: StoryCourseRecord) -> StoryCourseListItem:
    content = record.content or {}
    return StoryCourseListItem(
        id=record.slug,
        course=record.course_label,
        unit=record.unit,
        week=record.week,
        title=record.title,
        languages=Languages.model_validate(record.languages),
        objective_count=len(content.get("objectives", [])),
        question_count=len(content.get("questions", [])),
        exercise_count=len(content.get("exercises", [])),
        max_points=record.max_points,
        is_valid=record.is_valid,
    )


@router.get(
    "",
    response_model=StoryCourseListResponse,
    summary="List published story weeks (the app's catalog.json)",
)
async def list_story_courses(
    course_id: uuid.UUID | None = None,
    week: int | None = None,
    include_drafts: bool = Query(False, description="Admins only; ignored otherwise"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> StoryCourseListResponse:
    """The weeks the app lists, newest week first.

    Only published weeks are visible unless an admin asks for drafts. Generated
    stories (a module story and its lesson chapters, both bound to a module)
    are not catalog weeks: each is reached from its own module, through its
    gate, so they are left out.
    """
    stmt = select(StoryCourseRecord).where(
        StoryCourseRecord.module_id.is_(None), StoryCourseRecord.module_unit_id.is_(None)
    )
    is_admin = current_user.role in _ADMIN_ROLES
    if not (include_drafts and is_admin):
        stmt = stmt.where(StoryCourseRecord.status == "published")
    if course_id is not None:
        stmt = stmt.where(StoryCourseRecord.course_id == course_id)
    if week is not None:
        stmt = stmt.where(StoryCourseRecord.week == week)

    rows = (await db.execute(stmt.order_by(StoryCourseRecord.week.desc()))).scalars().all()
    total = len(rows)
    start = (page - 1) * limit
    page_rows = rows[start : start + limit]

    return StoryCourseListResponse(
        items=[_to_list_item(row) for row in page_rows],
        total=total,
    )


# -- Story mode: generation dedup ---------------------------------------------

_FINISHED_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})

#: Every generated story is per-learner gated content: never in a shared cache.
_PRIVATE_NO_STORE = "private, no-store"

#: How long a dispatched module story generation is remembered for a (module,
#: language), so concurrent first views share one task: the task's hard limit
#: plus slack (1320 s), from the dispatch and again from the moment the task
#: starts (it re-arms the key), so a long queue wait never shortens its run's
#: cover. It stays under the broker's 3600 s visibility timeout and the
#: result backend's expiry, so a key never outlives what it names.
_MODULE_STORY_DISPATCH_TTL_S = MODULE_STORY_DISPATCH_TTL_S


async def _release_dispatch_key(key: str, task_id: str) -> None:
    """Delete the dedup key only while it still holds ``task_id`` (compare-and-delete)."""
    from app.infrastructure.cache.redis import redis_client

    await redis_client.eval(RELEASE_IF_OWNER_SCRIPT, 1, key, task_id)


async def _in_flight_story_task(key: str, *, release_finished: bool = True) -> str | None:
    """The task already generating this story, if it has not finished.

    While the key exists the task counts as alive, ``PENDING`` included: a
    queued task can wait longer than any stall threshold, and a just-claimed
    key is ``PENDING`` with no dispatch marker until the dispatch completes.
    The key's TTL (the task's hard limit plus slack) is what bounds a task
    that was lost. Only a finished task (SUCCESS, FAILURE, REVOKED) is
    replaced, and its key is released with a compare-and-delete, so a key
    another request has since claimed is never removed. A reader that only
    reports (``release_finished=False``) leaves the key to the next dispatch.
    """
    from app.infrastructure.cache.redis import redis_client

    task_id = await redis_client.get(key)
    if not task_id:
        return None
    if AsyncResult(task_id).state not in _FINISHED_STATES:
        return task_id
    if release_finished:
        await _release_dispatch_key(key, task_id)
    return None


async def dispatch_module_story_generation(
    *,
    module_id: uuid.UUID,
    language: str,
    country: str,
    level: int,
    force_regenerate: bool,
) -> str:
    """Start (or join) the generation of one module story; returns the task id.

    Shared by ``GET /story-courses/module/{module_id}`` and the operators'
    script (``scripts/generate_lesson_stories.py``), so both join the same
    task. The first view claims a short-lived Redis key (SET NX, the pattern
    the country backfill uses) holding the task id; concurrent views get that
    same id to poll instead of dispatching a second, paid, generation. The
    task releases the key when it ends (compare-and-delete on its own id).
    Fails open: without Redis, every view dispatches, and the task itself
    returns the story another one already stored (its chapters are cached).

    Joined clients poll ``GET /content/status/{task_id}``, which reports a task
    still PENDING after its stall threshold as failed. A story task can
    legitimately wait that long (it is rate limited), and the dedup here keeps
    joining it, so the task is vouched for (``vouch_while_owned``) before its
    key is claimed: the status endpoint answers ``pending`` for as long as the
    key names the task, exactly as long as this dedup treats it as alive.
    """
    from app.infrastructure.cache.redis import redis_client

    key = module_story_dispatch_key(module_id, language)
    task_id = str(uuid.uuid4())
    claimed = False
    try:
        running = await _in_flight_story_task(key)
        if running:
            return running
        # Before the claim, so a request that joins right after it never sees
        # an unvouched task. Harmless if the claim is lost: no key names this id.
        await vouch_while_owned(task_id, key, _MODULE_STORY_DISPATCH_TTL_S)
        claimed = bool(
            await redis_client.set(key, task_id, nx=True, ex=_MODULE_STORY_DISPATCH_TTL_S)
        )
        if not claimed:
            winner = await redis_client.get(key)
            if winner:
                return winner
            # The holder finished and released the key in between: claim once more.
            claimed = bool(
                await redis_client.set(key, task_id, nx=True, ex=_MODULE_STORY_DISPATCH_TTL_S)
            )
            if not claimed:
                winner = await redis_client.get(key)
                if winner:
                    return winner
    except Exception as exc:
        logger.warning("Story dispatch dedup unavailable (dispatching)", error=str(exc))

    try:
        generate_module_story_task.apply_async(
            args=[str(module_id), language, country, level, force_regenerate],
            kwargs={"dedup_key": key},
            task_id=task_id,
        )
    except Exception:
        # Nothing was queued: a key left pointing at this id would make every
        # view poll a task that does not exist until the key expires.
        if claimed:
            try:
                await _release_dispatch_key(key, task_id)
            except Exception as exc:
                logger.warning("Story dispatch key not released", error=str(exc))
        raise
    await mark_task_dispatched(task_id)
    logger.info(
        "Module story generation dispatched",
        module_id=str(module_id),
        language=language,
        force_regenerate=force_regenerate,
        task_id=task_id,
    )
    return task_id


# -- Story art (#2675) ----------------------------------------------------------


async def dispatch_story_art_generation(course_id: uuid.UUID) -> str | None:
    """Start (or join) the course's art run; its task id, or None when none was started.

    One run per course at a time, through the same claim-a-Redis-key dedup as
    the story dispatch (the task re-arms the key when it starts and releases
    it when it ends). Unlike the story dispatch it fails *closed*: without
    Redis nothing is dispatched, because every view would otherwise start a
    paid run. The art then stays ``pending`` until Redis is back.
    """
    from app.infrastructure.cache.redis import redis_client

    key = story_art_dispatch_key(course_id)
    task_id = str(uuid.uuid4())
    try:
        running = await _in_flight_story_task(key)
        if running:
            return running
        if not await redis_client.set(key, task_id, nx=True, ex=STORY_ART_DISPATCH_TTL_S):
            # Another view claimed it in between: that one dispatches.
            return await redis_client.get(key)
    except Exception as exc:
        logger.warning("Story art dispatch dedup unavailable (not dispatched)", error=str(exc))
        return None

    try:
        generate_story_art.apply_async(
            args=[str(course_id)], kwargs={"dedup_key": key}, task_id=task_id
        )
    except Exception as exc:
        # Nothing was queued: free the key so the next view can dispatch.
        try:
            await _release_dispatch_key(key, task_id)
        except Exception as release_exc:
            logger.warning("Story art dispatch key not released", error=str(release_exc))
        logger.warning("Story art dispatch failed", course_id=str(course_id), error=str(exc))
        return None
    logger.info("Story art generation dispatched", course_id=str(course_id), task_id=task_id)
    return task_id


async def _story_art(db: AsyncSession, record: StoryCourseRecord, content: dict) -> dict:
    """The ``art`` map for a story served from ``record`` (contract #2672).

    ``none`` when the document has no looks (an old story) or no course to
    hold its art. Otherwise the ready images' URLs; when some are missing or
    stale for the document's looks, the course's art run is dispatched
    (deduplicated) and the map says ``pending`` or ``partial``. Never waits
    for a drawing, and never fails the story: on any error the story is
    served with a ``pending`` map and nothing dispatched.
    """
    items = collect_looks([content])
    course_id = getattr(record, "course_id", None)
    if not items or course_id is None:
        return empty_art("none")
    try:
        rows = await load_art_rows(db, course_id)
    except Exception as exc:
        logger.warning("Story art unavailable", course_id=str(course_id), error=str(exc))
        with contextlib.suppress(Exception):
            await db.rollback()
        return empty_art("pending")
    art_map = build_art_map(items, rows, document_updated_at=getattr(record, "updated_at", None))
    if art_map.outstanding:
        try:
            await dispatch_story_art_generation(course_id)
        except Exception as exc:
            logger.warning("Story art not dispatched", course_id=str(course_id), error=str(exc))
    return art_map.art


async def _served(db: AsyncSession, record: StoryCourseRecord) -> dict:
    """The stored document as served: a copy with the ``art`` map (never stored)."""
    content = record.content if isinstance(record.content, dict) else {}
    return {**content, "art": await _story_art(db, record, content)}


# -- Module story mode --------------------------------------------------------


async def _resolve_module(db: AsyncSession, module_id: str) -> uuid.UUID:
    """The module's UUID, or a 404 ``module_not_found``.

    Only a UUID names a module here: a module code (``M01``) is shared by
    every course, so it could not say which module's story is meant. A value
    that is not a UUID is refused without a query.
    """
    try:
        module_uuid = uuid.UUID(module_id)
    except ValueError:
        module_uuid = None
    if module_uuid is not None:
        found = (await db.execute(select(Module.id).where(Module.id == module_uuid))).first()
        if found is not None:
            return module_uuid
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "module_not_found", "message": f"No module {module_id!r}"},
    )


def _has_lesson(units: Sequence[StoryUnit]) -> bool:
    return any(unit.role == "lesson" for unit in units)


# Declared before ``/{slug}``: a slug never contains "/", so ``/{slug}`` could
# not swallow these paths anyway, but the order keeps that true even if the
# slug route ever becomes a ``{slug:path}``.
@router.get(
    "/module/{module_id}",
    response_model=dict,
    summary="A module's story mode, generated on first open",
    responses={
        202: {"description": "Generating; poll GET /api/v1/content/status/{task_id}"},
        403: {"description": "A subscription is required (subscription_required)"},
        404: {
            "description": "Story mode disabled (story_mode_disabled), unknown module"
            " (module_not_found), a module with no lesson unit (no_story_content), or"
            " generate=false with no fresh cached story (story_not_cached)"
        },
        409: {"description": "The story could not be made valid (story_unavailable)"},
    },
)
async def get_module_story(
    module_id: str,
    language: str = Query("fr", pattern="^(fr|en)$"),
    level: int = Query(1, ge=1, le=4, description="Preferred source lesson level"),
    country: str = Query("CI", description="Preferred source lesson country"),
    force_regenerate: bool = Query(
        False, description="Admins only, with generate=true; remakes every chapter"
    ),
    generate: bool = Query(
        True,
        description="false: answer from the cache only (404 story_not_cached) and never"
        " start a generation, e.g. for an offline module download",
    ),
    current_user: AuthenticatedUser = Depends(require_subscription_or_free_module),
    db=Depends(get_db_session),
) -> JSONResponse:
    """The story-course/1 week telling this module, for the learner as hero.

    One chapter per unit, in teaching order: a lesson's chapter is its story,
    and a quiz or case-study unit is a checkpoint scene that sends the learner
    to its page.

    * **200** — the cached story, valid and in step with the module's units,
      lessons and quizzes. Strings carry the ``{child}`` placeholder; the
      client substitutes the learner's first name. It carries the ``art`` map
      (contract #2672), added on the way out and never stored; when art is
      missing or stale the course's art run is started (deduplicated) and the
      map says ``pending`` or ``partial``.
    * **202** — ``{"status": "generating", "task_id": ...}``: the story is
      being generated (now, or by a request that came first); a first open
      that must generate lessons and quizzes too can take several minutes.
      Poll ``GET /api/v1/content/status/{task_id}``, then fetch this again.
    * **409** — ``story_unavailable``: the story could not reach zero
      validator errors; retried when a lesson, quiz or unit changes.
    * **404** — ``story_mode_disabled`` (answered before any query),
      ``module_not_found`` (an unknown module, or an id that is not a UUID),
      ``no_story_content`` (the module has no lesson unit), or, with
      ``generate=false``, ``story_not_cached`` (no fresh cached story;
      nothing is dispatched).
    * **403** — ``subscription_required``: the story tells every unit of the
      module, so it needs a subscription unless every unit is free.
    """
    if not story_mode_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_mode_disabled", "message": "Story mode is turned off"},
        )

    module_uuid = await _resolve_module(db, module_id)
    units = await load_story_units(db, module_uuid)
    if not _has_lesson(units):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_story_content",
                "message": "This module has no lesson to tell as a story.",
            },
        )
    force = force_regenerate and generate and current_user.role in _ADMIN_ROLES

    record = await find_module_story(db, module_uuid, language)
    if record is not None and not force and await module_story_is_fresh(db, record, units=units):
        if record.is_valid and record.status == "published":
            return JSONResponse(
                content=await _served(db, record),
                status_code=status.HTTP_200_OK,
                headers={"Cache-Control": "private, no-cache"},
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "story_unavailable",
                "message": "The story of this module could not be prepared. Read its lessons"
                " instead; the story is retried when a lesson or quiz changes.",
            },
        )

    if not generate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "story_not_cached",
                "message": "No story is ready for this module yet; none was started.",
            },
        )

    task_id = await dispatch_module_story_generation(
        module_id=module_uuid,
        language=language,
        country=canonicalize_country(country),
        level=level,
        force_regenerate=force,
    )
    return JSONResponse(
        content={
            "status": "generating",
            "task_id": task_id,
            "message": "Story is being generated",
        },
        status_code=status.HTTP_202_ACCEPTED,
    )


class ModuleStoryStatus(BaseModel):
    """Where a module's story stands, without downloading it."""

    state: Literal["ready", "generating", "not_ready", "unavailable", "disabled"] = Field(
        description="ready: GET returns it (200). generating: a task is making it (poll"
        " task_id). not_ready: nothing is cached and nothing runs; GET starts it."
        " unavailable: it could not be made valid, or the module has no lesson."
        " disabled: story mode is turned off."
    )
    task_id: str | None = Field(None, description="The generating task (state generating)")
    chapters: int | None = Field(None, description="Its chapters, one per unit (state ready)")
    revision: str | None = Field(
        None, description="module_story.revision of the ready story; changes with any chapter"
    )
    access: Literal["ok", "subscription_required"] = Field(
        description="Whether this user may open it (GET answers 403 otherwise)"
    )


@router.get(
    "/module/{module_id}/status",
    response_model=ModuleStoryStatus,
    summary="Whether a module's story is ready, without downloading or starting it",
    responses={404: {"description": "Unknown module (module_not_found)"}},
)
async def get_module_story_status(
    module_id: str,
    response: Response,
    language: str = Query("fr", pattern="^(fr|en)$"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> ModuleStoryStatus:
    """The state of the module's story card. Never dispatches a generation.

    ``access`` is reported whatever the state, so the card can say "for
    subscribers" without a 403. ``generating`` comes from the same Redis key
    the dedup uses, so it names the very task a GET would join.
    """
    module_uuid = await _resolve_module(db, module_id)
    access: Literal["ok", "subscription_required"] = (
        "ok"
        if await module_story_access(db, current_user, module_uuid)
        else "subscription_required"
    )
    response.headers["Cache-Control"] = _PRIVATE_NO_STORE
    if not story_mode_enabled():
        return ModuleStoryStatus(state="disabled", access=access)

    units = await load_story_units(db, module_uuid)
    if not _has_lesson(units):
        return ModuleStoryStatus(state="unavailable", access=access)
    record = await find_module_story(db, module_uuid, language)
    if record is not None and await module_story_is_fresh(db, record, units=units):
        if not (record.is_valid and record.status == "published"):
            return ModuleStoryStatus(state="unavailable", access=access)
        content = record.content if isinstance(record.content, dict) else {}
        chapters = content.get("chapters")
        module_story = content.get("module_story")
        return ModuleStoryStatus(
            state="ready",
            chapters=len(chapters) if isinstance(chapters, list) else None,
            revision=(
                str(module_story["revision"])
                if isinstance(module_story, dict) and module_story.get("revision")
                else None
            ),
            access=access,
        )

    try:
        task_id = await _in_flight_story_task(
            module_story_dispatch_key(module_uuid, language), release_finished=False
        )
    except Exception as exc:
        logger.warning("Story dispatch state unavailable", error=str(exc))
        task_id = None
    if task_id:
        return ModuleStoryStatus(state="generating", task_id=task_id, access=access)
    return ModuleStoryStatus(state="not_ready", access=access)


@router.get(
    "/{slug}",
    response_model=dict,
    summary="Download one week whole, for offline play",
    responses={404: {"description": "Week not found or not published"}},
)
async def get_story_course(
    slug: str,
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> dict:
    """Return the authored course file as stored, plus its ``art`` map.

    ``art`` (contract #2672) is added on the way out, never stored: the URLs of
    the course's ready character poses and backdrops, with a ``status``. When
    the document's looks have art missing or stale, the course's art run is
    started (deduplicated) and the status says ``pending`` or ``partial``.

    The player needs the whole document in one request: it caches the week in
    IndexedDB and then runs with no network. Responses are gzipped by the
    global compression middleware.

    Generated stories (rows bound to a module: a module story or one of its
    lesson chapters) are not served here to learners: their slugs are
    predictable, and only ``GET /story-courses/module/{module_id}`` applies
    the module's subscription gate, the story-mode switch and the staleness
    check. Admins may read one, never through a shared cache.
    """
    record = (
        await db.execute(select(StoryCourseRecord).where(StoryCourseRecord.slug == slug))
    ).scalar_one_or_none()

    is_admin = current_user.role in _ADMIN_ROLES
    is_generated = record is not None and _is_generated(record)
    if (
        record is None
        or (record.status != "published" and not is_admin)
        or (is_generated and not is_admin)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_course_not_found", "message": f"No week {slug!r}"},
        )

    served = await _served(db, record)
    if is_generated:
        response.headers["Cache-Control"] = _PRIVATE_NO_STORE
    elif record.status != "published":
        response.headers["Cache-Control"] = "no-store"
    elif served["art"]["status"] in ("pending", "partial"):
        # Its art is still being drawn: a shared cache would keep serving the
        # placeholders for an hour.
        response.headers["Cache-Control"] = "public, no-cache"
    else:
        # Published weeks are immutable in practice but can be corrected, so
        # allow a short cache rather than marking them immutable for a year.
        response.headers["Cache-Control"] = "public, max-age=3600"
    return served


@router.post(
    "/validate",
    response_model=ValidationReport,
    summary="Run the Appendix C checks without saving",
)
async def validate_course_file(
    request: SaveStoryCourseRequest,
    current_user: AuthenticatedUser = Depends(_ADMIN),
    db=Depends(get_db_session),
) -> ValidationReport:
    """Validate an authored file in place.

    This is the authoring loop: paste a generated course file, see every error
    with its path, fix, repeat — without writing anything.
    """
    report = validate_story_course(_parse(request.content))
    logger.info(
        "Story course validated via API",
        errors=len(report.errors),
        warnings=len(report.warnings),
        user_id=str(current_user.id),
    )
    return report


@router.post(
    "",
    response_model=SaveStoryCourseResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or replace a week",
)
async def save_story_course(
    request: SaveStoryCourseRequest,
    current_user: AuthenticatedUser = Depends(_ADMIN),
    db=Depends(get_db_session),
) -> SaveStoryCourseResponse:
    """Upsert a week by its format ``id``, validating before it is stored.

    An invalid file is still saved as a draft so the author can keep working on
    it, but publishing is refused until the validator is clean. The ids of
    generated stories (``lesson-…``, ``module-…``) are refused with 422
    ``reserved_slug``: the generator alone writes those rows.
    """
    course = _parse(request.content)
    if course.id.startswith(_RESERVED_SLUG_PREFIXES):
        raise _reserved_slug(course.id)
    report = validate_story_course(course)

    if request.publish and not report.ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "cannot_publish_invalid_course",
                "message": (
                    f"{len(report.errors)} validator error(s) must be fixed before publishing"
                ),
                "errors": [issue.model_dump() for issue in report.errors],
            },
        )

    record = await upsert_story_course(
        db,
        course=course,
        content=request.content,
        report=report,
        course_id=request.course_id,
        publish=request.publish,
        created_by=_actor_id(current_user),
    )
    await db.commit()
    await db.refresh(record)

    logger.info(
        "Story course saved",
        slug=record.slug,
        week=record.week,
        status=record.status,
        is_valid=record.is_valid,
        user_id=str(current_user.id),
    )
    return SaveStoryCourseResponse(
        id=record.id,
        slug=record.slug,
        status=record.status,
        is_valid=record.is_valid,
        validation=report,
    )


@router.post(
    "/{slug}/publish",
    response_model=SaveStoryCourseResponse,
    summary="Publish a stored week",
    responses={409: {"description": "The week still has validator errors"}},
)
async def publish_story_course(
    slug: str,
    current_user: AuthenticatedUser = Depends(_ADMIN),
    db=Depends(get_db_session),
) -> SaveStoryCourseResponse:
    """Re-validate the stored file and publish it only if it is clean.

    A generated story is refused (422 ``reserved_slug``): the generator
    publishes it only when it passes its own checks too, which the validator
    alone does not repeat.
    """
    record = (
        await db.execute(select(StoryCourseRecord).where(StoryCourseRecord.slug == slug))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_course_not_found", "message": f"No week {slug!r}"},
        )
    if _is_generated(record):
        raise _reserved_slug(slug)

    # Re-validate rather than trusting the stored flag: the engine or the
    # validator may have moved on since the file was saved.
    report = validate_story_course(_parse(record.content))
    record.is_valid = report.ok
    record.validation_report = report.model_dump(mode="json")
    record.max_points = report.checks.max_points

    if not report.ok:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "cannot_publish_invalid_course",
                "message": (
                    f"{len(report.errors)} validator error(s) must be fixed before publishing"
                ),
                "errors": [issue.model_dump() for issue in report.errors],
            },
        )

    record.status = "published"
    await db.commit()
    await db.refresh(record)
    logger.info("Story course published", slug=slug, user_id=str(current_user.id))
    return SaveStoryCourseResponse(
        id=record.id,
        slug=record.slug,
        status=record.status,
        is_valid=record.is_valid,
        validation=report,
    )
