"""Course bundle export — create, poll, list, download, and delete ZIP packages."""

from __future__ import annotations

import uuid
from typing import Literal

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.course import Course
from app.domain.models.course_bundle import CourseBundle
from app.domain.models.user import UserRole
from app.infrastructure.storage.s3 import S3StorageService
from app.tasks.course_bundle import generate_course_bundle_task

logger = get_logger(__name__)

router = APIRouter(tags=["Course Bundles"])

_ADMIN_ROLES = (UserRole.admin, UserRole.sub_admin, UserRole.expert)


# ── Schemas ───────────────────────────────────────────────────────────


class BundleCreateRequest(BaseModel):
    language: Literal["fr", "en"]
    level: int = Field(default=1, ge=1, le=4)
    country: str = Field(default="SN", max_length=4)


class BundleCreatedResponse(BaseModel):
    bundle_id: str
    task_id: str
    status: str


class BundleStatusResponse(BaseModel):
    bundle_id: str
    status: str
    progress: int | None = None
    current_file: str | None = None
    download_url: str | None = None
    file_count: int | None = None
    file_size_bytes: int | None = None
    error_message: str | None = None


class BundleListItem(BaseModel):
    bundle_id: str
    course_id: str
    course_title: str
    language: str
    level: int
    status: str
    file_count: int | None
    file_size_bytes: int | None
    created_at: str
    completed_at: str | None
    download_url: str | None
    error_message: str | None


# ── Helpers ───────────────────────────────────────────────────────────


