"""Flashcard review API endpoints."""

import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.api.deps import get_db
from app.api.deps_local_auth import require_active_subscription
from app.api.v1.schemas.content import FlashcardSetResponse
from app.api.v1.schemas.flashcards import (
    FlashcardDueResponse,
    FlashcardReviewRequest,
    FlashcardReviewResponse,
    FlashcardSessionRequest,
    FlashcardSessionResponse,
    UpcomingReviewsResponse,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.flashcard import FlashcardReview
from app.domain.models.module import Module
from app.domain.models.user import User
from app.domain.services.analytics_service import AnalyticsService
from app.domain.services.flashcard_service import FlashcardGenerationService
from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()
router = APIRouter(prefix="/flashcards", tags=["flashcards"])


def _get_flashcard_generation_service() -> FlashcardGenerationService:
    """Dependency to get flashcard generation service."""
    settings = get_settings()
    embedding_service = EmbeddingService(
        api_key=settings.openai_api_key, model=settings.embedding_model
    )
    retriever = SemanticRetriever(embedding_service)
    claude_service = ClaudeService()
    return FlashcardGenerationService(claude_service, retriever)


async def _resolve_module_id(module_id: str, session: AsyncSession) -> uuid.UUID:
    """Resolve module identifier (M01 code or UUID) to UUID."""
    try:
        return uuid.UUID(module_id)
    except ValueError:
        pass

    match = re.match(r"^M(\d{2})$", module_id.upper())
    if match:
        module_number = int(match.group(1))
        query = select(Module).where(Module.module_number == module_number)
        result = await session.execute(query)
        module = result.scalar_one_or_none()
        if module:
            return module.id
        raise ValueError(f"Module with code {module_id} not found")

    raise ValueError(
        f"Invalid module identifier: {module_id}. Expected UUID or module code (M01, M02, etc.)"
    )


@router.get(
    "/due",
    response_model=FlashcardDueResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_due_flashcards(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_db),
) -> FlashcardDueResponse:
    """
    Get flashcards due for review for the current user.

    Returns flashcards that are scheduled for review today or earlier.
    Used for daily flashcard sessions and spaced repetition.

    **FSRS Algorithm:**
    - Cards are scheduled based on previous review performance
    - "Again" cards appear again in same session
    - Other ratings schedule for future dates based on stability/difficulty

    **Mobile Optimization:**
    - Returns card data with bilingual content
    - Includes progress information for session UI
    - Sorted by due date (most urgent first)
    """
    try:
        logger.info("Fetching due flashcards", user_id=str(current_user.id))

        now = datetime.utcnow()

        # Get all flashcard reviews due for this user
        review_query = (
            select(FlashcardReview, GeneratedContent)
            .join(GeneratedContent, FlashcardReview.card_id == GeneratedContent.id)
            .where(
                and_(
                    FlashcardReview.user_id == current_user.id,
                    FlashcardReview.next_review <= now,
                    GeneratedContent.content_type == "flashcard",
                )
            )
            .order_by(FlashcardReview.next_review.asc())
        )

        result = await session.execute(review_query)
        due_reviews = result.all()

        # If no reviews found, look for new flashcards that haven't been reviewed yet
        if not due_reviews:
            # Get flashcard sets appropriate for user's level
            new_cards_query = (
                select(GeneratedContent)
                .where(
                    and_(
                        GeneratedContent.content_type == "flashcard",
                        GeneratedContent.language == current_user.preferred_language,
                        GeneratedContent.level <= current_user.current_level,
                        ~GeneratedContent.id.in_(
                            select(FlashcardReview.card_id).where(
                                FlashcardReview.user_id == current_user.id
                            )
                        ),
                    )
                )
                .limit(SettingsCache.instance().get("flashcards-new-cards-per-session", 20))
            )  # Limit new cards per session

            new_result = await session.execute(new_cards_query)
            new_cards = new_result.scalars().all()

            if new_cards:
                # Create initial review records for new cards
                for card in new_cards:
                    new_review = FlashcardReview(
                        id=uuid.uuid4(),
                        user_id=current_user.id,
                        card_id=card.id,
                        rating="new",
                        next_review=now,
                        stability=1.0,
                        difficulty=5.0,
                    )
                    session.add(new_review)

                await session.commit()

                # Re-fetch the due reviews
                result = await session.execute(review_query)
                due_reviews = result.all()

        # Build response
        cards_data = []
        for review, content in due_reviews:
            # Extract individual flashcards from content
            flashcards = content.content.get("flashcards", [])
            for i, card_data in enumerate(flashcards):
                cards_data.append(
                    {
                        "id": f"{content.id}_{i}",
                        "card_id": content.id,
                        "card_index": i,
                        "term": card_data.get("term", ""),
                        "definition_fr": card_data.get("definition_fr", ""),
                        "definition_en": card_data.get("definition_en", ""),
                        "example_aof": card_data.get("example_aof", ""),
                        "formula": card_data.get("formula"),
                        "sources_cited": card_data.get("sources_cited", []),
                        "review_id": review.id,
                        "due_date": review.next_review.isoformat(),
                        "stability": review.stability,
                        "difficulty": review.difficulty,
                    }
                )

        logger.info(
            "Due flashcards fetched successfully",
            user_id=str(current_user.id),
            cards_count=len(cards_data),
        )

        _new_cards_per_session = SettingsCache.instance().get(
            "flashcards-new-cards-per-session", 20
        )
        return FlashcardDueResponse(
            user_id=current_user.id,
            cards=cards_data,
            total_due=len(cards_data),
            session_target=min(_new_cards_per_session, len(cards_data)),
        )

    except Exception as e:
        logger.error("Failed to fetch due flashcards", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "flashcard_fetch_failed",
                "message": "Unable to fetch due flashcards",
            },
        )


