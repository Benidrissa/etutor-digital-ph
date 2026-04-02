"""Content generation API endpoints."""

import re
import uuid
from collections.abc import AsyncGenerator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.api.deps import get_db
from app.api.deps_local_auth import get_optional_user
from app.api.v1.schemas.content import (
    CaseStudyResponse,
    ErrorResponse,
    FlashcardGenerationRequest,
    FlashcardSetResponse,
    LessonGenerationRequest,
    LessonResponse,
    QuizGenerationRequest,
    QuizResponse,
    StreamingEvent,
)
from app.domain.models.module import Module
from app.domain.services.flashcard_service import FlashcardGenerationService
from app.domain.services.lesson_service import CaseStudyGenerationService, LessonGenerationService
from app.domain.services.progress_service import ProgressService
from app.domain.services.quiz_service import QuizService
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()
router = APIRouter(prefix="/content", tags=["content"])


async def _resolve_module_id(module_id: str, session: AsyncSession) -> UUID:
    """
    Resolve module identifier to UUID.

    Accepts both module codes (e.g., "M01") and UUID strings.
    For module codes, looks up the module by module_number.
    For UUIDs, validates and returns the UUID.

    Args:
        module_id: Module code (M01, M02, etc.) or UUID string
        session: Database session

    Returns:
        UUID of the module

    Raises:
        ValueError: If module not found or invalid UUID
    """
    # Try to parse as UUID first
    try:
        return uuid.UUID(module_id)
    except ValueError:
        pass

    # Try to parse as module code (M01, M02, etc.)
    module_code_pattern = re.match(r"^M(\d{2})$", module_id.upper())
    if module_code_pattern:
        module_number = int(module_code_pattern.group(1))

        query = select(Module).where(Module.module_number == module_number)
        result = await session.execute(query)
        module = result.scalar_one_or_none()

        if module:
            return module.id
        else:
            raise ValueError(f"Module with code {module_id} not found")

    # If neither UUID nor valid module code
    raise ValueError(
        f"Invalid module identifier: {module_id}. Expected UUID or module code (M01, M02, etc.)"
    )


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


def get_lesson_service(
    claude_service: ClaudeService = Depends(get_claude_service),
    semantic_retriever: SemanticRetriever = Depends(get_semantic_retriever),
) -> LessonGenerationService:
    """Dependency to get lesson generation service."""
    return LessonGenerationService(claude_service, semantic_retriever)


def get_flashcard_service(
    claude_service: ClaudeService = Depends(get_claude_service),
    semantic_retriever: SemanticRetriever = Depends(get_semantic_retriever),
) -> FlashcardGenerationService:
    """Dependency to get flashcard generation service."""
    return FlashcardGenerationService(claude_service, semantic_retriever)


def get_case_study_service(
    claude_service: ClaudeService = Depends(get_claude_service),
    semantic_retriever: SemanticRetriever = Depends(get_semantic_retriever),
) -> CaseStudyGenerationService:
    """Dependency to get case study generation service."""
    return CaseStudyGenerationService(claude_service, semantic_retriever)


def get_quiz_service(
    claude_service: ClaudeService = Depends(get_claude_service),
    semantic_retriever: SemanticRetriever = Depends(get_semantic_retriever),
) -> QuizService:
    """Dependency to get quiz generation service."""
    return QuizService(claude_service, semantic_retriever)


@router.post(
    "/generate-lesson",
    response_model=LessonResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Module not found"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def generate_lesson(
    request: LessonGenerationRequest,
    lesson_service: LessonGenerationService = Depends(get_lesson_service),
    session: AsyncSession = Depends(get_db),
) -> LessonResponse:
    """
    Generate or retrieve cached lesson content.

    This endpoint generates pedagogical lesson content using RAG (Retrieval-Augmented Generation)
    and Claude API. It performs the following steps:

    1. **Cache Check**: First checks if lesson already exists in cache
    2. **RAG Retrieval**: Searches top-8 relevant chunks from vector store
    3. **Content Generation**: Uses Claude API with specialized pedagogical prompts
    4. **Caching**: Stores generated content for future requests

    The generated lesson includes:
    - Contextualized introduction for West Africa
    - Key concepts adapted to user's level
    - Concrete examples from user's country/region
    - Synthesis and key takeaways
    - Source citations from reference materials

    **Rate Limiting**: Content generation is subject to API limits.
    Use streaming endpoint for real-time generation feedback.
    """
    try:
        logger.info(
            "Lesson generation requested",
            module_id=str(request.module_id),
            unit_id=request.unit_id,
            language=request.language,
            country=request.country,
            level=request.level,
        )

        lesson_response = await lesson_service.get_or_generate_lesson(
            module_id=request.module_id,
            unit_id=request.unit_id,
            language=request.language,
            country=request.country,
            level=request.level,
            session=session,
        )

        logger.info(
            "Lesson generation completed",
            lesson_id=str(lesson_response.id),
            cached=lesson_response.cached,
        )

        return lesson_response

    except ValueError as e:
        logger.warning("Invalid lesson generation request", error=str(e))
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
        logger.error("Lesson generation failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "generation_failed",
                "message": "Une erreur interne s'est produite lors de la génération",
            },
        )


