"""Celery application configuration for SantePublique AOF."""

import structlog
from celery import Celery

import app.domain.models  # noqa: F401 — register all SQLAlchemy models with the mapper
from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

# Initialize Celery app
celery_app = Celery(
    "santepublique_aof",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.content_generation",
        "app.tasks.data_etl",
    ],
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=False,
    task_eager_propagates=True,
    task_ignore_result=False,
    result_expires=3600,  # 1 hour
    worker_prefetch_multiplier=4,
    task_acks_late=True,
    worker_disable_rate_limits=False,
    task_default_rate_limit="10/m",  # 10 tasks per minute default
    # Retry configuration
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
)

# Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "refresh-dhis2-data": {
        "task": "app.tasks.data_etl.refresh_dhis2_data",
        "schedule": 3600 * 24,  # Daily
    },
    "refresh-who-data": {
        "task": "app.tasks.data_etl.refresh_who_data",
        "schedule": 3600 * 24 * 7,  # Weekly
    },
    "cleanup-expired-cache": {
        "task": "app.tasks.data_etl.cleanup_expired_cache",
        "schedule": 3600 * 6,  # Every 6 hours
    },
}


# Logging configuration for Celery
@celery_app.task(bind=True)
def debug_task(self):
    logger.info(f"Request: {self.request!r}")


if __name__ == "__main__":
    celery_app.start()
