"""Celery-beat poller for HeyGen video-summary completion.

Walks the ``generated_audio`` table (the polymorphic per-lesson
media cache) for rows with ``media_type='video'``,
``status='generating'``, and a ``provider_video_id``. Asks HeyGen
for the terminal status and either delegates to
``finalize_lesson_video`` (on ``completed``) or flips the row to
``failed`` (on HeyGen failure or the 2 h timeout guard).

Scope history: #1791 shipped webhook-only completion, #1796
switched to polling to avoid per-tenant ingress coupling, #1802
rescoped from per-module (``module_media``) to per-lesson
(``generated_audio``). The table rename is cosmetic-only work left
for a follow-up; for now the poller addresses the legacy table by
its current name.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.domain.models.generated_audio import GeneratedAudio
from app.domain.services.lesson_video_service import finalize_lesson_video
from app.infrastructure.config.settings import settings
from app.infrastructure.video.heygen_client import (
    HeyGenAuthError,
    HeyGenClient,
)
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

# Rows older than this are considered abandoned and marked failed
# rather than polled forever. HeyGen's own P95 is ~30 min; 2h is a
# forgiving cap that still prevents dangling rows if HeyGen drops
# the job silently.
_GENERATING_TIMEOUT = timedelta(hours=2)


@celery_app.task(
    name="app.tasks.heygen_poll.poll_pending_heygen_videos",
    bind=True,
    soft_time_limit=120,
    time_limit=150,
)
def poll_pending_heygen_videos(self) -> dict:
    """Reconcile every ``generating`` video row with HeyGen state.

    Returns a summary dict so the Celery result backend surfaces how
    many rows moved each way. Individual row errors are swallowed
    (logged) so one bad row never blocks the batch.
    """

    async def _run() -> dict:
        engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=2,
            max_overflow=1,
        )
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        summary = {
            "checked": 0,
            "ready": 0,
            "failed": 0,
            "still_pending": 0,
            "timed_out": 0,
            "errors": 0,
        }
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(GeneratedAudio).where(
                        GeneratedAudio.media_type == "video",
                        GeneratedAudio.status == "generating",
                        GeneratedAudio.provider_video_id.is_not(None),
                    )
                )
                rows: list[GeneratedAudio] = list(result.scalars().all())

                if not rows:
                    return summary

                async with HeyGenClient() as client:
                    for record in rows:
                        summary["checked"] += 1
                        try:
                            outcome = await _reconcile_one(
                                record=record,
                                client=client,
                                session=session,
                            )
                            summary[outcome] += 1
                        except HeyGenAuthError as exc:
                            # Global config issue — no point hitting
                            # HeyGen again this tick. Log and bail.
                            logger.error(
                                "heygen.poll.auth_error",
                                error=str(exc),
                            )
                            summary["errors"] += 1
                            break
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "heygen.poll.row_error",
                                media_id=str(record.id),
                                provider_video_id=(record.provider_video_id),
                                error=str(exc),
                            )
                            summary["errors"] += 1
        finally:
            await engine.dispose()
        return summary

    result = asyncio.run(_run())
    if result["checked"]:
        logger.info("heygen.poll.tick", **result)
    return result


async def _reconcile_one(
    *,
    record: GeneratedAudio,
    client: HeyGenClient,
    session: AsyncSession,
) -> str:
    """Reconcile one ``generating`` row against HeyGen's view.

    Returns one of ``"ready" | "failed" | "still_pending" |
    "timed_out"`` so the parent task can update its summary counter.
    """
    if _is_timed_out(record):
        record.status = "failed"
        record.error_message = "heygen generation timed out; still generating after 2h"
        await session.commit()
        logger.warning(
            "heygen.poll.timed_out",
            media_id=str(record.id),
            provider_video_id=record.provider_video_id,
        )
        return "timed_out"

    api_version = _api_version_for(record)
    status = await client.get_video(
        str(record.provider_video_id),
        api_version=api_version,
    )
    if status.status == "completed":
        if not status.video_url:
            record.status = "failed"
            record.error_message = "heygen reported completed without a video_url"
            await session.commit()
            return "failed"
        terminal = await finalize_lesson_video(
            record,
            video_url=status.video_url,
            session=session,
        )
        return "ready" if terminal == "ready" else "failed"

    if status.status == "failed":
        record.status = "failed"
        record.error_message = status.error or "heygen reported failure"
        await session.commit()
        return "failed"

    return "still_pending"


def _is_timed_out(record: GeneratedAudio) -> bool:
    """Return True when ``record.created_at`` is older than the cap."""
    created = record.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created > _GENERATING_TIMEOUT


def _api_version_for(record: GeneratedAudio) -> str:
    """Read the HeyGen API version used when the row was created.

    Written to ``media_metadata.api_version`` by the service at
    dispatch time.

    Poll every row via the v3 status endpoint (``/v3/videos/{id}``).
    HeyGen's ``/v2/video_status.get`` returns 404 as of April 2026
    (#1874) — the endpoint appears to be deprecated. The v3
    endpoint accepts any video_id HeyGen has issued, regardless of
    which create path produced it, since the video_id namespace is
    shared. Returning ``"v3-agent"`` dispatches the v3 GET in
    ``HeyGenClient.get_video`` for all rows.
    """
    # All create paths (v2 Direct Video, v3 Video Agents, v3 content
    # /v3/videos) produce video_ids that resolve on /v3/videos/{id}.
    return "v3-agent"
