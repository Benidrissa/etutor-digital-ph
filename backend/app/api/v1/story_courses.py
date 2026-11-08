"""Endpoints for ``story-course/1`` course files.

Learners read the catalog and download a week whole, because the player keeps
it in IndexedDB and runs offline. Authors validate and publish through the
admin routes, and a week can only reach ``published`` with zero validator
errors — the format's own rule, enforced here rather than trusted.

Every lesson unit also has a story mode (``GET /story-courses/unit/...``):
generated from that unit's lesson and quiz the first time a learner opens it,
then cached like lessons and quizzes are.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import (
    AuthenticatedUser,
    get_current_user,
    require_role,
    require_subscription_or_first_unit,
)
from app.api.v1._task_status import TASK_STALL_THRESHOLD_S
from app.api.v1._task_status import dispatched_at as task_dispatched_at
from app.api.v1._task_status import mark_dispatched as mark_task_dispatched
from app.api.v1.schemas.story_course import (
    Languages,
    StoryCourse,
    StoryCourseListItem,
    StoryCourseListResponse,
    ValidationReport,
)
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.story_course import StoryCourseRecord
from app.domain.models.user import UserRole
from app.domain.services.country_utils import canonicalize_country
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import (
    find_unit_story,
    story_mode_enabled,
    story_sources_are_fresh,
    upsert_story_course,
)
from app.tasks.content_generation import POLL_HARD_LIMIT, generate_story_task

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

    Only published weeks are visible unless an admin asks for drafts. Lesson
    stories are not catalog weeks — each is reached from its own lesson — so
    they are left out.
    """
    stmt = select(StoryCourseRecord).where(StoryCourseRecord.module_unit_id.is_(None))
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


# -- Lesson story mode --------------------------------------------------------

#: How long a dispatched story generation is remembered for a (unit, language),
#: so concurrent first views share one task: the task's hard limit plus slack.
_STORY_DISPATCH_TTL_S = POLL_HARD_LIMIT + 60
_FINISHED_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})


def _story_dispatch_key(module_unit_id: uuid.UUID, language: str) -> str:
    return f"story_dispatch:{module_unit_id}:{language}"


async def _in_flight_story_task(key: str) -> str | None:
    """The task already generating this story, if it is still alive.

    A finished task, or one Celery never picked up (no dispatch marker, or a
    marker older than the stall threshold — the same rule as
    ``/content/status``), no longer counts and the key is cleared.
    """
    from app.infrastructure.cache.redis import redis_client

    task_id = await redis_client.get(key)
    if not task_id:
        return None
    state = AsyncResult(task_id).state
    alive = state not in _FINISHED_STATES
    if alive and state == "PENDING":
        marker = await task_dispatched_at(task_id)
        alive = marker is not None and (
            (datetime.now(tz=UTC) - marker).total_seconds() <= TASK_STALL_THRESHOLD_S
        )
    if alive:
        return task_id
    await redis_client.delete(key)
    return None


async def _dispatch_story_generation(
    *,
    module_id: uuid.UUID,
    unit_id: str,
    module_unit_id: uuid.UUID,
    language: str,
    country: str,
    level: int,
    force_regenerate: bool,
) -> str:
    """Start (or join) the generation of one unit story; returns the task id.

    The first view claims a short-lived Redis key (SET NX, the pattern the
    country backfill uses) holding the task id; concurrent views get that
    same id to poll instead of dispatching a second, paid, generation. Fails
    open: without Redis, every view dispatches and the task itself returns
    the story another one already stored.
    """
    from app.infrastructure.cache.redis import redis_client

    key = _story_dispatch_key(module_unit_id, language)
    task_id = str(uuid.uuid4())
    try:
        running = await _in_flight_story_task(key)
        if running:
            return running
        if not await redis_client.set(key, task_id, nx=True, ex=_STORY_DISPATCH_TTL_S):
            winner = await redis_client.get(key)
            if winner:
                return winner
    except Exception as exc:
        logger.warning("Story dispatch dedup unavailable (dispatching)", error=str(exc))

    generate_story_task.apply_async(
        args=[str(module_id), unit_id, language, country, level, force_regenerate],
        task_id=task_id,
    )
    await mark_task_dispatched(task_id)
    logger.info(
        "Story generation dispatched",
        module_id=str(module_id),
        unit_id=unit_id,
        language=language,
        task_id=task_id,
    )
    return task_id


