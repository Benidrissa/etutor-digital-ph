"""Dashboard API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.api.v1.schemas.dashboard import DashboardStatsResponse
from app.domain.models.user import User
from app.domain.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def parse_timezone_offset(timezone_header: str | None) -> int:
    """
    Parse timezone offset from header.
    Expected format: "+01:00" or "-05:00"
    Returns offset in hours.
    """
    if not timezone_header:
        return 0

    try:
        # Remove the colon and parse
        if timezone_header.startswith(("+", "-")):
            sign = 1 if timezone_header[0] == "+" else -1
            hours_minutes = timezone_header[1:].replace(":", "")
            if len(hours_minutes) >= 2:
                hours = int(hours_minutes[:2])
                return sign * hours
    except (ValueError, IndexError):
        pass

    return 0


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_timezone_offset: Annotated[str | None, Header()] = None,
) -> DashboardStatsResponse:
    """
    Get dashboard statistics for the current user.

    - **streak_days**: Consecutive days of activity
    - **average_quiz_score**: Average quiz score across all modules (0-100)
    - **total_time_studied_this_week**: Total minutes studied in the last 7 days
    - **is_active_today**: True if user has been active today
    - **next_review_count**: Number of flashcards due for review
    - **modules_in_progress**: Number of modules currently in progress
    - **completion_percentage**: Overall completion percentage across all modules (0-100)

    Send timezone offset in `X-Timezone-Offset` header for streak calculations.
    """
    try:
        timezone_offset = parse_timezone_offset(x_timezone_offset)

        service = DashboardService(db)
        stats = await service.get_user_stats(str(current_user.id), timezone_offset)

        return DashboardStatsResponse(**stats)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve dashboard stats")
