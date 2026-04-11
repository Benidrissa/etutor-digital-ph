"""Quiz API endpoints for generating and taking quizzes."""

import re
import uuid
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_active_subscription
from app.api.v1.schemas.quiz import (
    ErrorResponse,
    QuizAttemptRequest,
    QuizAttemptResponse,
    QuizAttemptResult,
    QuizGenerationRequest,
    QuizResponse,
    SummativeAssessmentAttemptCheck,
    SummativeAssessmentRequest,
    SummativeAssessmentResponse,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress
from app.domain.models.quiz import QuizAttempt, SummativeAssessmentAttempt
from app.domain.services.analytics_service import AnalyticsService
from app.domain.services.platform_settings_service import SettingsCache
from app.domain.services.progress_service import ProgressService
from app.domain.services.quiz_service import QuizService
from app.infrastructure.config.settings import get_settings
from app.tasks.content_generation import generate_quiz_task

logger = structlog.get_logger()
router = APIRouter(prefix="/quiz", tags=["quiz"])


async def _check_subscription_or_first_unit(user: AuthenticatedUser, unit_id: str) -> None:
    """Allow free units of a module; require subscription for others.

    The number of free units is controlled by the 'subscription-free-units-count' platform
    setting (default: 2). Admin users always bypass this check.
    Falls back to DB ModuleUnit.order_index check when unit_id format is unrecognised.
    Raises 403 with code 'subscription_required' if no subscription.
    """
    import uuid as _uuid

    from app.domain.models.module_unit import ModuleUnit
    from app.domain.services.subscription_service import SubscriptionService
    from app.infrastructure.persistence.database import get_db_session

    if user.role in ("admin", "sub_admin"):
        return

    free_count = SettingsCache.instance().get("subscription-free-units-count", 2)
    m = re.search(r"-U0*(\d+)$", unit_id.upper()) if unit_id else None
    if m and int(m.group(1)) <= free_count:
        return

    async for session in get_db_session():
        sub = await SubscriptionService().get_active_subscription(_uuid.UUID(user.id), session)
        if sub is not None:
            return

        if unit_id:
            result = await session.execute(
                select(ModuleUnit.order_index).where(ModuleUnit.unit_number == unit_id)
            )
            order = result.scalar_one_or_none()
            if order is not None and order < free_count:
                return
        break

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "subscription_required",
            "message": "An active subscription is required to access this content. The first lesson of each module is free.",
        },
    )


async def _resolve_module_uuid(module_id_str: str, session: AsyncSession) -> UUID:
    """
    Resolve a module identifier to a UUID.

    Accepts:
    - A bare UUID string (e.g. "123e4567-e89b-12d3-a456-426614174000")
    - A module-number shorthand (e.g. "M01", "m1", "1")

    Raises ValueError if not found.
    """
    try:
        return UUID(module_id_str)
    except ValueError:
        pass

    # Extract the numeric part from strings like "M01", "M1", "01", "1"
    match = re.fullmatch(r"[Mm]?0*(\d+)", module_id_str.strip())
    if not match:
        raise ValueError(f"Module '{module_id_str}' not found")
    module_number = int(match.group(1))

    result = await session.execute(select(Module).where(Module.module_number == module_number))
    module = result.scalar_one_or_none()
    if not module:
        raise ValueError(f"Module '{module_id_str}' not found")
    return module.id


def get_claude_service() -> ClaudeService:
    """Dependency to get Claude service."""
    return ClaudeService()


def get_semantic_retriever() -> SemanticRetriever:
    """Dependency to get semantic retriever."""
    settings = get_settings()
    embedding_service = EmbeddingService(
        api_key=settings.openai_api_key, model=settings.embedding_model
    )
    return SemanticRetriever(embedding_service)


def get_quiz_service(
    claude_service: ClaudeService = Depends(get_claude_service),
    semantic_retriever: SemanticRetriever = Depends(get_semantic_retriever),
) -> QuizService:
    """Dependency to get quiz service."""
    return QuizService(claude_service, semantic_retriever)


