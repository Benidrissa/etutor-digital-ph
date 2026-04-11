"""Analytics API endpoints — event ingestion and admin summary."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, get_optional_user, require_role
from app.domain.models.user import UserRole
from app.domain.services.analytics_service import AnalyticsService

logger = structlog.get_logger()
router = APIRouter(prefix="/analytics", tags=["analytics"])

_VALID_PERIODS = {7, 30, 90}


class EventRequest(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=100)
    properties: dict[str, Any] | None = None
    session_id: str | None = Field(None, max_length=100)


class BatchEventItem(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=100)
    properties: dict[str, Any] | None = None
    session_id: str | None = Field(None, max_length=100)
    timestamp: str | None = None


class BatchEventRequest(BaseModel):
    events: list[BatchEventItem] = Field(..., min_length=1, max_length=500)


class EventResponse(BaseModel):
    id: uuid.UUID
    event_name: str
    accepted: bool = True


class BatchResponse(BaseModel):
    accepted: int


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        500: {"description": "Internal error"},
    },
)
async def ingest_event(
    request: EventRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)] = None,
) -> EventResponse:
    """Ingest a single analytics event. Auth is optional (anonymous events allowed)."""
    try:
        user_id = uuid.UUID(current_user.id) if current_user else None
        service = AnalyticsService(db)
        event = await service.ingest_event(
            event_name=request.event_name,
            properties=request.properties,
            user_id=user_id,
            session_id=request.session_id,
        )
        return EventResponse(id=event.id, event_name=event.event_name)
    except Exception as e:
        logger.error("Failed to ingest analytics event", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "ingest_failed", "message": "Failed to record event"},
        )


@router.post(
    "/events/batch",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        500: {"description": "Internal error"},
    },
)
async def ingest_batch(
    request: BatchEventRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)] = None,
) -> BatchResponse:
    """Batch ingest analytics events for offline sync. Auth is optional."""
    try:
        user_id = uuid.UUID(current_user.id) if current_user else None
        service = AnalyticsService(db)
        raw_events = [e.model_dump() for e in request.events]
        count = await service.ingest_batch(events=raw_events, user_id=user_id)
        return BatchResponse(accepted=count)
    except Exception as e:
        logger.error("Failed to ingest analytics batch", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "batch_ingest_failed", "message": "Failed to record events"},
        )


@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid period"},
        403: {"description": "Insufficient permissions"},
        500: {"description": "Internal error"},
    },
)
async def get_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        AuthenticatedUser, Depends(require_role(UserRole.admin, UserRole.sub_admin))
    ],
    period: Annotated[int, Query(description="Period in days: 7, 30, or 90")] = 7,
) -> dict[str, Any]:
    """Admin-only: return aggregated analytics summary for the given period."""
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_period", "message": "period must be 7, 30, or 90"},
        )
    try:
        service = AnalyticsService(db)
        return await service.get_summary(period_days=period)
    except Exception as e:
        logger.error("Failed to compute analytics summary", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "summary_failed", "message": "Failed to compute summary"},
        )
