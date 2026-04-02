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
    retry_kwargs={"max_retries": 2, "countdown": 30},
    rate_limit="3/m",
    soft_time_limit=15,
    time_limit=20,
)
def generate_lesson_image(
    self,
    lesson_id: str | None,
    module_id: str | None,
    unit_id: str | None,
    lesson_content: str,
) -> dict:
    """Generate a DALL-E 3 illustration for a lesson (fire-and-forget, non-blocking).

    Pipeline:
        1. Claude extracts key concept + semantic tags
        2. Search generated_images for ≥85% Jaccard tag overlap → reuse if found
        3. Otherwise call DALL-E 3, save WebP URL, store bilingual alt-text

    Args:
        lesson_id: UUID string of the GeneratedContent lesson (or None)
        module_id: UUID string of the module (or None)
        unit_id: Unit identifier (or None)
        lesson_content: Full text of the generated lesson

    Returns:
        dict with image_id and status
    """
    logger.info(
        "Starting lesson image generation",
        lesson_id=lesson_id,
        module_id=module_id,
        unit_id=unit_id,
        task_id=self.request.id,
    )

    try:
        import anthropic
        from openai import AsyncOpenAI

        from app.domain.services.image_service import ImageGenerationService
        from app.infrastructure.config.settings import settings
        from app.infrastructure.persistence.database import AsyncSessionLocal

        anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

        service = ImageGenerationService(
            anthropic_client=anthropic_client,
            openai_client=openai_client,
            settings=settings,
        )

        lesson_uuid = uuid.UUID(lesson_id) if lesson_id else None
        module_uuid = uuid.UUID(module_id) if module_id else None

        async def _run():
            async with AsyncSessionLocal() as session:
                return await service.run(
                    session=session,
                    lesson_id=lesson_uuid,
                    module_id=module_uuid,
                    unit_id=unit_id,
                    lesson_content=lesson_content,
                )

        image_id = asyncio.get_event_loop().run_until_complete(_run())

        logger.info(
            "Lesson image generation completed",
            image_id=str(image_id),
            lesson_id=lesson_id,
            task_id=self.request.id,
        )
        return {"image_id": str(image_id), "status": "done"}

    except Exception as exc:
        logger.error(
            "Lesson image generation failed",
            lesson_id=lesson_id,
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