@router.post(
    "/generate-lesson/stream",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid request"},
        404: {"description": "Module not found"},
        500: {"description": "Generation failed"},
    },
)
async def stream_lesson_generation(
    request: LessonGenerationRequest,
    lesson_service: LessonGenerationService = Depends(get_lesson_service),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Stream lesson generation in real-time using Server-Sent Events (SSE).

    This endpoint provides real-time feedback during lesson generation:

    **Event Types:**
    - `chunk`: Incremental content as it's generated
    - `complete`: Final lesson object when generation finishes
    - `error`: Error information if generation fails

    **Response Format:**
    ```
    event: chunk
    data: "Generating lesson content..."

    event: complete
    data: {"id": "...", "content": {...}, ...}
    ```

    **Client Implementation:**
    ```javascript
    const eventSource = new EventSource('/api/v1/content/generate-lesson/stream');
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        // Handle streaming updates
    };
    ```

    **Benefits:**
    - Real-time progress feedback (critical for 8s+ generation time)
    - Better UX on slow connections (2G/3G Africa)
    - Client can display loading states and partial content
    """

    async def generate_events() -> AsyncGenerator[str, None]:
        """Generate SSE events for streaming response."""
        try:
            logger.info(
                "Starting lesson streaming generation",
                module_id=str(request.module_id),
                unit_id=request.unit_id,
            )

            async for event in lesson_service.stream_lesson_generation(
                module_id=request.module_id,
                unit_id=request.unit_id,
                language=request.language,
                country=request.country,
                level=request.level,
                session=session,
            ):
                yield event.to_sse_format()

            logger.info("Lesson streaming generation completed")

        except Exception as e:
            logger.error("Lesson streaming generation failed", error=str(e), exc_info=True)
            error_event = StreamingEvent(
                event="error",
                data={
                    "error": "streaming_failed",
                    "message": "Erreur lors de la génération en streaming",
                },
            )
            yield error_event.to_sse_format()

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        },
    )


@router.get(
    "/lessons/{module_id}/{unit_id}",
    response_model=LessonResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Module or unit not found"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def get_or_generate_lesson_by_module_and_unit(
    module_id: str,
    unit_id: str,
    language: str = "fr",
    level: int = 1,
    country: str = "SN",
    lesson_service: LessonGenerationService = Depends(get_lesson_service),
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
) -> LessonResponse:
    """
    Get or generate lesson content by module and unit ID.

    This endpoint provides the main interface for the frontend to request lessons.
    It accepts both module codes (e.g., "M01") and UUIDs, resolving codes to UUIDs
    automatically via database lookup.

    When authenticated, accessing this endpoint marks the module as in_progress
    in user_module_progress (FR-02.2).

    **Parameters:**
    - **module_id**: Module identifier (code like "M01" or UUID string)
    - **unit_id**: Unit identifier (e.g., "M01-U03")
    - **language**: Content language ("fr" or "en")
    - **level**: User's level (1-4)
    - **country**: Country context for examples (ISO 2-letter code)

    **Returns:**
    - Cached lesson if available
    - Newly generated lesson if not cached
    - Error if module/unit not found
    """
    try:
        logger.info(
            "Lesson request by module/unit",
            module_id=module_id,
            unit_id=unit_id,
            language=language,
            level=level,
            country=country,
        )

        # Resolve module_id to UUID if it's a module code
        resolved_module_id = await _resolve_module_id(module_id, session)

        lesson_response = await lesson_service.get_or_generate_lesson(
            module_id=resolved_module_id,
            unit_id=unit_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        # Track lesson access for authenticated users
        if current_user is not None:
            try:
                from uuid import UUID as _UUID

                progress_service = ProgressService(session)
                await progress_service.track_lesson_access(
                    user_id=_UUID(str(current_user.id)),
                    module_id=resolved_module_id,
                    lesson_id=lesson_response.id,
                )
            except Exception as track_err:
                logger.warning(
                    "Failed to track lesson access (non-fatal)",
                    error=str(track_err),
                )

        logger.info(
            "Lesson request completed",
            lesson_id=str(lesson_response.id),
            cached=lesson_response.cached,
        )

        return lesson_response

    except ValueError as e:
        logger.warning("Invalid lesson request", error=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "module_or_unit_not_found", "message": str(e)},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_request", "message": str(e)},
            )

    except Exception as e:
        logger.error("Lesson request failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "generation_failed",
                "message": "Une erreur interne s'est produite lors de la génération",
            },
        )


@router.get(
    "/lessons/{module_id}/{unit_id}/stream",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid request"},
        404: {"description": "Module or unit not found"},
        500: {"description": "Generation failed"},
    },
)
async def stream_lesson_by_module_and_unit(
    module_id: str,
    unit_id: str,
    language: str = "fr",
    level: int = 1,
    country: str = "SN",
    lesson_service: LessonGenerationService = Depends(get_lesson_service),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Stream lesson generation by module and unit ID in real-time using Server-Sent Events (SSE).

    **Parameters:**
    - **module_id**: Module identifier (code like "M01" or UUID string)
    - **unit_id**: Unit identifier (e.g., "M01-U03")
    - **language**: Content language ("fr" or "en")
    - **level**: User's level (1-4)
    - **country**: Country context for examples (ISO 2-letter code)

    **Event Types:**
    - `chunk`: Incremental content as it's generated
    - `complete`: Final lesson object when generation finishes
    - `error`: Error information if generation fails
    """

    async def generate_events() -> AsyncGenerator[str, None]:
        """Generate SSE events for streaming response."""
        try:
            logger.info(
                "Starting lesson streaming by module/unit",
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                level=level,
                country=country,
            )

            # Resolve module_id to UUID if it's a module code
            resolved_module_id = await _resolve_module_id(module_id, session)

            async for event in lesson_service.stream_lesson_generation(
                module_id=resolved_module_id,
                unit_id=unit_id,
                language=language,
                country=country,
                level=level,
                session=session,
            ):
                yield event.to_sse_format()

            logger.info("Lesson streaming generation completed")

        except Exception as e:
            logger.error("Lesson streaming generation failed", error=str(e), exc_info=True)
            error_event = StreamingEvent(
                event="error",
                data={
                    "error": "streaming_failed",
                    "message": "Erreur lors de la génération en streaming",
                },
            )
            yield error_event.to_sse_format()

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        },
    )


