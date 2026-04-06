"""Placement test endpoints for level assignment.

DEPRECATED: These global endpoints are deprecated.  Use the per-course
pre-assessment endpoints under /api/v1/courses/{course_id}/preassessment instead.
Global endpoints internally delegate to the default SantePublique AOF course.
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user
from app.domain.models.course import Course
from app.domain.models.preassessment import CoursePreAssessment
from app.domain.services.platform_settings_service import SettingsCache

from ...domain.models.quiz import PlacementTestAttempt
from ...domain.models.user import User
from ...domain.repositories.implementations.user_repository import UserRepository
from ...domain.services.placement_service import PlacementService
from .schemas.placement import (
    PlacementAttemptSummary,
    PlacementResultsHistory,
    PlacementTestResponse,
    PlacementTestSubmission,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/placement-test", tags=["Placement Test"])

_DEPRECATION_LINK = '</api/v1/courses/{{course_id}}/preassessment>; rel="successor-version"'


async def _load_default_course_preassessment(
    language: str, db: AsyncSession
) -> CoursePreAssessment | None:
    """Load preassessment for the default course from the database."""
    default_slug = SettingsCache.instance().get("default-course-slug", "sante-publique-aof")
    course_result = await db.execute(select(Course).where(Course.slug == default_slug))
    default_course = course_result.scalar_one_or_none()
    if default_course is None:
        return None
    result = await db.execute(
        select(CoursePreAssessment).where(
            CoursePreAssessment.course_id == default_course.id,
            CoursePreAssessment.language == language,
        )
    )
    return result.scalar_one_or_none()


def _add_deprecation_headers(response: Response, migrate_to: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-12-31"
    response.headers["Link"] = f'<{migrate_to}>; rel="successor-version"'


@router.get("/questions", response_model=PlacementTestResponse)
async def get_placement_test_questions(
    response: Response,
    language: str | None = Query(default=None, pattern="^(fr|en)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlacementTestResponse:
    """Get placement test questions.

    .. deprecated::
        Use ``GET /api/v1/courses/{course_id}/preassessment/questions`` instead.
        Delegates to the default course preassessment in the database.

    Args:
        language: Language override (fr/en). Falls back to user's preferred_language.

    Returns:
        Placement test questions from the default course preassessment

    Raises:
        404: No preassessment found for the default course
        500: Failed to load questions
    """
    _add_deprecation_headers(response, "/api/v1/courses/{course_id}/preassessment/questions")
    logger.warning(
        "Deprecated endpoint called: GET /placement-test/questions",
        user_id=str(current_user.id),
        migrate_to="/api/v1/courses/{course_id}/preassessment/questions",
    )

    try:
        lang = language if language is not None else current_user.preferred_language
        preassessment = await _load_default_course_preassessment(lang, db)

        if preassessment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No preassessment found for the default course. Use the course-specific endpoint.",
            )

        logger.info(
            "Placement test questions retrieved via deprecated endpoint",
            user_id=str(current_user.id),
        )
        # Normalize options to [{id, text}] for legacy dict format compat
        normalized_questions = []
        for q in preassessment.questions or []:
            raw_opts = q.get("options", [])
            if isinstance(raw_opts, dict):
                opts = [{"id": k, "text": v} for k, v in raw_opts.items()]
            else:
                opts = raw_opts
            normalized_questions.append({**q, "options": opts})

        return PlacementTestResponse(
            questions=normalized_questions,
            total_questions=preassessment.question_count or len(preassessment.questions),
            time_limit_minutes=30,
            instructions={
                "en": "Answer all questions covering topics from beginner to expert level. Your score will determine your starting level and unlock the modules that match your knowledge.",
                "fr": "Répondez à toutes les questions couvrant des sujets du niveau débutant au niveau expert. Votre score déterminera votre niveau de départ et débloquera les modules correspondant à vos connaissances.",
            },
            domains=preassessment.domains or {},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get placement test questions", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load placement test questions",
        )


@router.post("/submit")
async def submit_placement_test(
    submission: PlacementTestSubmission,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Submit placement test and get level assignment.

    .. deprecated::
        Use ``POST /api/v1/courses/{course_id}/preassessment/submit`` instead.
        Delegates scoring to the default course preassessment in the database.

    Args:
        submission: User's answers and test data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Placement result with assigned level and recommendations

    Raises:
        400: Invalid submission data
        500: Failed to score placement test
    """
    _add_deprecation_headers(response, "/api/v1/courses/{course_id}/preassessment/submit")
    logger.warning(
        "Deprecated endpoint called: POST /placement-test/submit",
        user_id=str(current_user.id),
        migrate_to="/api/v1/courses/{course_id}/preassessment/submit",
    )

    try:
        user_repo = UserRepository(db)
        placement_service = PlacementService(user_repo)

        user_context = {
            "professional_role": current_user.professional_role or "",
            "country": current_user.country or "",
            "preferred_language": current_user.preferred_language,
        }

        result = await placement_service.score_placement_test(
            user_id=current_user.id,
            answers=submission.answers,
            time_taken=submission.time_taken_sec,
            user_context=user_context,
            db=db,
        )

        attempt = PlacementTestAttempt(
            user_id=current_user.id,
            answers=submission.answers,
            raw_score=result.score_percentage,
            adjusted_score=result.score_percentage,
            assigned_level=result.assigned_level,
            time_taken_sec=submission.time_taken_sec,
            domain_scores=result.level_scores,
            user_context=user_context,
            competency_areas=result.competency_areas,
            recommendations=result.recommendations,
            can_retake_after=datetime.utcnow()
            + timedelta(days=SettingsCache.instance().get("placement-retest-cooldown-days", 90)),
        )

        db.add(attempt)
        await db.commit()

        logger.info(
            "Placement test completed via deprecated endpoint",
            user_id=str(current_user.id),
            assigned_level=result.assigned_level,
            score=result.score_percentage,
        )

        return {
            "assigned_level": result.assigned_level,
            "score_percentage": result.score_percentage,
            "level_scores": result.level_scores,
            "competency_areas": result.competency_areas,
            "recommendations": result.recommendations,
            "level_description": {
                "en": _get_level_description_en(result.assigned_level),
                "fr": _get_level_description_fr(result.assigned_level),
            },
            "can_retake_after": (
                datetime.utcnow()
                + timedelta(days=SettingsCache.instance().get("placement-retest-cooldown-days", 90))
            ).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to submit placement test", error=str(e), user_id=str(current_user.id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process placement test submission",
        )