@router.post(
    "/generate",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"model": QuizResponse, "description": "Cached quiz returned"},
        202: {"description": "Generation dispatched, poll /api/v1/content/status/{task_id}"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Module not found"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def generate_quiz(
    request: QuizGenerationRequest,
    quiz_service: QuizService = Depends(get_quiz_service),
    session: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    """
    Generate or retrieve cached quiz content.

    **Cache HIT (200):** Returns the cached quiz immediately.

    **Cache MISS (202):** Dispatches a background Celery task and returns:
    ```json
    {"status": "generating", "task_id": "<uuid>", "message": "Content is being generated"}
    ```
    Poll `GET /api/v1/content/status/{task_id}` every 3 seconds.
    When status is "complete", re-POST to this endpoint to get the cached quiz.

    The generated quiz includes:
    - 5-15 multiple choice questions (default: 10)
    - Explanations for each correct answer
    - Source citations from reference materials
    - Difficulty progression from easy to hard
    - Country-contextualized examples
    """
    try:
        await _check_subscription_or_first_unit(current_user, request.unit_id)

        module_uuid = await _resolve_module_uuid(request.module_id, session)

        logger.info(
            "Quiz generation requested",
            module_id=str(module_uuid),
            unit_id=request.unit_id,
            language=request.language,
            country=request.country,
            level=request.level,
            num_questions=request.num_questions,
        )

        if not request.force_regenerate:
            cached_query = (
                select(GeneratedContent)
                .where(GeneratedContent.module_id == module_uuid)
                .where(GeneratedContent.content_type == "quiz")
                .where(GeneratedContent.language == request.language)
                .where(GeneratedContent.level == request.level)
                .where(GeneratedContent.country_context == request.country)
                .where(GeneratedContent.content["unit_id"].astext == request.unit_id)
                .order_by(GeneratedContent.generated_at.desc())
            )
            cache_result = await session.execute(cached_query)
            cached = cache_result.scalars().first()

            if cached:
                from app.api.v1.schemas.quiz import QuizContent as _QuizContent

                content_dict = {k: v for k, v in cached.content.items() if k != "unit_id"}
                quiz_response = QuizResponse(
                    id=cached.id,
                    module_id=cached.module_id,
                    unit_id=cached.content.get("unit_id", request.unit_id),
                    language=cached.language,
                    level=cached.level,
                    country_context=cached.country_context or request.country,
                    content=_QuizContent(**content_dict),
                    generated_at=cached.generated_at.isoformat(),
                    cached=True,
                )
                logger.info("Quiz cache hit", quiz_id=str(quiz_response.id))
                return JSONResponse(
                    content=quiz_response.model_dump(mode="json"),
                    status_code=status.HTTP_200_OK,
                )

        task = generate_quiz_task.delay(
            str(module_uuid),
            request.unit_id,
            request.language,
            request.country,
            request.level,
            request.num_questions,
        )

        logger.info(
            "Quiz generation dispatched",
            module_id=str(module_uuid),
            unit_id=request.unit_id,
            task_id=task.id,
        )

        return JSONResponse(
            content={
                "status": "generating",
                "task_id": task.id,
                "message": "Content is being generated",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    except HTTPException:
        raise

    except ValueError as e:
        logger.warning("Invalid quiz generation request", error=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "module_not_found", "message": str(e)},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_request", "message": str(e)},
            )

    except Exception as e:
        logger.error("Quiz generation failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "generation_failed",
                "message": "Quiz generation failed due to internal error",
            },
        )


@router.get(
    "/{quiz_id}",
    response_model=QuizResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Quiz not found"},
    },
)
async def get_quiz(
    quiz_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> QuizResponse:
    """
    Retrieve a previously generated quiz by ID.

    **Use Cases:**
    - Load quiz for a new attempt
    - Review quiz content before starting
    - Offline quiz access for mobile clients
    """
    try:
        query = select(GeneratedContent).where(
            GeneratedContent.id == quiz_id,
            GeneratedContent.content_type == "quiz",
        )
        result = await session.execute(query)
        quiz_content = result.scalar_one_or_none()

        if not quiz_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "quiz_not_found", "message": f"Quiz {quiz_id} not found"},
            )

        from app.api.v1.schemas.quiz import QuizContent

        return QuizResponse(
            id=quiz_content.id,
            module_id=quiz_content.module_id,
            unit_id=quiz_content.content.get("unit_id", ""),
            language=quiz_content.language,
            level=quiz_content.level,
            country_context=quiz_content.country_context or "",
            content=QuizContent(**quiz_content.content),
            generated_at=quiz_content.generated_at.isoformat(),
            cached=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to retrieve quiz", quiz_id=str(quiz_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "retrieval_failed", "message": "Failed to retrieve quiz"},
        )