@router.post(
    "/review",
    response_model=FlashcardReviewResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid review data"},
        401: {"description": "Unauthorized"},
        404: {"description": "Card not found"},
        500: {"description": "Internal server error"},
    },
)
async def submit_flashcard_review(
    review_request: FlashcardReviewRequest,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_db),
) -> FlashcardReviewResponse:
    """
    Submit a flashcard review with FSRS rating.

    Updates the spaced repetition schedule based on user's performance rating.

    **FSRS Ratings:**
    - `again`: Forgot completely (1) - card shown again in same session
    - `hard`: Recalled with difficulty (2) - shorter interval
    - `good`: Recalled correctly (3) - standard interval
    - `easy`: Recalled easily (4) - longer interval

    **Algorithm:**
    - Calculates new stability and difficulty based on previous performance
    - Schedules next review date using FSRS parameters
    - "Again" cards are rescheduled for immediate review

    **Mobile Offline Support:**
    - Reviews are queued when offline and submitted when connection restored
    - Includes timestamp for proper scheduling calculation
    """
    try:
        logger.info(
            "Processing flashcard review",
            user_id=str(current_user.id),
            card_id=str(review_request.card_id),
            rating=review_request.rating,
        )

        # Get existing review record
        review_query = select(FlashcardReview).where(
            and_(
                FlashcardReview.id == review_request.review_id,
                FlashcardReview.user_id == current_user.id,
            )
        )

        result = await session.execute(review_query)
        review = result.scalar_one_or_none()

        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "review_not_found",
                    "message": f"Review {review_request.review_id} not found",
                },
            )

        # Calculate FSRS parameters (simplified implementation)
        rating_values = {"again": 1, "hard": 2, "good": 3, "easy": 4}
        rating_value = rating_values.get(review_request.rating, 3)

        # Load FSRS parameters from settings
        fsrs = SettingsCache.instance().get(
            "flashcards-fsrs-params",
            {
                "again": {"stability": 0.5, "difficulty": 1.0},
                "hard": {"stability": 0.8, "difficulty": 0.5, "interval": 0.8},
                "good": {"stability": 1.2, "difficulty": -0.1},
                "easy": {"stability": 1.5, "difficulty": -0.2, "interval": 1.3},
            },
        )

        # Update stability and difficulty based on rating
        if rating_value == 1:  # Again
            new_stability = max(0.1, review.stability * fsrs["again"]["stability"])
            new_difficulty = min(10.0, review.difficulty + fsrs["again"]["difficulty"])
            # Schedule for immediate review (same session)
            next_review = datetime.utcnow()
        elif rating_value == 2:  # Hard
            new_stability = review.stability * fsrs["hard"]["stability"]
            new_difficulty = min(10.0, review.difficulty + fsrs["hard"]["difficulty"])
            # Schedule for 1-2 days
            interval_days = max(1, int(new_stability * fsrs["hard"]["interval"]))
            next_review = datetime.utcnow().replace(
                hour=9, minute=0, second=0, microsecond=0
            ) + timedelta(days=interval_days)
        elif rating_value == 3:  # Good
            new_stability = review.stability * fsrs["good"]["stability"]
            new_difficulty = max(1.0, review.difficulty + fsrs["good"]["difficulty"])
            # Standard interval
            interval_days = max(1, int(new_stability))
            next_review = datetime.utcnow().replace(
                hour=9, minute=0, second=0, microsecond=0
            ) + timedelta(days=interval_days)
        else:  # Easy
            new_stability = review.stability * fsrs["easy"]["stability"]
            new_difficulty = max(1.0, review.difficulty + fsrs["easy"]["difficulty"])
            # Longer interval
            interval_days = max(1, int(new_stability * fsrs["easy"]["interval"]))
            next_review = datetime.utcnow().replace(
                hour=9, minute=0, second=0, microsecond=0
            ) + timedelta(days=interval_days)

        # Update review record
        review.rating = review_request.rating
        review.stability = new_stability
        review.difficulty = new_difficulty
        review.next_review = next_review
        review.reviewed_at = review_request.reviewed_at or datetime.utcnow()

        await session.commit()

        try:
            analytics_svc = AnalyticsService(session)
            await analytics_svc.ingest_event(
                event_name="flashcard_reviewed",
                properties={
                    "card_id": str(review_request.card_id),
                    "rating": review_request.rating,
                },
                user_id=uuid.UUID(str(current_user.id)),
                session_id=None,
            )
        except Exception as analytics_err:
            logger.warning("Analytics event failed (non-fatal)", error=str(analytics_err))

        logger.info(
            "Flashcard review processed successfully",
            user_id=str(current_user.id),
            review_id=str(review.id),
            new_stability=new_stability,
            new_difficulty=new_difficulty,
            next_review=next_review.isoformat(),
        )

        return FlashcardReviewResponse(
            review_id=review.id,
            card_id=review.card_id,
            rating=review.rating,
            next_review_date=next_review.isoformat(),
            stability=new_stability,
            difficulty=new_difficulty,
            show_again=rating_value == 1,  # Show again if rated "again"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process flashcard review", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "review_processing_failed",
                "message": "Unable to process flashcard review",
            },
        )


