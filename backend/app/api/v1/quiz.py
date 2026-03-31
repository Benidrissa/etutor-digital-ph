"""Quiz API endpoints for generating and taking quizzes."""

import uuid
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.api.deps import get_db
from app.api.v1.schemas.quiz import (
    ErrorResponse,
    QuizAttemptRequest,
    QuizAttemptResponse,
    QuizAttemptResult,
    QuizGenerationRequest,
    QuizResponse,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.quiz import QuizAttempt
from app.domain.services.quiz_service import QuizService
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()
router = APIRouter(prefix="/quiz", tags=["quiz"])


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
    response_model=QuizResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Module not found"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def generate_quiz(
    request: QuizGenerationRequest,
    quiz_service: QuizService = Depends(get_quiz_service),
    session: AsyncSession = Depends(get_db),
) -> QuizResponse:
    """
    Generate or retrieve cached quiz content.

    This endpoint generates multiple-choice quiz questions using RAG and Claude API:

    1. **Cache Check**: First checks if quiz already exists in cache
    2. **RAG Retrieval**: Searches relevant chunks from vector store
    3. **Question Generation**: Uses Claude API with quiz-specific prompts
    4. **Validation**: Ensures questions have exactly 4 options with 1 correct answer
    5. **Caching**: Stores generated quiz for future attempts

    The generated quiz includes:
    - 5-15 multiple choice questions (default: 10)
    - Explanations for each correct answer
    - Source citations from reference materials
    - Difficulty progression from easy to hard
    - Country-contextualized examples

    **Rate Limiting**: Quiz generation is subject to API limits.
    """
    try:
        logger.info(
            "Quiz generation requested",
            module_id=str(request.module_id),
            unit_id=request.unit_id,
            language=request.language,
            country=request.country,
            level=request.level,
            num_questions=request.num_questions,
        )

        quiz_response = await quiz_service.get_or_generate_quiz(
            module_id=request.module_id,
            unit_id=request.unit_id,
            language=request.language,
            country=request.country,
            level=request.level,
            num_questions=request.num_questions,
            session=session,
        )

        logger.info(
            "Quiz generation completed",
            quiz_id=str(quiz_response.id),
            cached=quiz_response.cached,
            num_questions=len(quiz_response.content.questions),
        )

        return quiz_response

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
    # user_id: UUID = Depends(get_current_user_id),  # TODO: Add auth dependency
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
        # For now, use a dummy user_id until auth is implemented
        user_id = uuid.uuid4()  # TODO: Replace with actual user from auth

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
        passing_score = quiz_data.get("passing_score", 70.0)
        passed = score >= passing_score

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

        response = QuizAttemptResponse(
            attempt_id=attempt.id,
            quiz_id=request.quiz_id,
            score=score,
            total_questions=len(questions),
            correct_answers=correct_count,
            total_time_seconds=request.total_time_seconds,
            passed=passed,
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
