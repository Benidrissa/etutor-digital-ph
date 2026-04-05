"""Celery tasks for subscription management — expiry checks."""

import asyncio

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.subscription.expire_subscriptions",
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def expire_subscriptions(self) -> dict:
    """Bulk-expire subscriptions whose expires_at has passed.

    Runs synchronously in Celery worker. Uses asyncio.run() to call
    async service from sync Celery context.
    """
    logger.info("Starting subscription expiry task", task_id=self.request.id)

    async def _run() -> int:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        from app.domain.services.subscription_service import SubscriptionService
        from app.infrastructure.config.settings import settings

        engine = create_async_engine(settings.database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            service = SubscriptionService(session)
            expired = await service.expire_subscriptions()

        await engine.dispose()
        return expired

    try:
        expired_count = asyncio.run(_run())
        logger.info("Subscription expiry task completed", expired=expired_count)
        return {"status": "ok", "expired": expired_count}
    except Exception as exc:
        logger.error("Subscription expiry task failed", error=str(exc))
        raise self.retry(exc=exc) from exc