async def _resolve_unit(db, module_id: str, unit_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    """``(module uuid, module_unit uuid)``, or a 404."""
    from app.api.v1.content import _resolve_module_id

    try:
        resolved_module_id = await _resolve_module_id(module_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "module_not_found", "message": str(exc)},
        )
    module_unit_id = (
        await db.execute(
            select(ModuleUnit.id).where(
                ModuleUnit.module_id == resolved_module_id, ModuleUnit.unit_number == unit_id
            )
        )
    ).scalar_one_or_none()
    if module_unit_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "unit_not_found",
                "message": f"Unit '{unit_id}' does not exist in this module.",
            },
        )
    return resolved_module_id, module_unit_id


# Declared before ``/{slug}``: a slug never contains "/", so ``/{slug}`` could
# not swallow this three-segment path anyway, but the order keeps that true
# even if the slug route ever becomes a ``{slug:path}``.
@router.get(
    "/unit/{module_id}/{unit_id}",
    response_model=dict,
    summary="A lesson's story mode, generated on first open",
    responses={
        202: {"description": "Generating; poll GET /api/v1/content/status/{task_id}"},
        404: {"description": "Unknown module or unit, or story mode disabled"},
        409: {"description": "The story could not be made valid (story_unavailable)"},
    },
)
async def get_unit_story(
    module_id: str,
    unit_id: str,
    language: str = Query("fr", pattern="^(fr|en)$"),
    level: int = Query(1, ge=1, le=4, description="Preferred source lesson level"),
    country: str = Query("CI", description="Preferred source lesson country"),
    force_regenerate: bool = Query(False, description="Admins only; ignored otherwise"),
    current_user: AuthenticatedUser = Depends(require_subscription_or_first_unit),
    db=Depends(get_db_session),
) -> JSONResponse:
    """The story-course/1 week telling this lesson, for the learner as hero.

    * **200** — the cached story, valid and still in step with the unit's
      lesson and quiz. Strings carry the ``{child}`` placeholder; the client
      substitutes the learner's first name.
    * **202** — ``{"status": "generating", "task_id": ...}``: the story is being
      generated (now, or by a request that came first). Poll
      ``GET /api/v1/content/status/{task_id}``, then fetch this again.
    * **409** — ``story_unavailable``: generation could not reach zero
      validator errors; retried when the lesson or quiz changes.

    Access follows the lesson's own gate (subscription, or a free unit).
    """
    if not story_mode_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_mode_disabled", "message": "Story mode is turned off"},
        )

    resolved_module_id, module_unit_id = await _resolve_unit(db, module_id, unit_id)
    force = force_regenerate and current_user.role in _ADMIN_ROLES

    record = await find_unit_story(db, module_unit_id, language)
    if record is not None and not force and await story_sources_are_fresh(db, record):
        if record.is_valid and record.status == "published":
            return JSONResponse(
                content=record.content,
                status_code=status.HTTP_200_OK,
                headers={"Cache-Control": "private, no-cache"},
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "story_unavailable",
                "message": "The story for this lesson could not be prepared. Read the lesson"
                " instead; the story is retried when the lesson changes.",
            },
        )

    task_id = await _dispatch_story_generation(
        module_id=resolved_module_id,
        unit_id=unit_id,
        module_unit_id=module_unit_id,
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
    """Return the authored course file exactly as stored.

    The player needs the whole document in one request: it caches the week in
    IndexedDB and then runs with no network. Responses are gzipped by the
    global compression middleware.
    """
    record = (
        await db.execute(select(StoryCourseRecord).where(StoryCourseRecord.slug == slug))
    ).scalar_one_or_none()

    is_admin = current_user.role in _ADMIN_ROLES
    if record is None or (record.status != "published" and not is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_course_not_found", "message": f"No week {slug!r}"},
        )

    # Published weeks are immutable in practice but can be corrected, so allow
    # a short cache rather than marking them immutable for a year.
    response.headers["Cache-Control"] = (
        "public, max-age=3600" if record.status == "published" else "no-store"
    )
    return record.content


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
    it, but publishing is refused until the validator is clean.
    """
    course = _parse(request.content)
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
    """Re-validate the stored file and publish it only if it is clean."""
    record = (
        await db.execute(select(StoryCourseRecord).where(StoryCourseRecord.slug == slug))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_course_not_found", "message": f"No week {slug!r}"},
        )

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
