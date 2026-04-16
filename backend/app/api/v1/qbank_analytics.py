"""Question bank analytics endpoints for org admins."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.domain.services.organization_service import OrganizationService
from app.domain.services.qbank_analytics_service import QBankAnalyticsService

router = APIRouter(prefix="/qbank", tags=["Question Bank Analytics"])

_analytics_svc = QBankAnalyticsService()
_org_svc = OrganizationService()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ScoreBucket(BaseModel):
    range: str
    count: int


class CategoryPassRate(BaseModel):
    category: str
    pass_rate: float
    correct: int
    total: int


class AttemptDataPoint(BaseModel):
    date: str
    count: int


class BankAnalyticsResponse(BaseModel):
    bank_id: str
    bank_title: str
    pass_score: float
    total_attempts: int
    unique_students: int
    avg_score: float
    pass_rate: float
    avg_time_per_question_sec: float | None
    score_distribution: list[ScoreBucket]
    category_pass_rates: list[CategoryPassRate]
    attempts_over_time: list[AttemptDataPoint]


class StudentSummary(BaseModel):
    user_id: str
    name: str
    email: str | None
    attempt_count: int
    best_score: float
    latest_score: float
    last_attempt_at: str | None


class AttemptRecord(BaseModel):
    attempt_id: str
    score: float
    passed: bool
    time_taken_sec: int | None
    attempted_at: str


class StudentProgressResponse(BaseModel):
    bank_id: str
    user_id: str
    attempt_count: int
    best_score: float | None
    latest_score: float | None
    improvement_trend: float | None
    attempt_history: list[AttemptRecord]
    weakest_categories: list[CategoryPassRate]


# ---------------------------------------------------------------------------
# Authorization helper
# ---------------------------------------------------------------------------


async def _require_admin(
    db: AsyncSession,
    bank_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Ensure the calling user is an admin/owner of the bank's org."""
    from app.domain.models.qbank import QuestionBank

    bank = await db.get(QuestionBank, bank_id)
    if bank is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank not found.")
    await _analytics_svc.require_org_admin(db, bank.organization_id, user_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/banks/{bank_id}/analytics", response_model=BankAnalyticsResponse)
async def get_bank_analytics(
    bank_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> BankAnalyticsResponse:
    """Aggregate analytics for a question bank. Org admin only."""
    await _require_admin(db, bank_id, uuid.UUID(current_user.id))
    data = await _analytics_svc.get_bank_analytics(db, bank_id)
    return BankAnalyticsResponse(**data)


@router.get("/banks/{bank_id}/students", response_model=list[StudentSummary])
async def get_bank_students(
    bank_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[StudentSummary]:
    """Student list with latest scores. Org admin only."""
    await _require_admin(db, bank_id, uuid.UUID(current_user.id))
    data = await _analytics_svc.get_bank_students(db, bank_id, limit=limit, offset=offset)
    return [StudentSummary(**item) for item in data]


@router.get("/banks/{bank_id}/students/{user_id}", response_model=StudentProgressResponse)
async def get_student_progress(
    bank_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> StudentProgressResponse:
    """Individual student progress. Org admin or the student themselves."""
    caller_id = uuid.UUID(current_user.id)
    if caller_id != user_id:
        await _require_admin(db, bank_id, caller_id)
    data = await _analytics_svc.get_student_progress(db, bank_id, user_id)
    return StudentProgressResponse(**data)