@router.post(
    "/attempt",
    response_model=QuizAttemptResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid submission"},
        404: {"model": ErrorResponse, "description": "Quiz not found"},
        500: {"model": ErrorResponse, "description": "Submission failed"},
    },
)
async def submit_quiz_attempt(
    request: QuizAttemptRequest,
    session: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> QuizAttemptResponse:
    """
    Submit a completed quiz attempt and get immediate feedback.

    **Process:**
    1. Validate quiz exists and answers match question count
    2. Calculate score and per-question results
    3. Store attempt in database
    4. Return detailed feedback with explanations

    **Scoring:**
    - Each question worth equal points (100 / num_questions)
    - Final score rounded to 1 decimal place
    - Pass/fail determined by quiz.passing_score threshold

    **Rate Limiting:** Users can retake quizzes unlimited times.
    """
    try:
        user_id = uuid.UUID(str(current_user.id))

        logger.info(
            "Quiz attempt submitted",
            quiz_id=str(request.quiz_id),
            user_id=str(user_id),
            total_time=request.total_time_seconds,
            num_answers=len(request.answers),
        )

        # Retrieve the quiz content
        query = select(GeneratedContent).where(
            GeneratedContent.id == request.quiz_id,
            GeneratedContent.content_type == "quiz",
        )
        result = await session.execute(query)
        quiz_content = result.scalar_one_or_none()

        if not quiz_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "quiz_not_found", "message": f"Quiz {request.quiz_id} not found"},
            )

        await _check_subscription_or_first_unit(
            current_user, quiz_content.content.get("unit_id", "")
        )

        quiz_data = quiz_content.content
        questions = quiz_data["questions"]

        # Validate answer count matches question count
        if len(request.answers) != len(questions):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "answer_count_mismatch",
                    "message": f"Expected {len(questions)} answers, got {len(request.answers)}",
                },
            )

        # Calculate results
        correct_count = 0
        results = []

        # Create question lookup for O(1) access
        question_lookup = {q["id"]: q for q in questions}

        for answer in request.answers:
            question = question_lookup.get(answer.question_id)
            if not question:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "invalid_question_id",
                        "message": f"Question {answer.question_id} not found in quiz",
                    },
                )

            is_correct = answer.selected_option == question["correct_answer"]
            if is_correct:
                correct_count += 1

            results.append(
                QuizAttemptResult(
                    question_id=answer.question_id,
                    user_answer=answer.selected_option,
                    correct_answer=question["correct_answer"],
                    is_correct=is_correct,
                    explanation=question["explanation"],
                    time_taken_seconds=answer.time_taken_seconds,
                )
            )

        # Calculate final score
        score = round((correct_count / len(questions)) * 100, 1)
        _quiz_passing = SettingsCache.instance().get("quiz-passing-score", 80.0)
        passing_score = quiz_data.get("passing_score", _quiz_passing)
        passed = score >= passing_score
        lesson_validated = score >= _quiz_passing

        # Store attempt in database
        attempt = QuizAttempt(
            id=uuid.uuid4(),
            user_id=user_id,
            quiz_id=request.quiz_id,
            answers={
                "answers": [
                    {
                        "question_id": ans.question_id,
                        "selected_option": ans.selected_option,
                        "time_taken_seconds": ans.time_taken_seconds,
                    }
                    for ans in request.answers
                ],
                "results": [
                    {
                        "question_id": res.question_id,
                        "is_correct": res.is_correct,
                        "user_answer": res.user_answer,
                        "correct_answer": res.correct_answer,
                    }
                    for res in results
                ],
            },
            score=score,
            time_taken_sec=request.total_time_seconds,
        )

        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)

        # Update module progress when lesson is validated (≥80%) — FR-02.2, FR-03.3
        if lesson_validated:
            try:
                unit_id = quiz_data.get("unit_id", "")
                if unit_id:
                    progress_service = ProgressService(session)
                    await progress_service.update_progress_after_quiz(
                        user_id=user_id,
                        module_id=quiz_content.module_id,
                        unit_id=unit_id,
                        score=score,
                        passed=True,
                    )
            except Exception as progress_err:
                logger.warning(
                    "Failed to update progress after quiz (non-fatal)",
                    error=str(progress_err),
                )

        try:
            analytics_svc = AnalyticsService(session)
            await analytics_svc.ingest_event(
                event_name="quiz_completed",
                properties={
                    "module_id": str(quiz_content.module_id),
                    "score": score,
                    "passed": passed,
                    "duration_seconds": request.total_time_seconds,
                },
                user_id=user_id,
                session_id=None,
            )
        except Exception as analytics_err:
            logger.warning("Analytics event failed (non-fatal)", error=str(analytics_err))

        response = QuizAttemptResponse(
            attempt_id=attempt.id,
            quiz_id=request.quiz_id,
            score=score,
            total_questions=len(questions),
            correct_answers=correct_count,
            total_time_seconds=request.total_time_seconds,
            passed=passed,
            lesson_validated=lesson_validated,
            results=results,
            attempted_at=attempt.attempted_at.isoformat(),
        )

        logger.info(
            "Quiz attempt completed",
            attempt_id=str(attempt.id),
            score=score,
            passed=passed,
            correct_answers=correct_count,
            total_questions=len(questions),
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Quiz attempt submission failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "submission_failed",
                "message": "Failed to submit quiz attempt",
            },
        )


