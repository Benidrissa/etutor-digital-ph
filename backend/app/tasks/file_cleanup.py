"""Celery task for cleaning up expired tutor file uploads."""

import structlog

from app.domain.services.file_processor import FileProcessor
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="app.tasks.file_cleanup.cleanup_expired_uploads", bind=True, max_retries=3)
def cleanup_expired_uploads(self) -> dict[str, int]:
    """Delete temp upload files older than the configured TTL (default 24h)."""
    try:
        processor = FileProcessor()
        deleted = processor.cleanup_expired_files()
        logger.info("File cleanup task completed", deleted=deleted)
        return {"deleted": deleted}
    except Exception as exc:
        logger.error("File cleanup task failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300) from exc