@router.get(
    "/lessons/{lesson_id}",
    response_model=LessonResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Lesson not found"},
    },
)
async def get_lesson(
    lesson_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> LessonResponse:
    """
    Retrieve a previously generated lesson by ID.

    **Use Cases:**
    - Retrieve cached lessons for offline viewing
    - Load lessons from bookmarks/favorites
    - Delta sync for mobile clients

    **Caching Strategy:**
    - Lessons are cached indefinitely once generated
    - Content validation flag indicates quality review status
    - Cache invalidation only on manual content updates
    """
    from sqlalchemy import select

    from app.domain.models.content import GeneratedContent

    try:
        query = select(GeneratedContent).where(
            GeneratedContent.id == lesson_id,
            GeneratedContent.content_type == "lesson",
        )
        result = await session.execute(query)
        lesson_content = result.scalar_one_or_none()

        if not lesson_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "lesson_not_found", "message": f"Lesson {lesson_id} not found"},
            )

        from app.api.v1.schemas.content import LessonContent

        return LessonResponse(
            id=lesson_content.id,
            module_id=lesson_content.module_id,
            unit_id=lesson_content.content.get("unit_id", ""),
            language=lesson_content.language,
            level=lesson_content.level,
            country_context=lesson_content.country_context or "",
            content=LessonContent(**lesson_content.content),
            generated_at=lesson_content.generated_at.isoformat(),
            cached=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to retrieve lesson", lesson_id=str(lesson_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "retrieval_failed", "message": "Failed to retrieve lesson"},
        )


