"""Celery tasks for SMS relay monitoring."""

import asyncio

import structlog

from app.domain.services.email_service import EmailService
from app.domain.services.sms_relay_service import SmsRelayService
from app.infrastructure.cache.redis import redis_client
from app.infrastructure.config.settings import settings
from app.infrastructure.persistence.database import (
    async_session_factory,
)
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

ALERT_COOLDOWN_KEY = "relay_alert_sent:{device_id}"
ALERT_COOLDOWN_TTL = 3600  # 1 hour


@celery_app.task(
    name="app.tasks.sms_relay.check_relay_heartbeat",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def check_relay_heartbeat(self) -> dict:
    """Check for stale relay devices and alert admin."""
    try:

        async def _run() -> int:
            async with async_session_factory() as session:
                service = SmsRelayService()
                stale = await service.get_stale_devices(
                    timeout_minutes=(
                        settings.sms_relay_heartbeat_timeout_minutes
                    ),
                    session=session,
                )

                if not stale or not settings.sms_relay_alert_email:
                    return 0

                email_service = EmailService()
                alerted = 0
                for device in stale:
                    key = ALERT_COOLDOWN_KEY.format(
                        device_id=device.device_id
                    )
                    if redis_client.get(key):
                        continue

                    sent = await email_service.send_relay_alert(
                        to_email=settings.sms_relay_alert_email,
                        device_id=device.device_id,
                        last_seen=device.last_heartbeat_at.isoformat(),
                        battery=device.battery,
                    )
                    if sent:
                        redis_client.set(
                            key, "1", ex=ALERT_COOLDOWN_TTL
                        )
                        alerted += 1

                return alerted

        count = asyncio.run(_run())
        logger.info(
            "check_relay_heartbeat completed",
            stale_alerted=count,
        )
        return {"stale_alerted": count}
    except Exception as exc:
        logger.error(
            "check_relay_heartbeat failed",
            error=str(exc),
        )
        raise self.retry(exc=exc) from exc
