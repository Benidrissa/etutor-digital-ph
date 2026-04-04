"""Celery tasks for AI content generation."""

import uuid

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

POLL_SOFT_LIMIT = 300
POLL_HARD_LIMIT = 320


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
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_lesson_task(
    self,
    module_id: str,
    unit_id: str,
    language: str,
    country: str,
    level: int,
) -> dict:
    """Generate lesson content via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.lesson_service import LessonGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async lesson generation",
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = LessonGenerationService(ClaudeService(), retriever)
                lesson = await service.get_or_generate_lesson(
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    country=country,
                    level=level,
                    session=session,
                )
                return {"status": "complete", "content_id": str(lesson.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async lesson generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Async lesson generation failed",
            module_id=module_id,
            unit_id=unit_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_case_study_task(
    self,
    module_id: str,
    unit_id: str,
    language: str,
    country: str,
    level: int,
) -> dict:
    """Generate case study content via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.lesson_service import CaseStudyGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async case study generation",
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = CaseStudyGenerationService(ClaudeService(), retriever)
                case_study = await service.get_or_generate_case_study(
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    country=country,
                    level=level,
                    session=session,
                )
                return {"status": "complete", "content_id": str(case_study.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async case study generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Async case study generation failed",
            module_id=module_id,
            unit_id=unit_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_quiz_task(
    self,
    module_id: str,
    unit_id: str,
    language: str,
    country: str,
    level: int,
    num_questions: int = 10,
) -> dict:
    """Generate quiz content via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)
        num_questions: Number of questions to generate

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.quiz_service import QuizService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async quiz generation",
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        country=country,
        level=level,
        num_questions=num_questions,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = QuizService(ClaudeService(), retriever)
                quiz = await service.get_or_generate_quiz(
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    country=country,
                    level=level,
                    num_questions=num_questions,
                    session=session,
                )
                return {"status": "complete", "content_id": str(quiz.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async quiz generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Async quiz generation failed",
            module_id=module_id,
            unit_id=unit_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_flashcard_task(
    self,
    module_id: str,
    language: str,
    country: str,
    level: int,
) -> dict:
    """Generate flashcard set via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.flashcard_service import FlashcardGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async flashcard generation",
        module_id=module_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = FlashcardGenerationService(ClaudeService(), retriever)
                flashcard_set = await service.get_or_generate_flashcard_set(
                    module_id=uuid.UUID(module_id),
                    language=language,
                    country=country,
                    level=level,
                    session=session,
                )
                return {"status": "complete", "content_id": str(flashcard_set.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async flashcard generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Async flashcard generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=120,
    time_limit=150,
    rate_limit="5/m",
)
def generate_lesson_image(
    self,
    lesson_id: str,
    module_id: str,
    unit_id: str,
    lesson_content: str,
) -> dict:
    """Generate an illustration for a lesson asynchronously (fire-and-forget).

    Args:
        lesson_id: UUID of the lesson (GeneratedContent.id)
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        lesson_content: Full lesson text used for concept extraction

    Returns:
        dict with image_id and status
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.image_service import ImageGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting lesson image generation",
        lesson_id=lesson_id,
        module_id=module_id,
        unit_id=unit_id,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = ImageGenerationService()
                image = await service.generate_for_lesson(
                    lesson_id=uuid.UUID(lesson_id),
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    lesson_content=lesson_content,
                    session=session,
                )
                return {"image_id": str(image.id), "status": image.status}
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
        return {"image_id": None, "status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=360,
    time_limit=400,
    rate_limit="3/m",
    priority=3,
)
def prefetch_next_lessons_task(
    self,
    user_id: str,
    module_id: str,
    current_unit_id: str,
    language: str,
    country: str,
    level: int,
    module_number: int | None = None,
) -> dict:
    """Pre-generate the next 2 lessons after current_unit_id for a learner.

    Called after registration, quiz pass, or module unlock to eliminate
    the 'Génération du contenu...' wait on first access.

    Args:
        user_id: UUID of the learner
        module_id: UUID string of the current module, or empty string if module_number given
        current_unit_id: Unit ID like 'M01-U01'; empty string means start of module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)
        module_number: Module number (e.g. 1 for M01); used when module_id is empty

    Returns:
        dict with prefetched unit_ids, skipped (already cached), and errors
    """
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.models.content import GeneratedContent
    from app.domain.models.module import Module
    from app.domain.models.module_unit import ModuleUnit
    from app.domain.services.lesson_service import LessonGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting lesson prefetch",
        user_id=user_id,
        module_id=module_id,
        current_unit_id=current_unit_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _get_next_lesson_unit_ids(
        session: AsyncSession,
        module_uuid: uuid.UUID,
        current_unit_id: str,
        count: int = 2,
    ) -> list[str]:
        """Return unit IDs for the next N lesson-type units after current_unit_id."""
        module_result = await session.execute(select(Module).where(Module.id == module_uuid))
        module = module_result.scalar_one_or_none()
        if not module:
            return []

        units_result = await session.execute(
            select(ModuleUnit)
            .where(ModuleUnit.module_id == module_uuid)
            .order_by(ModuleUnit.order_index)
        )
        all_units = list(units_result.scalars().all())

        current_idx = -1
        if current_unit_id:
            for i, u in enumerate(all_units):
                uid = f"M{module.module_number:02d}-U{u.order_index + 1:02d}"
                has_dot = "." in u.unit_number
                ordinal = int(u.unit_number.split(".")[-1]) if has_dot else 0
                alt_uid = f"M{module.module_number:02d}-U{ordinal:02d}" if has_dot else uid
                if uid == current_unit_id or alt_uid == current_unit_id:
                    current_idx = i
                    break

        next_lessons = []
        for u in all_units[current_idx + 1 :]:
            title = (u.title_fr or u.title_en or "").lower()
            is_quiz_or_case = any(
                kw in title
                for kw in ("quiz", "évaluation", "evaluation", "étude de cas", "case study")
            )
            if not is_quiz_or_case:
                uid = f"M{module.module_number:02d}-U{u.order_index + 1:02d}"
                next_lessons.append(uid)
            if len(next_lessons) >= count:
                break

        return next_lessons

    async def _is_cached(
        session: AsyncSession,
        module_uuid: uuid.UUID,
        unit_id: str,
        language: str,
        level: int,
        country: str,
    ) -> bool:
        """Return True if lesson content already exists in generated_content cache."""
        result = await session.execute(
            select(GeneratedContent.id).where(
                GeneratedContent.module_id == module_uuid,
                GeneratedContent.content_type == "lesson",
                GeneratedContent.language == language,
                GeneratedContent.content["unit_id"].astext == unit_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        prefetched: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        try:
            async with session_factory() as session:
                if module_id:
                    module_uuid = uuid.UUID(module_id)
                elif module_number is not None:
                    mod_result = await session.execute(
                        select(Module).where(Module.module_number == module_number)
                    )
                    mod = mod_result.scalar_one_or_none()
                    if not mod:
                        logger.warning(
                            "Module not found for prefetch",
                            module_number=module_number,
                            user_id=user_id,
                        )
                        return {
                            "status": "skipped",
                            "reason": "module_not_found",
                            "prefetched": [],
                            "skipped": [],
                            "errors": [],
                        }
                    module_uuid = mod.id
                else:
                    logger.warning(
                        "prefetch_next_lessons_task called with no module_id or module_number",
                        user_id=user_id,
                    )
                    return {
                        "status": "skipped",
                        "reason": "no_module",
                        "prefetched": [],
                        "skipped": [],
                        "errors": [],
                    }

                next_unit_ids = await _get_next_lesson_unit_ids(
                    session, module_uuid, current_unit_id
                )

                logger.info(
                    "Pre-fetching lessons",
                    user_id=user_id,
                    units=next_unit_ids,
                )

                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                lesson_service = LessonGenerationService(ClaudeService(), retriever)

                for unit_id_str in next_unit_ids:
                    try:
                        cached = await _is_cached(
                            session, module_uuid, unit_id_str, language, level, country
                        )
                        if cached:
                            skipped.append(unit_id_str)
                            logger.info(
                                "Skipping already cached lesson",
                                unit_id=unit_id_str,
                                user_id=user_id,
                            )
                            continue

                        await lesson_service.get_or_generate_lesson(
                            module_id=module_uuid,
                            unit_id=unit_id_str,
                            language=language,
                            country=country,
                            level=level,
                            session=session,
                        )
                        prefetched.append(unit_id_str)
                        logger.info(
                            "Lesson pre-fetched",
                            unit_id=unit_id_str,
                            user_id=user_id,
                        )
                    except Exception as exc:
                        errors.append(unit_id_str)
                        logger.error(
                            "Failed to pre-fetch lesson",
                            unit_id=unit_id_str,
                            user_id=user_id,
                            error=str(exc),
                        )
        finally:
            await engine.dispose()

        return {
            "status": "complete",
            "prefetched": prefetched,
            "skipped": skipped,
            "errors": errors,
        }

    try:
        result = asyncio.run(_run())
        logger.info(
            "Lesson prefetch completed",
            user_id=user_id,
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Lesson prefetch task failed",
            user_id=user_id,
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=600,
    time_limit=660,
    rate_limit="1/m",
)
def backfill_missing_image_data(self) -> dict:
    """Re-generate image data for ready images that have NULL binary data (expired Azure URLs).

    Finds all GeneratedImage rows with status='ready' and image_data=NULL,
    then re-downloads and stores binary WebP for each one via the image service.

    Returns:
        dict with counts of processed, succeeded, and failed images
    """
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.models.generated_image import GeneratedImage
    from app.domain.services.image_service import ImageGenerationService, _resize_to_webp
    from app.infrastructure.config.settings import settings

    logger.info("Starting backfill of missing image binary data", task_id=self.request.id)

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        processed = 0
        succeeded = 0
        failed = 0

        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(GeneratedImage).where(
                        GeneratedImage.status == "ready",
                        GeneratedImage.image_data.is_(None),
                    )
                )
                images = result.scalars().all()
                logger.info("Found images missing binary data", count=len(images))

                service = ImageGenerationService()
                for img in images:
                    processed += 1
                    try:
                        if not img.concept:
                            logger.warning(
                                "Skipping image with no concept — cannot re-generate",
                                image_id=str(img.id),
                            )
                            failed += 1
                            continue

                        prompt = img.prompt or (
                            f"Educational illustration of {img.concept} "
                            "for West African public health"
                        )
                        image_bytes, _ = await service._call_dalle(prompt)
                        webp_bytes, width = _resize_to_webp(image_bytes, max_width=512)

                        img.image_data = webp_bytes
                        img.image_url = f"/api/v1/images/{img.id}/data"
                        img.width = width
                        img.format = "webp"
                        img.file_size_bytes = len(webp_bytes)
                        await session.flush()
                        succeeded += 1
                        logger.info(
                            "Backfilled image binary data",
                            image_id=str(img.id),
                            size_bytes=len(webp_bytes),
                        )
                    except Exception as exc:
                        failed += 1
                        logger.error(
                            "Failed to backfill image",
                            image_id=str(img.id),
                            error=str(exc),
                        )

                await session.commit()

        finally:
            await engine.dispose()

        return {"processed": processed, "succeeded": succeeded, "failed": failed}

    try:
        result = asyncio.run(_run())
        logger.info(
            "Backfill completed",
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Backfill task failed",
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"processed": 0, "succeeded": 0, "failed": 0, "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=600,
    time_limit=650,
    rate_limit="2/m",
)
def generate_media_summary(
    self,
    module_id: str,
    language: str,
    media_type: str = "audio_summary",
) -> dict:
    """Generate an audio summary for a module via Claude script + Gemini TTS.

    Args:
        module_id: UUID of the module
        language: Language code (fr/en)
        media_type: Media type (default: "audio_summary")

    Returns:
        dict with media_id and status
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.media_summary_service import MediaSummaryService
    from app.infrastructure.config.settings import settings
    from app.infrastructure.storage.s3 import S3StorageService

    logger.info(
        "Starting audio summary generation",
        module_id=module_id,
        language=language,
        media_type=media_type,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = MediaSummaryService(
                    claude_service=ClaudeService(),
                    retriever=retriever,
                    storage=S3StorageService(),
                )
                media = await service.generate_audio_summary(
                    module_id=uuid.UUID(module_id),
                    language=language,
                    session=session,
                )
                return {"media_id": str(media.id), "status": media.status}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Audio summary generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Audio summary generation failed",
            module_id=module_id,
            language=language,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"media_id": None, "status": "failed", "error": str(exc)}