@router.post(
    "/session",
    response_model=FlashcardSessionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid session data"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def complete_flashcard_session(
    session_request: FlashcardSessionRequest,
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_db),
) -> FlashcardSessionResponse:
    """
    Complete a flashcard review session.

    Records session statistics and updates user progress.
    Used for tracking learning analytics and session summaries.

    **Session Metrics:**
    - Cards reviewed count
    - Time spent in session
    - Accuracy by rating distribution
    - Cards mastered vs. need more practice

    **Progress Updates:**
    - Updates user streak if daily target met
    - Records session for dashboard analytics
    """
    try:
        logger.info(
            "Recording flashcard session completion",
            user_id=str(current_user.id),
            cards_reviewed=session_request.cards_reviewed,
            session_duration=session_request.session_duration_seconds,
        )

        # Calculate session statistics
        total_reviews = len(session_request.review_ratings)
        rating_counts = {
            "again": sum(1 for r in session_request.review_ratings if r == "again"),
            "hard": sum(1 for r in session_request.review_ratings if r == "hard"),
            "good": sum(1 for r in session_request.review_ratings if r == "good"),
            "easy": sum(1 for r in session_request.review_ratings if r == "easy"),
        }

        accuracy_percentage = (
            (rating_counts["good"] + rating_counts["easy"]) / total_reviews * 100
            if total_reviews > 0
            else 0
        )

        # Update user's last_active timestamp
        current_user.last_active = datetime.utcnow()

        # Check if user met daily target (20 cards or available cards)
        daily_target_met = session_request.cards_reviewed >= min(
            SettingsCache.instance().get("flashcards-new-cards-per-session", 20), total_reviews
        )

        if daily_target_met:
            # Update streak if it's a new day
            today = datetime.utcnow().date()
            last_active_date = current_user.last_active.date()

            if last_active_date < today:
                if (today - last_active_date).days == 1:
                    # Consecutive day - increment streak
                    current_user.streak_days += 1
                else:
                    # Gap in activity - reset streak
                    current_user.streak_days = 1
            # Same day activity doesn't change streak

        await session.commit()

        logger.info(
            "Flashcard session recorded successfully",
            user_id=str(current_user.id),
            accuracy=accuracy_percentage,
            streak_days=current_user.streak_days,
        )

        return FlashcardSessionResponse(
            session_id=uuid.uuid4(),
            user_id=current_user.id,
            cards_reviewed=session_request.cards_reviewed,
            session_duration_seconds=session_request.session_duration_seconds,
            accuracy_percentage=accuracy_percentage,
            rating_distribution=rating_counts,
            streak_days=current_user.streak_days,
            daily_target_met=daily_target_met,
        )

    except Exception as e:
        logger.error("Failed to record flashcard session", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "session_recording_failed",
                "message": "Unable to record flashcard session",
            },
        )


