"""Flashcard review API endpoints."""

import uuid
from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.api.v1.schemas.flashcards import (
    FlashcardDueResponse,
    FlashcardReviewRequest,
    FlashcardReviewResponse,
    FlashcardSessionRequest,
    FlashcardSessionResponse,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.flashcard import FlashcardReview
from app.domain.models.user import User

logger = structlog.get_logger()
router = APIRouter(prefix="/flashcards", tags=["flashcards"])


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
    current_user: User = Depends(get_current_user),
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
                .limit(20)
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

        return FlashcardDueResponse(
            user_id=current_user.id,
            cards=cards_data,
            total_due=len(cards_data),
            session_target=min(20, len(cards_data)),  # Reasonable daily target
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
    current_user: User = Depends(get_current_user),
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

        # Update stability and difficulty based on rating
        if rating_value == 1:  # Again
            new_stability = max(0.1, review.stability * 0.5)
            new_difficulty = min(10.0, review.difficulty + 1.0)
            # Schedule for immediate review (same session)
            next_review = datetime.utcnow()
        elif rating_value == 2:  # Hard
            new_stability = review.stability * 0.8
            new_difficulty = min(10.0, review.difficulty + 0.5)
            # Schedule for 1-2 days
            interval_days = max(1, int(new_stability * 0.8))
            next_review = datetime.utcnow().replace(
                hour=9, minute=0, second=0, microsecond=0
            ) + timedelta(days=interval_days)
        elif rating_value == 3:  # Good
            new_stability = review.stability * 1.2
            new_difficulty = max(1.0, review.difficulty - 0.1)
            # Standard interval
            interval_days = max(1, int(new_stability))
            next_review = datetime.utcnow().replace(
                hour=9, minute=0, second=0, microsecond=0
            ) + timedelta(days=interval_days)
        else:  # Easy
            new_stability = review.stability * 1.5
            new_difficulty = max(1.0, review.difficulty - 0.2)
            # Longer interval
            interval_days = max(1, int(new_stability * 1.3))
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
    current_user: User = Depends(get_current_user),
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
        daily_target_met = session_request.cards_reviewed >= min(20, total_reviews)

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
