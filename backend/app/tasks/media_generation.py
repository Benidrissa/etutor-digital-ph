"""Celery tasks for AI-generated module audio/video summaries (issue #539)."""

import uuid

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

MEDIA_SOFT_LIMIT = 480
MEDIA_HARD_LIMIT = 520


class MediaCallbackTask(Task):
    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Media generation task completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "Media generation task failed",
            task_id=task_id,
            exception=str(exc),
            traceback=einfo.traceback,
        )


@celery_app.task(
    bind=True,
    base=MediaCallbackTask,
    soft_time_limit=MEDIA_SOFT_LIMIT,
    time_limit=MEDIA_HARD_LIMIT,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 120},
    rate_limit="3/m",
)
def generate_module_audio_task(
    self,
    media_id: str,
    module_id: str,
    language: str,
) -> dict:
    """Generate audio summary for a module and store binary MP3 in DB.

    Args:
        media_id: UUID of the ModuleMedia record (status=pending)
        module_id: UUID of the module
        language: Language code (fr|en)

    Returns:
        dict with media_id and status
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.module_media_service import ModuleMediaService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting audio summary generation",
        media_id=media_id,
        module_id=module_id,
        language=language,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = ModuleMediaService()
                record = await service.generate_audio(
                    media_id=uuid.UUID(media_id),
                    module_id=uuid.UUID(module_id),
                    language=language,
                    session=session,
                )
                return {"media_id": str(record.id), "status": record.status}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Audio summary generation completed",
            media_id=media_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Audio summary generation failed",
            media_id=media_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"media_id": media_id, "status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=MediaCallbackTask,
    soft_time_limit=MEDIA_SOFT_LIMIT,
    time_limit=MEDIA_HARD_LIMIT,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 120},
    rate_limit="3/m",
)
def generate_module_video_task(
    self,
    media_id: str,
    module_id: str,
    language: str,
) -> dict:
    """Generate video summary script for a module and store in DB.

    Args:
        media_id: UUID of the ModuleMedia record (status=pending)
        module_id: UUID of the module
        language: Language code (fr|en)

    Returns:
        dict with media_id and status
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.module_media_service import ModuleMediaService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting video summary generation",
        media_id=media_id,
        module_id=module_id,
        language=language,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = ModuleMediaService()
                record = await service.generate_video(
                    media_id=uuid.UUID(media_id),
                    module_id=uuid.UUID(module_id),
                    language=language,
                    session=session,
                )
                return {"media_id": str(record.id), "status": record.status}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Video summary generation completed",
            media_id=media_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Video summary generation failed",
            media_id=media_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"media_id": media_id, "status": "failed", "error": str(exc)}