@router.get(
    "/upcoming",
    response_model=UpcomingReviewsResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_upcoming_reviews(
    current_user: User = Depends(require_active_subscription),
    session: AsyncSession = Depends(get_db),
) -> UpcomingReviewsResponse:
    """
    Get upcoming flashcard review sessions grouped by date.

    Returns the next 5 review sessions with module information and card counts.
    Used for the dashboard upcoming reviews widget.

    **Features:**
    - Groups cards by review date and module
    - Shows card counts per session
    - Identifies overdue reviews (highlighted in red in UI)
    - Includes today's due cards count for "Start review" button

    **Mobile Optimization:**
    - Returns minimal data for quick loading
    - Pre-grouped for easy UI rendering
    - Includes all info needed for widget display
    """
    try:
        logger.info("Fetching upcoming reviews", user_id=str(current_user.id))

        now = datetime.utcnow()
        today = now.date()

        # Get all scheduled flashcard reviews for the next 2 weeks
        _preview_days = SettingsCache.instance().get(
            "flashcards-review-preview-days",
            14,
        )
        two_weeks_from_now = now + timedelta(days=_preview_days)

        review_query = (
            select(FlashcardReview, GeneratedContent)
            .join(GeneratedContent, FlashcardReview.card_id == GeneratedContent.id)
            .where(
                and_(
                    FlashcardReview.user_id == current_user.id,
                    FlashcardReview.next_review <= two_weeks_from_now,
                    GeneratedContent.content_type == "flashcard",
                )
            )
            .order_by(FlashcardReview.next_review.asc())
        )

        result = await session.execute(review_query)
        upcoming_reviews = result.all()

        # Count today's due cards
        today_due_count = 0

        # Group reviews by date and module
        reviews_by_date = defaultdict(lambda: defaultdict(int))

        for review, content in upcoming_reviews:
            review_date = review.next_review.date()

            # Count today's cards
            if review_date <= today:
                # Count individual flashcards in the set
                flashcards = content.content.get("flashcards", [])
                today_due_count += len(flashcards)

            # Get module info from content
            module_name = str(content.module_id) if content.module_id else "General Review"
            # Simplify module names for display
            if module_name.startswith("M"):
                # Extract module number and create display name
                module_parts = module_name.split("_")
                if len(module_parts) > 1:
                    module_num = module_parts[0]  # e.g., "M01"
                    module_name = f"{module_num}: Health Foundations"
                else:
                    module_name = f"Module {module_name}"

            # Count flashcards in this review
            flashcards = content.content.get("flashcards", [])
            reviews_by_date[review_date][module_name] += len(flashcards)

        # Convert to response format - get next 5 sessions
        upcoming_sessions = []
        processed_dates = 0

        for review_date in sorted(reviews_by_date.keys()):
            if processed_dates >= 5:
                break

            for module_name, card_count in reviews_by_date[review_date].items():
                if processed_dates >= 5:
                    break

                is_overdue = review_date < today

                upcoming_sessions.append(
                    {
                        "date": review_date.isoformat(),
                        "module_name": module_name,
                        "card_count": card_count,
                        "is_overdue": is_overdue,
                    }
                )

                processed_dates += 1

        logger.info(
            "Upcoming reviews fetched successfully",
            user_id=str(current_user.id),
            today_due_count=today_due_count,
            sessions_count=len(upcoming_sessions),
        )

        return UpcomingReviewsResponse(
            user_id=current_user.id,
            today_due_count=today_due_count,
            has_due_cards=today_due_count > 0,
            upcoming_sessions=upcoming_sessions,
        )

    except Exception as e:
        logger.error("Failed to fetch upcoming reviews", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "upcoming_reviews_fetch_failed",
                "message": "Unable to fetch upcoming reviews",
            },
        )


