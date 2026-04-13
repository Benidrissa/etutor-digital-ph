"""Organization reporting endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.domain.services.org_reporting_service import OrgReportingService
from app.domain.services.organization_service import OrganizationService

router = APIRouter(
    prefix="/organizations/{org_id}/reports",
    tags=["Organization Reports"],
)

_report_svc = OrgReportingService()
_org_svc = OrganizationService()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OrgSummaryResponse(BaseModel):
    total_codes: int
    active_codes: int
    total_redemptions: int
    unique_learners: int
    avg_completion_pct: float


class LearnerProgressItem(BaseModel):
    user_id: str
    name: str
    email: str | None
    activated_at: str | None
    courses_enrolled: int
    avg_completion_pct: float


class CodeUsageItem(BaseModel):
    code_id: str
    code: str
    course_name: str | None
    curriculum_id: str | None
    max_uses: int | None
    times_used: int
    is_active: bool
    created_at: str


class CourseStatsResponse(BaseModel):
    course_id: str
    enrolled: int
    avg_completion_pct: float
    completed: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=OrgSummaryResponse)
async def get_org_summary(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OrgSummaryResponse:
    """Get aggregate dashboard stats for the organization."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    data = await _report_svc.get_org_summary(db, org_id)
    return OrgSummaryResponse(**data)


@router.get("/learners", response_model=list[LearnerProgressItem])
async def get_learner_progress(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    curriculum_id: uuid.UUID | None = Query(None),
    course_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[LearnerProgressItem]:
    """Get per-learner progress for the organization."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    data = await _report_svc.get_learner_progress(
        db,
        org_id,
        curriculum_id=curriculum_id,
        course_id=course_id,
        limit=limit,
        offset=offset,
    )
    return [LearnerProgressItem(**item) for item in data]


@router.get("/codes", response_model=list[CodeUsageItem])
async def get_code_usage(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[CodeUsageItem]:
    """Get per-code usage stats for the organization."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    data = await _report_svc.get_code_usage_report(db, org_id)
    return [CodeUsageItem(**item) for item in data]


@router.get("/courses/{course_id}", response_model=CourseStatsResponse)
async def get_course_stats(
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CourseStatsResponse:
    """Get course completion stats for org learners."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    data = await _report_svc.get_course_completion_stats(db, org_id, course_id)
    return CourseStatsResponse(**data)


@router.get("/export")
async def export_csv(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Export learner progress as CSV."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    csv_content = await _report_svc.export_csv(db, org_id)
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=org_learners.csv"},
    )
