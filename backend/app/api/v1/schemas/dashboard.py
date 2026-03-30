"""Dashboard API schemas."""

from pydantic import BaseModel, Field


class DashboardStatsResponse(BaseModel):
    """Dashboard statistics response."""

    streak_days: int = Field(description="Consecutive days of activity")
    average_quiz_score: float = Field(
        description="Average quiz score percentage across all modules"
    )
    total_time_studied_this_week: int = Field(description="Total minutes studied this week")
    is_active_today: bool = Field(description="Whether user has been active today")
    next_review_count: int = Field(description="Number of flashcards due for review")
    modules_in_progress: int = Field(description="Number of modules currently in progress")
    completion_percentage: float = Field(
        description="Overall completion percentage across all modules"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "streak_days": 7,
                "average_quiz_score": 85.5,
                "total_time_studied_this_week": 240,
                "is_active_today": True,
                "next_review_count": 12,
                "modules_in_progress": 2,
                "completion_percentage": 35.7,
            }
        }