@router.post("/skip")
async def skip_placement_test(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Skip placement test and assign Level 1.

    .. deprecated::
        Use the course-specific pre-assessment skip endpoint instead.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        Assignment result with Level 1

    Raises:
        500: Failed to assign level
    """
    _add_deprecation_headers(response, "/api/v1/courses/{course_id}/preassessment/skip")
    logger.warning(
        "Deprecated endpoint called: POST /placement-test/skip",
        user_id=str(current_user.id),
        migrate_to="/api/v1/courses/{course_id}/preassessment/skip",
    )

    try:
        user_repo = UserRepository(db)

        current_user.current_level = 1
        await user_repo.update(current_user)

        logger.info("Placement test skipped - assigned Level 1", user_id=str(current_user.id))

        return {
            "assigned_level": 1,
            "score_percentage": 0.0,
            "competency_areas": ["Foundation Building"],
            "recommendations": [
                "Start with Module 1: Public Health Foundations",
                "Focus on building core concepts before advancing",
            ],
            "level_description": {
                "en": "Beginner - Build foundational knowledge",
                "fr": "Débutant - Construire les connaissances de base",
            },
            "skipped": True,
        }

    except Exception as e:
        logger.error("Failed to skip placement test", error=str(e), user_id=str(current_user.id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to skip placement test",
        )


@router.get("/results", response_model=PlacementResultsHistory)
async def get_placement_results_history(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlacementResultsHistory:
    """Get all past placement test attempts for the authenticated user.

    .. deprecated::
        Use the course-specific pre-assessment results endpoint instead.

    Returns:
        PlacementResultsHistory with all attempts ordered newest first,
        plus retake eligibility info.

    Raises:
        500: Failed to retrieve results
    """
    _add_deprecation_headers(response, "/api/v1/courses/{course_id}/preassessment/results")
    logger.warning(
        "Deprecated endpoint called: GET /placement-test/results",
        user_id=str(current_user.id),
        migrate_to="/api/v1/courses/{course_id}/preassessment/results",
    )

    try:
        result = await db.execute(
            select(PlacementTestAttempt)
            .where(PlacementTestAttempt.user_id == current_user.id)
            .order_by(PlacementTestAttempt.attempted_at.desc())
        )
        attempts = list(result.scalars().all())

        now = datetime.utcnow()
        latest = attempts[0] if attempts else None
        can_retake_now = latest is None or (
            latest.can_retake_after is None or latest.can_retake_after <= now
        )
        next_retake_at = (
            latest.can_retake_after
            if latest and latest.can_retake_after and latest.can_retake_after > now
            else None
        )

        attempt_summaries = [
            PlacementAttemptSummary(
                id=str(attempt.id),
                attempt_number=idx + 1,
                attempted_at=attempt.attempted_at,
                score_percentage=attempt.raw_score,
                assigned_level=attempt.assigned_level,
                domain_scores=attempt.domain_scores or {},
                can_retake_after=attempt.can_retake_after,
            )
            for idx, attempt in enumerate(reversed(attempts))
        ]
        attempt_summaries.sort(key=lambda a: a.attempted_at, reverse=True)

        logger.info(
            "Placement results history retrieved via deprecated endpoint",
            user_id=str(current_user.id),
            total_attempts=len(attempts),
        )

        return PlacementResultsHistory(
            attempts=attempt_summaries,
            total_attempts=len(attempts),
            can_retake_now=can_retake_now,
            next_retake_at=next_retake_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to retrieve placement results",
            error=str(e),
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve placement test results",
        )


def _get_level_description_en(level: int) -> str:
    """Get English level description."""
    descriptions = {
        1: "Beginner - Build foundational knowledge",
        2: "Intermediate - Develop core competencies",
        3: "Advanced - Strengthen specialized skills",
        4: "Expert - Master advanced concepts",
    }
    return descriptions.get(level, "Unknown level")


def _get_level_description_fr(level: int) -> str:
    """Get French level description."""
    descriptions = {
        1: "Débutant - Construire les connaissances de base",
        2: "Intermédiaire - Développer les compétences clés",
        3: "Avancé - Renforcer les compétences spécialisées",
        4: "Expert - Maîtriser les concepts avancés",
    }
    return descriptions.get(level, "Niveau inconnu")