# Summative Assessment Endpoints


@router.post(
    "/summative/generate",
    response_model=QuizResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Module not found"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def generate_summative_assessment(
    request: SummativeAssessmentRequest,
    quiz_service: QuizService = Depends(get_quiz_service),
    session: AsyncSession = Depends(get_db),
) -> QuizResponse:
    """
    Generate or retrieve cached summative assessment content.

    Summative assessments are end-of-module tests with specific requirements:
    - Exactly 20 questions covering all units in the module
    - 80% passing score required
    - No immediate feedback during assessment
    - Results shown only at the end
    - Can gate progression to next module
    """
    try:
        module_uuid = await _resolve_module_uuid(request.module_id, session)

        logger.info(
            "Summative assessment generation requested",
            module_id=str(module_uuid),
            language=request.language,
            country=request.country,
            level=request.level,
        )

        # Generate summative assessment with specific parameters
        quiz_response = await quiz_service.get_or_generate_quiz(
            module_id=module_uuid,
            unit_id="summative",  # Special unit ID for summative assessments
            language=request.language,
            country=request.country,
            level=request.level,
            num_questions=SettingsCache.instance().get("quiz-summative-questions-count", 20),
            session=session,
        )

        # Ensure it's marked as summative in the content
        _summative_passing = SettingsCache.instance().get("quiz-passing-score", 80.0)
        if quiz_response.content.passing_score != _summative_passing:
            quiz_response.content.passing_score = _summative_passing

        logger.info(
            "Summative assessment generation completed",
            assessment_id=str(quiz_response.id),
            cached=quiz_response.cached,
        )

        return quiz_response

    except ValueError as e:
        logger.warning("Invalid summative assessment request", error=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "module_not_found", "message": str(e)},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_request", "message": str(e)},
            )

    except Exception as e:
        logger.error("Summative assessment generation failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "generation_failed",
                "message": "Summative assessment generation failed due to internal error",
            },
        )