@router.post(
    "/generate-flashcards",
    response_model=FlashcardSetResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Module not found"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def generate_flashcards(
    request: FlashcardGenerationRequest,
    flashcard_service: FlashcardGenerationService = Depends(get_flashcard_service),
    session: AsyncSession = Depends(get_db),
) -> FlashcardSetResponse:
    """
    Generate or retrieve cached bilingual flashcard set.

    This endpoint generates 15-30 bilingual flashcards using RAG (Retrieval-Augmented Generation)
    and Claude API. It performs the following steps:

    1. **Cache Check**: First checks if flashcard set already exists in cache
    2. **RAG Retrieval**: Searches top-12 relevant chunks from vector store
    3. **Content Generation**: Uses Claude API with specialized flashcard prompts
    4. **Caching**: Stores generated content for future requests

    Each flashcard includes:
    - **term**: Key concept or terminology
    - **definition_fr**: French definition (50-100 words)
    - **definition_en**: English definition (50-100 words)
    - **example_aof**: Concrete West African example (1-2 sentences)
    - **formula**: LaTeX mathematical formula if applicable
    - **sources_cited**: Source references from textbooks

    **Content Types Supported:**
    - Public health terminology and definitions
    - Epidemiological concepts and methods
    - Biostatistics formulas (Triola textbook)
    - Health system indicators (WHO, DHIS2)
    - Country-specific examples from ECOWAS region

    **LaTeX Support**: Mathematical formulas are rendered using LaTeX syntax.
    Example: `$\\frac{\\text{cases}}{\\text{population}} \\times 100,000$`

    **Rate Limiting**: Content generation is subject to API limits.
    Cached results are returned instantly.
    """
    try:
        logger.info(
            "Flashcard generation requested",
            module_id=str(request.module_id),
            language=request.language,
            country=request.country,
            level=request.level,
        )

        flashcard_response = await flashcard_service.get_or_generate_flashcard_set(
            module_id=request.module_id,
            language=request.language,
            country=request.country,
            level=request.level,
            session=session,
        )

        logger.info(
            "Flashcard generation completed",
            flashcard_set_id=str(flashcard_response.id),
            flashcard_count=len(flashcard_response.flashcards),
            cached=flashcard_response.cached,
        )

        return flashcard_response

    except ValueError as e:
        logger.warning("Invalid flashcard generation request", error=str(e))
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
        logger.error("Flashcard generation failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "generation_failed",
                "message": "Une erreur interne s'est produite lors de la génération des flashcards",
            },
        )


