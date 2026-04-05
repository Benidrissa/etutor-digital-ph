"""Per-course pre-assessment endpoints."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user
from app.domain.models.course import Course
from app.domain.models.preassessment import CoursePreassessment
from app.domain.models.quiz import PlacementTestAttempt
from app.domain.models.user import User
from app.domain.repositories.implementations.user_repository import UserRepository
from app.domain.services.placement_service import PlacementService

from .schemas.placement import (
    CoursePreassessmentStatus,
    PlacementTestResponse,
    PlacementTestSubmission,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/courses/{course_id}/preassessment", tags=["Course Pre-Assessment"])


async def _get_course_or_404(course_id: UUID, db: AsyncSession) -> Course:
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


async def _get_preassessment_or_404(course_id: UUID, db: AsyncSession) -> CoursePreassessment:
    result = await db.execute(
        select(CoursePreassessment).where(CoursePreassessment.course_id == course_id)
    )
    preassessment = result.scalar_one_or_none()
    if preassessment is None or not preassessment.preassessment_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pre-assessment found for this course or it is disabled",
        )
    return preassessment


async def _get_latest_attempt(
    user_id: UUID, course_id: UUID, db: AsyncSession
) -> PlacementTestAttempt | None:
    result = await db.execute(
        select(PlacementTestAttempt)
        .where(
            PlacementTestAttempt.user_id == user_id,
            PlacementTestAttempt.course_id == course_id,
        )
        .order_by(PlacementTestAttempt.attempted_at.desc())
    )
    return result.scalars().first()


@router.get("/questions", response_model=PlacementTestResponse)
async def get_course_preassessment_questions(
    course_id: UUID,
    language: str | None = Query(default=None, pattern="^(fr|en)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlacementTestResponse:
    """Get pre-assessment questions for a specific course.

    Returns 404 if the course has no pre-assessment or preassessment_enabled=false.
    Questions do NOT include correct_answer (stripped for security).
    """
    try:
        await _get_course_or_404(course_id, db)
        preassessment = await _get_preassessment_or_404(course_id, db)

        lang = language if language is not None else current_user.preferred_language

        raw_questions: list[dict[str, Any]] = preassessment.questions or []
        questions = []
        for q in raw_questions:
            questions.append(
                {
                    "id": str(q.get("id", "")),
                    "domain": q.get("domain", ""),
                    "level": q.get("level", 1),
                    "question": q.get(f"question_{lang}", q.get("question", "")),
                    "options": [
                        {
                            "id": opt.get("id", ""),
                            "text": opt.get(f"text_{lang}", opt.get("text", "")),
                        }
                        for opt in q.get("options", [])
                    ],
                }
            )

        instructions_fr = preassessment.instructions_fr or (
            "Répondez à toutes les questions. Votre score déterminera votre niveau de départ."
        )
        instructions_en = preassessment.instructions_en or (
            "Answer all questions. Your score will determine your starting level."
        )

        logger.info(
            "Course pre-assessment questions retrieved",
            user_id=str(current_user.id),
            course_id=str(course_id),
            question_count=len(questions),
        )

        return PlacementTestResponse(
            questions=questions,
            total_questions=len(questions),
            time_limit_minutes=preassessment.time_limit_minutes,
            instructions={"fr": instructions_fr, "en": instructions_en},
            domains={},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get course pre-assessment questions",
            error=str(e),
            course_id=str(course_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve pre-assessment questions",
        )


@router.post("/submit")
async def submit_course_preassessment(
    course_id: UUID,
    submission: PlacementTestSubmission,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Submit course pre-assessment and get level assignment.

    Scores using the stored answer key from course_preassessments.
    Calls _unlock_modules_after_placement() filtered by course_id.
    Saves PlacementTestAttempt with course_id.
    """
    try:
        await _get_course_or_404(course_id, db)
        preassessment = await _get_preassessment_or_404(course_id, db)

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
            course_id=course_id,
        )

        cooldown_days = preassessment.retake_cooldown_days
        can_retake_after = datetime.utcnow() + timedelta(days=cooldown_days)

        attempt = PlacementTestAttempt(
            user_id=current_user.id,
            course_id=course_id,
            answers=submission.answers,
            raw_score=result.score_percentage,
            adjusted_score=result.score_percentage,
            assigned_level=result.assigned_level,
            time_taken_sec=submission.time_taken_sec,
            domain_scores=result.level_scores,
            user_context=user_context,
            competency_areas=result.competency_areas,
            recommendations=result.recommendations,
            can_retake_after=can_retake_after,
        )
        db.add(attempt)
        await db.commit()

        logger.info(
            "Course pre-assessment submitted",
            user_id=str(current_user.id),
            course_id=str(course_id),
            assigned_level=result.assigned_level,
            score=result.score_percentage,
        )

        return {
            "assigned_level": result.assigned_level,
            "score_percentage": result.score_percentage,
            "level_scores": result.level_scores,
            "competency_areas": result.competency_areas,
            "recommendations": result.recommendations,
            "can_retake_after": can_retake_after.isoformat(),
            "course_id": str(course_id),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to submit course pre-assessment",
            error=str(e),
            user_id=str(current_user.id),
            course_id=str(course_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process pre-assessment submission",
        )


@router.post("/skip")
async def skip_course_preassessment(
    course_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Skip pre-assessment for a specific course.

    Assigns Level 1 and unlocks only that course's modules.
    """
    try:
        await _get_course_or_404(course_id, db)
        preassessment = await _get_preassessment_or_404(course_id, db)

        if preassessment.mandatory:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Pre-assessment is mandatory for this course and cannot be skipped",
            )

        user_repo = UserRepository(db)
        placement_service = PlacementService(user_repo)

        await placement_service._unlock_modules_after_placement(
            user_id=current_user.id,
            assigned_level=1,
            db=db,
            course_id=course_id,
        )

        attempt = PlacementTestAttempt(
            user_id=current_user.id,
            course_id=course_id,
            answers={},
            raw_score=0.0,
            adjusted_score=0.0,
            assigned_level=1,
            time_taken_sec=0,
            domain_scores={},
            user_context={
                "professional_role": current_user.professional_role or "",
                "country": current_user.country or "",
                "preferred_language": current_user.preferred_language,
                "skipped": True,
            },
            competency_areas=["Foundation Building"],
            recommendations=["Start from the beginning of the course"],
            can_retake_after=None,
        )
        db.add(attempt)
        await db.commit()

        logger.info(
            "Course pre-assessment skipped",
            user_id=str(current_user.id),
            course_id=str(course_id),
        )

        return {
            "assigned_level": 1,
            "course_id": str(course_id),
            "skipped": True,
            "message": "Pre-assessment skipped. Starting at Level 1.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to skip course pre-assessment",
            error=str(e),
            user_id=str(current_user.id),
            course_id=str(course_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to skip pre-assessment",
        )


@router.get("/status", response_model=CoursePreassessmentStatus)
async def get_course_preassessment_status(
    course_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CoursePreassessmentStatus:
    """Get pre-assessment status for the current user and course.

    Returns enabled, mandatory, completed, skipped, can_retake, next_retake_at.
    Used by frontend to decide redirect logic after onboarding.
    """
    try:
        await _get_course_or_404(course_id, db)

        result = await db.execute(
            select(CoursePreassessment).where(CoursePreassessment.course_id == course_id)
        )
        preassessment = result.scalar_one_or_none()

        if preassessment is None or not preassessment.preassessment_enabled:
            return CoursePreassessmentStatus(
                course_id=course_id,
                enabled=False,
                mandatory=False,
                completed=False,
                skipped=False,
                can_retake=False,
                next_retake_at=None,
            )

        latest_attempt = await _get_latest_attempt(current_user.id, course_id, db)

        now = datetime.utcnow()
        completed = False
        skipped = False
        can_retake = True
        next_retake_at = None

        if latest_attempt is not None:
            skipped = bool(latest_attempt.user_context.get("skipped", False))
            completed = not skipped
            if latest_attempt.can_retake_after and latest_attempt.can_retake_after > now:
                can_retake = False
                next_retake_at = latest_attempt.can_retake_after

        logger.info(
            "Course pre-assessment status retrieved",
            user_id=str(current_user.id),
            course_id=str(course_id),
            completed=completed,
        )

        return CoursePreassessmentStatus(
            course_id=course_id,
            enabled=preassessment.preassessment_enabled,
            mandatory=preassessment.mandatory,
            completed=completed,
            skipped=skipped,
            can_retake=can_retake,
            next_retake_at=next_retake_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get course pre-assessment status",
            error=str(e),
            user_id=str(current_user.id),
            course_id=str(course_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve pre-assessment status",
        )