@router.get(
    "/summative/{module_id}/can-attempt",
    response_model=SummativeAssessmentAttemptCheck,
    responses={
        404: {"model": ErrorResponse, "description": "Module not found"},
    },
)
async def can_attempt_summative_assessment(
    module_id: UUID,
    session: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_active_subscription),
) -> SummativeAssessmentAttemptCheck:
    """
    Check if user can attempt summative assessment for a module.

    Rules:
    - User can attempt if never attempted before
    - User cannot attempt if already passed (score >= 80%)
    - User must wait 24h after failed attempt before retry
    """
    try:
        # For now, use a dummy user_id until auth is implemented
        user_id = uuid.UUID(str(current_user.id))

        # Check if module exists
        query = select(Module).where(Module.id == module_id)
        result = await session.execute(query)
        module = result.scalar_one_or_none()

        if not module:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "module_not_found", "message": f"Module {module_id} not found"},
            )

        # Check previous attempts
        attempts_query = (
            select(SummativeAssessmentAttempt)
            .where(
                SummativeAssessmentAttempt.user_id == user_id,
                SummativeAssessmentAttempt.module_id == module_id,
            )
            .order_by(SummativeAssessmentAttempt.attempted_at.desc())
        )
        attempts_result = await session.execute(attempts_query)
        attempts = attempts_result.scalars().all()

        if not attempts:
            # No previous attempts - can attempt
            return SummativeAssessmentAttemptCheck(
                can_attempt=True,
                last_attempt_score=None,
                attempt_count=0,
                next_retry_at=None,
                reason=None,
            )

        latest_attempt = attempts[0]
        attempt_count = len(attempts)

        if latest_attempt.passed:
            # Already passed - cannot retry
            return SummativeAssessmentAttemptCheck(
                can_attempt=False,
                last_attempt_score=latest_attempt.score,
                attempt_count=attempt_count,
                next_retry_at=None,
                reason="already_passed",
            )

        # Check 24h cooldown
        from datetime import datetime

        now = datetime.utcnow()
        if latest_attempt.can_retry_at and now < latest_attempt.can_retry_at:
            return SummativeAssessmentAttemptCheck(
                can_attempt=False,
                last_attempt_score=latest_attempt.score,
                attempt_count=attempt_count,
                next_retry_at=latest_attempt.can_retry_at.isoformat(),
                reason="cooldown_active",
            )

        # Can retry
        return SummativeAssessmentAttemptCheck(
            can_attempt=True,
            last_attempt_score=latest_attempt.score,
            attempt_count=attempt_count,
            next_retry_at=None,
            reason=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to check summative attempt eligibility", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "check_failed", "message": "Failed to check attempt eligibility"},
        )