@router.post(
    "/generate-quiz",
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
    Generate formative quiz with 10 multiple-choice questions.

    This endpoint generates quiz content using RAG (Retrieval-Augmented Generation)
    and Claude API. It performs the following steps:

    1. **Cache Check**: First checks if quiz already exists in cache
    2. **RAG Retrieval**: Searches top-8 relevant chunks from vector store
    3. **Content Generation**: Uses Claude API with specialized quiz prompts
    4. **Caching**: Stores generated content for future requests

    The generated quiz includes:
    - Exactly 10 multiple-choice questions with 4 options each
    - Difficulty distribution: 3 easy, 4 medium, 3 hard
    - Detailed explanations for each correct answer
    - Source citations from reference materials
    - Estimated completion time (typically 15 minutes)

    **Question Types:**
    - **Easy**: Definitions, basic concepts, memorization
    - **Medium**: Practical application, simple analysis, comparisons
    - **Hard**: Critical analysis, synthesis, complex cases

    **Rate Limiting**: Content generation is subject to API limits.
    Cache lookup is used for repeated requests.
    """
    try:
        logger.info(
            "Quiz generation requested",
            module_id=str(request.module_id),
            unit_id=request.unit_id,
            language=request.language,
            difficulty_level=request.difficulty_level,
        )

        quiz_response = await quiz_service.get_or_generate_quiz(
            module_id=request.module_id,
            unit_id=request.unit_id,
            language=request.language,
            difficulty_level=request.difficulty_level,
            session=session,
        )

        logger.info(
            "Quiz generation completed",
            quiz_id=str(quiz_response.id),
            cached=quiz_response.cached,
            questions_count=len(quiz_response.content.questions),
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
                "message": "Une erreur interne s'est produite lors de la génération du quiz",
            },
        )


@router.get(
    "/quizzes/{quiz_id}",
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
    - Retrieve cached quizzes for review
    - Load quizzes for retaking or practice
    - Delta sync for mobile clients

    **Caching Strategy:**
    - Quizzes are cached indefinitely once generated
    - Content validation flag indicates quality review status
    - Cache invalidation only on manual content updates
    """
    from sqlalchemy import select

    from app.domain.models.content import GeneratedContent

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

        from app.api.v1.schemas.content import QuizContent

        # Extract metadata
        unit_id = quiz_content.content.get("unit_id", "")
        difficulty_level = quiz_content.content.get("difficulty_level", "medium")

        return QuizResponse(
            id=quiz_content.id,
            module_id=quiz_content.module_id,
            unit_id=unit_id,
            language=quiz_content.language,
            difficulty_level=difficulty_level,
            content=QuizContent(
                **{
                    "title": quiz_content.content.get("title", "Quiz"),
                    "questions": quiz_content.content.get("questions", []),
                    "estimated_duration_minutes": quiz_content.content.get(
                        "estimated_duration_minutes", 15
                    ),
                    "sources_cited": quiz_content.content.get("sources_cited", []),
                }
            ),
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


# ── Case Study Endpoints ────────────────────────────────────────────────────


@router.get(
    "/cases/{module_id}/{unit_id}",
    response_model=CaseStudyResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Module or unit not found"},
        500: {"model": ErrorResponse, "description": "Generation failed"},
    },
)
async def get_or_generate_case_study(
    module_id: str,
    unit_id: str,
    language: str = "fr",
    level: int = 1,
    country: str = "SN",
    case_study_service: CaseStudyGenerationService = Depends(get_case_study_service),
    session: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
) -> CaseStudyResponse:
    """
    Get or generate case study content by module and unit ID.

    **Parameters:**
    - **module_id**: Module identifier (code like "M01" or UUID string)
    - **unit_id**: Unit identifier (e.g., "M01-U05")
    - **language**: Content language ("fr" or "en")
    - **level**: User's level (1-4)
    - **country**: Country context for examples (ISO 2-letter code)
    """
    try:
        logger.info(
            "Case study request",
            module_id=module_id,
            unit_id=unit_id,
            language=language,
            level=level,
            country=country,
        )

        resolved_module_id = await _resolve_module_id(module_id, session)

        case_study_response = await case_study_service.get_or_generate_case_study(
            module_id=resolved_module_id,
            unit_id=unit_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        if current_user is not None:
            try:
                from uuid import UUID as _UUID

                progress_service = ProgressService(session)
                await progress_service.track_lesson_access(
                    user_id=_UUID(str(current_user.id)),
                    module_id=resolved_module_id,
                    lesson_id=case_study_response.id,
                )
            except Exception as track_err:
                logger.warning(
                    "Failed to track case study access (non-fatal)",
                    error=str(track_err),
                )

        logger.info(
            "Case study request completed",
            case_study_id=str(case_study_response.id),
            cached=case_study_response.cached,
        )

        return case_study_response

    except ValueError as e:
        logger.warning("Invalid case study request", error=str(e))
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "module_or_unit_not_found", "message": str(e)},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_request", "message": str(e)},
            )

    except Exception as e:
        logger.error("Case study request failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "generation_failed",
                "message": "Une erreur interne s'est produite lors de la génération",
            },
        )


@router.get(
    "/cases/{module_id}/{unit_id}/stream",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid request"},
        404: {"description": "Module or unit not found"},
        500: {"description": "Generation failed"},
    },
)
async def stream_case_study_by_module_and_unit(
    module_id: str,
    unit_id: str,
    language: str = "fr",
    level: int = 1,
    country: str = "SN",
    case_study_service: CaseStudyGenerationService = Depends(get_case_study_service),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Stream case study generation by module and unit ID using Server-Sent Events (SSE).

    **Event Types:**
    - `chunk`: Incremental content as it's generated
    - `complete`: Final case study object when generation finishes
    - `error`: Error information if generation fails
    """

    async def generate_events() -> AsyncGenerator[str, None]:
        try:
            logger.info(
                "Starting case study streaming",
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                level=level,
                country=country,
            )

            resolved_module_id = await _resolve_module_id(module_id, session)

            async for event in case_study_service.stream_case_study_generation(
                module_id=resolved_module_id,
                unit_id=unit_id,
                language=language,
                country=country,
                level=level,
                session=session,
            ):
                yield event.to_sse_format()

            logger.info("Case study streaming completed")

        except Exception as e:
            logger.error("Case study streaming failed", error=str(e), exc_info=True)
            error_event = StreamingEvent(
                event="error",
                data={
                    "error": "streaming_failed",
                    "message": "Erreur lors de la génération en streaming",
                },
            )
            yield error_event.to_sse_format()

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        },
    )
