"""Celery tasks for QBank audio generation (FR/Moore/Dioula)."""

from __future__ import annotations

import uuid

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

SOFT_LIMIT = 300
HARD_LIMIT = 360


class QBankCallbackTask(Task):
    def on_success(self, retval, task_id, args, kwargs):
        logger.info("QBank task completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "QBank task failed",
            task_id=task_id,
            exception=str(exc),
            traceback=einfo.traceback,
        )


@celery_app.task(
    bind=True,
    base=QBankCallbackTask,
    soft_time_limit=120,
    time_limit=150,
    rate_limit="10/m",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 30},
)
def generate_question_audio_task(
    self,
    question_id: str,
    language: str,
    question_text: str,
    choices: list[dict] | None = None,
) -> dict:
    """Generate TTS audio for a single qbank question.

    Args:
        question_id: UUID string of the question.
        language: "fr" (Gemini TTS), "mos" or "dyu" (Meta MMS).
        question_text: The question stem text.
        choices: Optional list of {"text": "..."} option dicts.

    Returns:
        dict with audio_id and status.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.qbank_audio_service import QBankAudioService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting question audio generation",
        question_id=question_id,
        language=language,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = QBankAudioService()
                audio = await service.generate_question_audio(
                    question_id=uuid.UUID(question_id),
                    language=language,
                    question_text=question_text,
                    choices=choices,
                    session=session,
                )
                return {"audio_id": str(audio.id), "status": audio.status}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Question audio generation completed",
            question_id=question_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Question audio generation failed",
            question_id=question_id,
            language=language,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"audio_id": None, "status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=QBankCallbackTask,
    soft_time_limit=SOFT_LIMIT,
    time_limit=HARD_LIMIT,
    rate_limit="2/m",
)
def generate_qbank_audio_task(
    self,
    bank_id: str,
    language: str,
    questions: list[dict],
) -> dict:
    """Batch TTS generation for all questions in a question bank.

    Args:
        bank_id: UUID string of the question bank.
        language: Target language ("fr", "mos", "dyu").
        questions: List of {"id": str, "text": str, "choices": [...]} dicts.

    Returns:
        dict with generated/skipped/failed lists.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.qbank_audio_service import QBankAudioService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting batch qbank audio generation",
        bank_id=bank_id,
        language=language,
        question_count=len(questions),
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = QBankAudioService()
                return await service.batch_generate_audio(
                    bank_id=uuid.UUID(bank_id),
                    language=language,
                    questions=questions,
                    session=session,
                )
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Batch qbank audio generation completed",
            bank_id=bank_id,
            language=language,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Batch qbank audio generation failed",
            bank_id=bank_id,
            language=language,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"generated": [], "skipped": [], "failed": [], "error": str(exc)}
