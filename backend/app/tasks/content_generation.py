"""Celery tasks for AI content generation."""

import asyncio
import uuid

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


class CallbackTask(Task):
    """Base task class with callbacks for content generation."""

    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        logger.info("Content generation task completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails."""
        logger.error(
            "Content generation task failed",
            task_id=task_id,
            exception=str(exc),
            traceback=einfo.traceback,
        )


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    rate_limit="5/m",  # 5 tasks per minute
)
def generate_lesson_bulk(self, module_id: str, language: str = "fr", country: str = "SN") -> dict:
    """Generate lessons for a module in bulk (async background task).

    Args:
        module_id: UUID of the module
        language: Language code (fr/en)
        country: Country code for contextualization

    Returns:
        dict: Task result with generated lesson IDs
    """
    logger.info(
        "Starting bulk lesson generation",
        module_id=module_id,
        language=language,
        country=country,
        task_id=self.request.id,
    )

    try:
        # TODO: Implement lesson generation logic
        # This will use the RAG pipeline from app.ai.rag.generator
        # For now, return a placeholder
        result = {
            "module_id": module_id,
            "language": language,
            "country": country,
            "lessons_generated": 0,
            "status": "pending_implementation",
        }

        logger.info(
            "Bulk lesson generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )

        return result

    except Exception as exc:
        logger.error(
            "Bulk lesson generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        raise


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    rate_limit="10/m",  # 10 tasks per minute
)
def generate_quiz_questions(
    self, module_id: str, count: int = 20, difficulty: str = "medium"
) -> dict:
    """Generate quiz questions for a module.

    Args:
        module_id: UUID of the module
        count: Number of questions to generate
        difficulty: Question difficulty level

    Returns:
        dict: Task result with generated question IDs
    """
    logger.info(
        "Starting quiz question generation",
        module_id=module_id,
        count=count,
        difficulty=difficulty,
        task_id=self.request.id,
    )

    try:
        # TODO: Implement quiz generation logic
        # This will use the RAG pipeline and CAT algorithm
        result = {
            "module_id": module_id,
            "questions_generated": 0,
            "difficulty": difficulty,
            "status": "pending_implementation",
        }

        logger.info(
            "Quiz question generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )

        return result

    except Exception as exc:
        logger.error(
            "Quiz question generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        raise


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    rate_limit="15/m",  # 15 tasks per minute
)
def generate_flashcards(self, module_id: str, language: str = "fr", count: int = 30) -> dict:
    """Generate flashcards for a module.

    Args:
        module_id: UUID of the module
        language: Language for flashcard content
        count: Number of flashcards to generate

    Returns:
        dict: Task result with generated flashcard IDs
    """
    logger.info(
        "Starting flashcard generation",
        module_id=module_id,
        language=language,
        count=count,
        task_id=self.request.id,
    )

    try:
        # TODO: Implement flashcard generation logic
        result = {
            "module_id": module_id,
            "language": language,
            "flashcards_generated": 0,
            "status": "pending_implementation",
        }

        logger.info(
            "Flashcard generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )

        return result

    except Exception as exc:
        logger.error(
            "Flashcard generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        raise


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    rate_limit="3/m",
    time_limit=60,
    soft_time_limit=55,
)
def generate_lesson_image(
    self,
    lesson_id: str,
    module_id: str,
    unit_id: str,
    lesson_content: str,
) -> dict:
    """Async Celery task to generate a DALL-E 3 illustration for a lesson (US-025, FR-03.2).

    Pipeline:
    1. Claude API extracts key concept + generates DALL-E prompt + semantic tags
    2. Check generated_images for semantic tag overlap >= 85%
    3. If match found: reuse image (increment reuse_count), skip DALL-E
    4. If no match: call DALL-E 3, save as WebP (max 512px), store metadata
    5. Generate FR/EN alt-text for accessibility

    Status transitions: pending -> generating -> ready | failed
    Lesson content is served independently (non-blocking).

    Args:
        lesson_id: UUID of the lesson (GeneratedContent.id)
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        lesson_content: Full lesson text for concept extraction

    Returns:
        dict with image_id, status, reused flag
    """
    logger.info(
        "Starting lesson image generation",
        lesson_id=lesson_id,
        module_id=module_id,
        unit_id=unit_id,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.domain.services.image_service import ImageGenerationService
        from app.infrastructure.config.settings import settings

        engine = create_async_engine(settings.database_url, echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with session_factory() as session:
                service = ImageGenerationService()
                image = await service.process_lesson_image(
                    lesson_id=uuid.UUID(lesson_id),
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    lesson_content=lesson_content,
                    session=session,
                )
                reused = bool(image.extra_metadata and image.extra_metadata.get("reused_from"))
                return {
                    "image_id": str(image.id),
                    "status": image.status,
                    "reused": reused,
                    "lesson_id": lesson_id,
                    "module_id": module_id,
                    "unit_id": unit_id,
                }
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Lesson image generation completed",
            lesson_id=lesson_id,
            result=result,
            task_id=self.request.id,
        )
        return result

    except Exception as exc:
        logger.error(
            "Lesson image generation failed",
            lesson_id=lesson_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        raise
