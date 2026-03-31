"""Schemas for flashcard review endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FlashcardData(BaseModel):
    """Individual flashcard data for review session."""

    id: str = Field(..., description="Unique card identifier (content_id_index)")
    card_id: UUID = Field(..., description="Generated content ID")
    card_index: int = Field(..., description="Index within flashcard set")
    term: str = Field(..., description="Key term or concept")
    definition_fr: str = Field(..., description="French definition")
    definition_en: str = Field(..., description="English definition")
    example_aof: str = Field(..., description="West African example")
    formula: str | None = Field(None, description="LaTeX formula if applicable")
    sources_cited: list[str] = Field(..., description="Source citations")
    review_id: UUID = Field(..., description="Review record ID")
    due_date: str = Field(..., description="Due date (ISO format)")
    stability: float = Field(..., description="FSRS stability parameter")
    difficulty: float = Field(..., description="FSRS difficulty parameter")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000_0",
                "card_id": "550e8400-e29b-41d4-a716-446655440000",
                "card_index": 0,
                "term": "Surveillance épidémiologique",
                "definition_fr": "Collecte systématique et continue de données sur l'état de santé des populations pour guider les actions de santé publique.",
                "definition_en": "Systematic and continuous collection of data on population health status to guide public health actions.",
                "example_aof": "Au Sénégal, le système de surveillance du paludisme collecte des données hebdomadaires dans tous les centres de santé.",
                "formula": None,
                "sources_cited": ["Donaldson Ch.4, p.67"],
                "review_id": "550e8400-e29b-41d4-a716-446655440001",
                "due_date": "2026-03-31T09:00:00Z",
                "stability": 2.5,
                "difficulty": 4.2,
            }
        }
    }


class FlashcardDueResponse(BaseModel):
    """Response for due flashcards query."""

    user_id: UUID = Field(..., description="User ID")
    cards: list[FlashcardData] = Field(..., description="Due flashcards")
    total_due: int = Field(..., description="Total cards due for review")
    session_target: int = Field(..., description="Recommended session size")

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "cards": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000_0",
                        "card_id": "550e8400-e29b-41d4-a716-446655440000",
                        "card_index": 0,
                        "term": "Surveillance épidémiologique",
                        "definition_fr": "Collecte systématique et continue...",
                        "definition_en": "Systematic and continuous collection...",
                        "example_aof": "Au Sénégal, le système de surveillance...",
                        "formula": None,
                        "sources_cited": ["Donaldson Ch.4, p.67"],
                        "review_id": "550e8400-e29b-41d4-a716-446655440001",
                        "due_date": "2026-03-31T09:00:00Z",
                        "stability": 2.5,
                        "difficulty": 4.2,
                    }
                ],
                "total_due": 15,
                "session_target": 15,
            }
        }
    }


class FlashcardReviewRequest(BaseModel):
    """Request to submit a flashcard review."""

    review_id: UUID = Field(..., description="Review record ID")
    card_id: UUID = Field(..., description="Generated content ID")
    card_index: int = Field(..., description="Index within flashcard set")
    rating: Literal["again", "hard", "good", "easy"] = Field(
        ..., description="FSRS rating: again=1, hard=2, good=3, easy=4"
    )
    reviewed_at: datetime | None = Field(None, description="Review timestamp (for offline sync)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "review_id": "550e8400-e29b-41d4-a716-446655440001",
                "card_id": "550e8400-e29b-41d4-a716-446655440000",
                "card_index": 0,
                "rating": "good",
                "reviewed_at": "2026-03-31T10:30:00Z",
            }
        }
    }


class FlashcardReviewResponse(BaseModel):
    """Response after submitting a flashcard review."""

    review_id: UUID = Field(..., description="Review record ID")
    card_id: UUID = Field(..., description="Generated content ID")
    rating: str = Field(..., description="Submitted rating")
    next_review_date: str = Field(..., description="Next review scheduled date")
    stability: float = Field(..., description="Updated FSRS stability")
    difficulty: float = Field(..., description="Updated FSRS difficulty")
    show_again: bool = Field(..., description="Whether to show again in same session")

    model_config = {
        "json_schema_extra": {
            "example": {
                "review_id": "550e8400-e29b-41d4-a716-446655440001",
                "card_id": "550e8400-e29b-41d4-a716-446655440000",
                "rating": "good",
                "next_review_date": "2026-04-02T09:00:00Z",
                "stability": 3.0,
                "difficulty": 4.1,
                "show_again": False,
            }
        }
    }


class FlashcardSessionRequest(BaseModel):
    """Request to record a completed flashcard session."""

    cards_reviewed: int = Field(..., description="Number of cards reviewed")
    session_duration_seconds: int = Field(..., description="Session duration in seconds")
    review_ratings: list[Literal["again", "hard", "good", "easy"]] = Field(
        ..., description="List of all ratings in session"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "cards_reviewed": 15,
                "session_duration_seconds": 900,
                "review_ratings": ["good", "easy", "hard", "good", "again", "good"],
            }
        }
    }


class FlashcardSessionResponse(BaseModel):
    """Response after recording a flashcard session."""

    session_id: UUID = Field(..., description="Session identifier")
    user_id: UUID = Field(..., description="User ID")
    cards_reviewed: int = Field(..., description="Cards reviewed in session")
    session_duration_seconds: int = Field(..., description="Session duration")
    accuracy_percentage: float = Field(..., description="Percentage of good/easy ratings")
    rating_distribution: dict[str, int] = Field(..., description="Count by rating type")
    streak_days: int = Field(..., description="Current learning streak")
    daily_target_met: bool = Field(..., description="Whether daily target was achieved")

    model_config = {
        "json_schema_extra": {
            "example": {
                "session_id": "550e8400-e29b-41d4-a716-446655440002",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "cards_reviewed": 15,
                "session_duration_seconds": 900,
                "accuracy_percentage": 80.0,
                "rating_distribution": {"again": 1, "hard": 2, "good": 8, "easy": 4},
                "streak_days": 7,
                "daily_target_met": True,
            }
        }
    }


class UpcomingReviewSession(BaseModel):
    """Single upcoming review session data."""

    date: str = Field(..., description="Review date (YYYY-MM-DD)")
    module_name: str = Field(..., description="Module name for this session")
    card_count: int = Field(..., description="Number of cards due on this date")
    is_overdue: bool = Field(..., description="Whether this session is overdue")

    model_config = {
        "json_schema_extra": {
            "example": {
                "date": "2026-03-31",
                "module_name": "M01: Foundations of Public Health",
                "card_count": 12,
                "is_overdue": False,
            }
        }
    }


class UpcomingReviewsResponse(BaseModel):
    """Response for upcoming reviews query."""

    user_id: UUID = Field(..., description="User ID")
    today_due_count: int = Field(..., description="Total cards due today")
    has_due_cards: bool = Field(..., description="Whether user has cards due today")
    upcoming_sessions: list[UpcomingReviewSession] = Field(
        ..., description="Next 5 review sessions"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "today_due_count": 15,
                "has_due_cards": True,
                "upcoming_sessions": [
                    {
                        "date": "2026-03-31",
                        "module_name": "M01: Foundations of Public Health",
                        "card_count": 15,
                        "is_overdue": False,
                    },
                    {
                        "date": "2026-04-01",
                        "module_name": "M02: Health Data Systems",
                        "card_count": 8,
                        "is_overdue": False,
                    },
                ],
            }
        }
    }
