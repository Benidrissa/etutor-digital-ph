"""Celery task for pre-assessment generation — generates 20 MCQ via Claude API + RAG."""

import asyncio

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


class PreAssessmentTask(Task):
    """Base task for pre-assessment generation with progress tracking."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Pre-assessment generation completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Pre-assessment generation failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=PreAssessmentTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
    time_limit=660,
    soft_time_limit=600,
    name="app.tasks.preassessment_generation.generate_course_preassessment",
)
def generate_course_preassessment(self, course_id: str, language: str = "fr") -> dict:
    """Generate a 20-question pre-assessment for a course via Claude API + RAG.

    Runs synchronously in a Celery worker. Uses asyncio.run() to call async
    service and DB operations.

    Args:
        course_id: UUID string of the course
        language: Content language ("fr" or "en")

    Returns:
        dict with status, preassessment_id, and question_count
    """
    logger.info(
        "Starting pre-assessment generation",
        task_id=self.request.id,
        course_id=course_id,
        language=language,
    )

    self.update_state(
        state="GENERATING",
        meta={"step": "initializing", "progress": 5, "question_count": 0},
    )

    async def _run_generation():
        import uuid

        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        from app.ai.claude_service import ClaudeService
        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.retriever import SemanticRetriever
        from app.domain.services.preassessment_generation_service import (
            PreAssessmentGenerationService,
        )
        from app.infrastructure.config.settings import settings

        engine = create_async_engine(settings.database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            self.update_state(
                state="GENERATING",
                meta={"step": "retrieving_rag_context", "progress": 20, "question_count": 0},
            )

            claude_service = ClaudeService()
            embedding_service = EmbeddingService()
            retriever = SemanticRetriever(embedding_service)
            service = PreAssessmentGenerationService(claude_service, retriever)

            async with async_session() as session:
                self.update_state(
                    state="GENERATING",
                    meta={"step": "calling_claude", "progress": 40, "question_count": 0},
                )

                preassessment = await service.generate_and_store(
                    course_id=uuid.UUID(course_id),
                    language=language,
                    session=session,
                    task_id=self.request.id,
                )

            return {
                "status": "complete",
                "preassessment_id": str(preassessment.id),
                "question_count": preassessment.question_count,
            }
        finally:
            await engine.dispose()

    try:
        self.update_state(
            state="GENERATING",
            meta={"step": "generating", "progress": 10, "question_count": 0},
        )

        result = asyncio.run(_run_generation())

        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "progress": 100,
                "question_count": result.get("question_count", 0),
                "preassessment_id": result.get("preassessment_id"),
            },
        )

        return result

    except Exception as exc:
        logger.error(
            "Pre-assessment generation failed",
            course_id=course_id,
            language=language,
            error=str(exc),
        )
        raise