@router.get(
    "/modules/{module_id}",
    response_model=FlashcardSetResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid module identifier"},
        401: {"description": "Unauthorized"},
        404: {"description": "Module not found"},
        500: {"description": "Internal server error"},
    },
)
async def get_module_flashcards(
    module_id: str,
    language: str = "fr",
    country: str = "SN",
    level: int = 1,
    current_user: User = Depends(require_active_subscription),
    flashcard_service: FlashcardGenerationService = Depends(_get_flashcard_generation_service),
    session: AsyncSession = Depends(get_db),
) -> FlashcardSetResponse:
    """
    Get or auto-generate bilingual flashcards for a module.

    Flashcards are automatically generated via RAG pipeline on first access.
    Subsequent calls return cached results instantly.

    **Parameters:**
    - **module_id**: Module identifier (code like "M01" or UUID string)
    - **language**: Content language ("fr" or "en"), defaults to "fr"
    - **country**: Country context for examples (ISO 2-letter code), defaults to "SN"
    - **level**: User's competency level (1-4), defaults to 1

    **Generation:**
    - Retrieves top-12 relevant chunks from RAG vector store
    - Uses module's learning objectives and key concepts
    - Generates 15-30 bilingual flashcards (FR/EN)
    - Stores result in `generated_content` table (content_type='flashcard')
    - Cached results returned instantly on subsequent calls

    **Each flashcard includes:**
    - Term and bilingual definitions (FR/EN)
    - West African contextual example
    - LaTeX formula if applicable
    - Source citations from reference materials
    """
    try:
        logger.info(
            "Module flashcards request",
            module_id=module_id,
            language=language,
            country=country,
            level=level,
            user_id=str(current_user.id),
        )

        resolved_module_id = await _resolve_module_id(module_id, session)

        flashcard_response = await flashcard_service.get_or_generate_flashcard_set(
            module_id=resolved_module_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        logger.info(
            "Module flashcards returned",
            module_id=module_id,
            flashcard_count=len(flashcard_response.flashcards),
            cached=flashcard_response.cached,
        )

        return flashcard_response

    except ValueError as e:
        logger.warning("Invalid module flashcards request", error=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "module_not_found", "message": str(e)},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_request", "message": str(e)},
        )

    except Exception as e:
        logger.error("Failed to get module flashcards", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "flashcard_generation_failed",
                "message": "Unable to get or generate flashcards for this module",
            },
        )