async def _get_course_or_404(
    course_id: uuid.UUID, session: AsyncSession
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


def _expert_owns_course(user: AuthenticatedUser, course: Course) -> bool:
    return str(course.created_by) == user.id


def _guard_expert(user: AuthenticatedUser, course: Course) -> None:
    if user.role == UserRole.expert.value and not _expert_owns_course(
        user, course
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Experts can only bundle their own courses",
        )


def _celery_progress(task_id: str) -> tuple[int, str | None]:
    """Return (progress 0-100, current_file) from Celery state."""
    if not task_id:
        return 0, None
    try:
        res = AsyncResult(task_id)
        if res.state == "PROGRESS" and isinstance(res.info, dict):
            return res.info.get("progress", 0), res.info.get("current_file")
    except Exception:
        pass
    return 0, None


def _bundle_download_url(bundle: CourseBundle, user: AuthenticatedUser) -> str | None:
    """Return the API download URL (requires auth) when the bundle is ready."""
    if bundle.status != "ready":
        return None
    return f"/api/v1/admin/bundles/{bundle.id}/download"


def _bundle_to_status(
    bundle: CourseBundle, user: AuthenticatedUser
) -> BundleStatusResponse:
    progress, current_file = 0, None
    if bundle.status == "generating" and bundle.task_id:
        progress, current_file = _celery_progress(bundle.task_id)
    return BundleStatusResponse(
        bundle_id=str(bundle.id),
        status=bundle.status,
        progress=progress,
        current_file=current_file,
        download_url=_bundle_download_url(bundle, user),
        file_count=bundle.file_count,
        file_size_bytes=bundle.file_size_bytes,
        error_message=bundle.error_message,
    )


# ── Endpoints ─────────────────────────────────────────────────────────


@router.post(
    "/admin/courses/{course_id}/bundle",
    response_model=BundleCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_course_bundle(
    course_id: uuid.UUID,
    body: BundleCreateRequest,
    current_user: AuthenticatedUser = Depends(
        require_role(*_ADMIN_ROLES)
    ),
    session: AsyncSession = Depends(get_db_session),
) -> BundleCreatedResponse:
    """Trigger bundle generation for a course. Returns immediately with a bundle_id."""
    course = await _get_course_or_404(course_id, session)
    _guard_expert(current_user, course)

    bundle = CourseBundle(
        course_id=course_id,
        requested_by=uuid.UUID(current_user.id),
        language=body.language,
        level=body.level,
        country=body.country,
        status="pending",
    )
    session.add(bundle)
    await session.flush()  # assign bundle.id before dispatching task

    task = generate_course_bundle_task.delay(str(bundle.id))
    bundle.task_id = task.id
    await session.commit()

    logger.info(
        "bundle.created",
        bundle_id=str(bundle.id),
        course_id=str(course_id),
        language=body.language,
        task_id=task.id,
    )
    return BundleCreatedResponse(
        bundle_id=str(bundle.id),
        task_id=task.id,
        status="pending",
    )


@router.get(
    "/admin/courses/{course_id}/bundle/status",
    response_model=BundleStatusResponse,
)
async def get_bundle_status(
    course_id: uuid.UUID,
    bundle_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(
        require_role(*_ADMIN_ROLES)
    ),
    session: AsyncSession = Depends(get_db_session),
) -> BundleStatusResponse:
    """Poll the status of a bundle job."""
    course = await _get_course_or_404(course_id, session)
    _guard_expert(current_user, course)

    bundle = await session.get(CourseBundle, bundle_id)
    if bundle is None or bundle.course_id != course_id:
        raise HTTPException(status_code=404, detail="Bundle not found")

    return _bundle_to_status(bundle, current_user)


@router.get(
    "/admin/bundles",
    response_model=list[BundleListItem],
)
async def list_bundles(
    course_id: uuid.UUID | None = None,
    bundle_status: str | None = None,
    limit: int = 50,
    current_user: AuthenticatedUser = Depends(
        require_role(*_ADMIN_ROLES)
    ),
    session: AsyncSession = Depends(get_db_session),
) -> list[BundleListItem]:
    """List course bundles.

    Admin/sub_admin see all bundles. Experts see only bundles for their
    own courses.
    """
    q = select(CourseBundle, Course).join(
        Course, Course.id == CourseBundle.course_id
    )

    if current_user.role == UserRole.expert.value:
        q = q.where(
            Course.created_by == uuid.UUID(current_user.id)
        )

    if course_id is not None:
        q = q.where(CourseBundle.course_id == course_id)

    if bundle_status is not None:
        q = q.where(CourseBundle.status == bundle_status)

    q = q.order_by(CourseBundle.created_at.desc()).limit(limit)
    rows = (await session.execute(q)).all()

    items: list[BundleListItem] = []
    for bundle, course in rows:
        lang = bundle.language
        course_title = (
            course.title_fr if lang == "fr" else course.title_en
        )
        items.append(
            BundleListItem(
                bundle_id=str(bundle.id),
                course_id=str(bundle.course_id),
                course_title=course_title,
                language=bundle.language,
                level=bundle.level,
                status=bundle.status,
                file_count=bundle.file_count,
                file_size_bytes=bundle.file_size_bytes,
                created_at=bundle.created_at.isoformat(),
                completed_at=(
                    bundle.completed_at.isoformat()
                    if bundle.completed_at
                    else None
                ),
                download_url=_bundle_download_url(bundle, current_user),
                error_message=bundle.error_message,
            )
        )
    return items


@router.get("/admin/bundles/{bundle_id}/download")
async def download_bundle(
    bundle_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(
        require_role(*_ADMIN_ROLES)
    ),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Stream the ZIP archive from MinIO.

    Experts can only download bundles for their own courses.
    """
    result = await session.execute(
        select(CourseBundle, Course)
        .join(Course, Course.id == CourseBundle.course_id)
        .where(CourseBundle.id == bundle_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Bundle not found")

    bundle, course = row
    _guard_expert(current_user, course)

    if bundle.status != "ready" or not bundle.storage_key:
        raise HTTPException(
            status_code=409, detail="Bundle is not ready yet"
        )

    storage = S3StorageService()
    try:
        data = await storage.download_bytes(bundle.storage_key)
    except Exception as exc:
        logger.error(
            "bundle.download_failed",
            bundle_id=str(bundle_id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=502, detail="Could not retrieve bundle from storage"
        ) from exc

    lang = bundle.language
    slug = course.slug or str(course.id)
    filename = f"{slug}_{lang}.zip"

    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.delete(
    "/admin/bundles/{bundle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_bundle(
    bundle_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(
        require_role(*_ADMIN_ROLES)
    ),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a bundle and its MinIO object."""
    result = await session.execute(
        select(CourseBundle, Course)
        .join(Course, Course.id == CourseBundle.course_id)
        .where(CourseBundle.id == bundle_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Bundle not found")

    bundle, course = row
    _guard_expert(current_user, course)

    if bundle.storage_key:
        try:
            storage = S3StorageService()
            await storage.delete_object(bundle.storage_key)
        except Exception as exc:
            logger.warning(
                "bundle.delete_storage_failed",
                bundle_id=str(bundle_id),
                error=str(exc),
            )

    await session.delete(bundle)
    await session.commit()