@router.post(
    "/summative/attempt",
    response_model=SummativeAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid submission or cannot attempt"},
        404: {"model": ErrorResponse, "description": "Assessment not found"},
        500: {"model": ErrorResponse, "description": "Submission failed"},
    },
)
async def submit_summative_assessment_attempt(
    request: QuizAttemptRequest,
    session: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_active_subscription),
) -> SummativeAssessmentResponse:
    """
    Submit a completed summative assessment attempt.

    Process:
    1. Verify user can attempt (not passed, not in cooldown)
    2. Validate assessment exists and answers match questions
    3. Calculate score and domain breakdown
    4. Check if user passes (score >= 80%)
    5. Update module progression if passed
    6. Set 24h retry cooldown if failed
    7. Store detailed results
    """
    try:
        # For now, use a dummy user_id until auth is implemented
        user_id = uuid.UUID(str(current_user.id))

        logger.info(
            "Summative assessment attempt submitted",
            assessment_id=str(request.quiz_id),
            user_id=str(user_id),
            total_time=request.total_time_seconds,
            num_answers=len(request.answers),
        )

        # Retrieve the assessment content
        query = select(GeneratedContent).where(
            GeneratedContent.id == request.quiz_id,
            GeneratedContent.content_type == "quiz",
        )
        result = await session.execute(query)
        assessment_content = result.scalar_one_or_none()

        if not assessment_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "assessment_not_found",
                    "message": f"Assessment {request.quiz_id} not found",
                },
            )

        assessment_data = assessment_content.content
        questions = assessment_data["questions"]

        # Validate this is a summative assessment
        _summative_q_count = SettingsCache.instance().get("quiz-summative-questions-count", 20)
        if len(questions) != _summative_q_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "not_summative_assessment",
                    "message": f"This endpoint is only for summative assessments with {_summative_q_count} questions",
                },
            )

        # Check if user can attempt
        can_attempt_response = await can_attempt_summative_assessment(
            assessment_content.module_id, session
        )

        if not can_attempt_response.can_attempt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "cannot_attempt",
                    "message": f"Cannot attempt assessment: {can_attempt_response.reason}",
                    "next_retry_at": can_attempt_response.next_retry_at,
                },
            )

        # Validate answer count
        if len(request.answers) != _summative_q_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "answer_count_mismatch",
                    "message": f"Expected {_summative_q_count} answers, got {len(request.answers)}",
                },
            )

        # Calculate results and domain breakdown
        correct_count = 0
        results = []
        domain_stats = {}  # domain -> {"correct": 0, "total": 0}

        question_lookup = {q["id"]: q for q in questions}

        for answer in request.answers:
            question = question_lookup.get(answer.question_id)
            if not question:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "invalid_question_id",
                        "message": f"Question {answer.question_id} not found in assessment",
                    },
                )

            is_correct = answer.selected_option == question["correct_answer"]
            if is_correct:
                correct_count += 1

            # Track domain performance (extract from question metadata)
            domain = question.get("domain", "general")  # Default domain
            if domain not in domain_stats:
                domain_stats[domain] = {"correct": 0, "total": 0}
            domain_stats[domain]["total"] += 1
            if is_correct:
                domain_stats[domain]["correct"] += 1

            results.append(
                QuizAttemptResult(
                    question_id=answer.question_id,
                    user_answer=answer.selected_option,
                    correct_answer=question["correct_answer"],
                    is_correct=is_correct,
                    explanation=question["explanation"],
                    time_taken_seconds=answer.time_taken_seconds,
                )
            )

        # Calculate final score and pass status
        _summative_passing = SettingsCache.instance().get("quiz-passing-score", 80.0)
        score = round((correct_count / _summative_q_count) * 100, 1)
        passed = score >= _summative_passing

        # Determine next attempt number
        attempt_number = can_attempt_response.attempt_count + 1

        # Set retry cooldown if failed (24 hours)
        from datetime import datetime, timedelta

        can_retry_at = None if passed else datetime.utcnow() + timedelta(hours=24)

        # Check if module should be unlocked
        module_unlocked = False
        if passed:
            # Update user progress and check for next module unlock
            progress_query = select(UserModuleProgress).where(
                UserModuleProgress.user_id == user_id,
                UserModuleProgress.module_id == assessment_content.module_id,
            )
            progress_result = await session.execute(progress_query)
            progress = progress_result.scalar_one_or_none()

            if progress:
                progress.status = "completed"
                progress.completion_pct = 100.0
                module_unlocked = True
            else:
                # Create progress entry
                new_progress = UserModuleProgress(
                    user_id=user_id,
                    module_id=assessment_content.module_id,
                    status="completed",
                    completion_pct=100.0,
                    quiz_score_avg=score,
                    time_spent_minutes=request.total_time_seconds // 60,
                    last_accessed=datetime.utcnow(),
                )
                session.add(new_progress)
                module_unlocked = True

        # Store summative assessment attempt
        attempt = SummativeAssessmentAttempt(
            id=uuid.uuid4(),
            user_id=user_id,
            module_id=assessment_content.module_id,
            assessment_id=request.quiz_id,
            answers={
                "answers": [
                    {
                        "question_id": ans.question_id,
                        "selected_option": ans.selected_option,
                        "time_taken_seconds": ans.time_taken_seconds,
                    }
                    for ans in request.answers
                ],
                "results": [
                    {
                        "question_id": res.question_id,
                        "is_correct": res.is_correct,
                        "user_answer": res.user_answer,
                        "correct_answer": res.correct_answer,
                    }
                    for res in results
                ],
            },
            score=score,
            correct_answers=correct_count,
            time_taken_sec=request.total_time_seconds,
            passed=passed,
            domain_breakdown=domain_stats,
            module_unlocked=module_unlocked,
            attempt_number=attempt_number,
            can_retry_at=can_retry_at,
        )

        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)

        # Touch course interaction for recent-courses ranking
        if assessment_content.module_id:
            try:
                from app.domain.services.progress_service import (
                    touch_course_interaction_by_module,
                )

                await touch_course_interaction_by_module(
                    session, user_id, assessment_content.module_id
                )
            except Exception as touch_err:
                logger.warning("touch_course_interaction failed (non-fatal)", error=str(touch_err))

        response = SummativeAssessmentResponse(
            attempt_id=attempt.id,
            assessment_id=request.quiz_id,
            score=score,
            total_questions=_summative_q_count,
            correct_answers=correct_count,
            total_time_seconds=request.total_time_seconds,
            passed=passed,
            results=results,
            domain_breakdown=domain_stats,
            module_unlocked=module_unlocked,
            can_retry=not passed and can_retry_at is None,
            next_retry_at=can_retry_at.isoformat() if can_retry_at else None,
            attempt_count=attempt_number,
            attempted_at=attempt.attempted_at.isoformat(),
        )

        logger.info(
            "Summative assessment attempt completed",
            attempt_id=str(attempt.id),
            score=score,
            passed=passed,
            correct_answers=correct_count,
            module_unlocked=module_unlocked,
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Summative assessment submission failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "submission_failed",
                "message": "Failed to submit summative assessment attempt",
            },
        )
