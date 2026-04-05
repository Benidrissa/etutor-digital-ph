"""Celery tasks for subscription lifecycle management."""

import asyncio

import structlog

from app.domain.services.subscription_service import SubscriptionService
from app.infrastructure.persistence.database import async_session_factory
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.subscription.expire_subscriptions",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def expire_subscriptions(self) -> dict:
    """Bulk-expire subscriptions whose expires_at has passed."""
    try:

        async def _run() -> int:
            async with async_session_factory() as session:
                service = SubscriptionService()
                return await service.expire_subscriptions(session)

        expired_count = asyncio.run(_run())
        logger.info("expire_subscriptions task completed", expired=expired_count)
        return {"expired": expired_count}
    except Exception as exc:
        logger.error("expire_subscriptions task failed", error=str(exc))
        raise self.retry(exc=exc) from exc
