"""Endpoints for ``story-course/1`` course files.

Learners read the catalog and download a week whole, because the player keeps
it in IndexedDB and runs offline. Authors validate and publish through the
admin routes, and a week can only reach ``published`` with zero validator
errors — the format's own rule, enforced here rather than trusted.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.api.v1.schemas.story_course import (
    Languages,
    StoryCourse,
    StoryCourseListItem,
    StoryCourseListResponse,
    ValidationReport,
)
from app.domain.models.story_course import StoryCourseRecord
from app.domain.models.user import UserRole
from app.domain.services.story_course_validator import validate_story_course

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

    Only published weeks are visible unless an admin asks for drafts.
    """
    stmt = select(StoryCourseRecord)
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

    record = (
        await db.execute(select(StoryCourseRecord).where(StoryCourseRecord.slug == course.id))
    ).scalar_one_or_none()
    if record is None:
        record = StoryCourseRecord(
            id=uuid.uuid4(), slug=course.id, created_by=_actor_id(current_user)
        )
        db.add(record)

    record.course_id = request.course_id
    record.course_label = course.course
    record.unit = course.unit
    record.week = course.week
    record.title = dict(course.title)
    record.languages = course.languages.model_dump()
    record.format_version = course.format
    record.content = request.content
    record.is_valid = report.ok
    record.validation_report = report.model_dump(mode="json")
    record.max_points = report.checks.max_points
    if request.publish:
        record.status = "published"
    elif record.status != "published":
        record.status = "draft"

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
