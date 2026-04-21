"""External-provider webhook receivers.

Per issue #1796 the primary completion path for HeyGen video
summaries is the Celery-beat poller in ``app/tasks/heygen_poll.py``:
it works across multi-tenant deployments without ingress config and
requires only ``HEYGEN_API_KEY``. This endpoint stays as an opt-in
low-latency fallback for single-tenant deployments where the
operator has populated ``HEYGEN_WEBHOOK_SECRET`` and registered the
URL with HeyGen — signature check still enforced, and the post-
verification work is delegated to the shared
``finalize_video_summary`` helper so webhook and poller stay in
lock-step.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db as get_db_session
from app.domain.models.module_media import ModuleMedia
from app.domain.services.media_summary_service import finalize_video_summary
from app.infrastructure.video.heygen_client import HeyGenClient

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "/heygen",
    status_code=status.HTTP_200_OK,
)
async def heygen_webhook(
    request: Request,
    signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Handle ``avatar_video.success`` / ``avatar_video.failed`` events.

    Idempotent: a row already in ``ready``/``failed`` is a 200 no-op.
    Signature mismatch → 403. Unknown ``video_id`` → 200 ignored so
    HeyGen stops retrying; the poller reconciles any orphaned row.
    Actual MP4 download + upload is delegated to
    :func:`finalize_video_summary` so the webhook and poller produce
    identical outcomes.
    """
    raw_body = await request.body()
    client = HeyGenClient()
    if not client.verify_webhook_signature(
        signature=signature or "",
        raw_body=raw_body,
    ):
        logger.warning(
            "heygen.webhook.bad_signature",
            signature_prefix=(signature or "")[:12],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="bad signature",
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid json body",
        )

    event_type = payload.get("event_type") or payload.get("event")
    data = payload.get("event_data") or payload.get("data") or {}
    video_id = data.get("video_id") or payload.get("video_id")
    if not video_id:
        logger.warning("heygen.webhook.missing_video_id", payload=payload)
        return {"status": "ignored", "reason": "missing video_id"}

    result = await db.execute(
        select(ModuleMedia).where(ModuleMedia.provider_video_id == str(video_id))
    )
    record = result.scalar_one_or_none()
    if record is None:
        logger.info(
            "heygen.webhook.unknown_video_id",
            video_id=video_id,
            event_type=event_type,
        )
        return {"status": "ignored", "reason": "unknown video_id"}

    if record.status in ("ready", "failed"):
        logger.info(
            "heygen.webhook.duplicate",
            video_id=video_id,
            media_id=str(record.id),
            current_status=record.status,
        )
        return {"status": "duplicate", "media_id": str(record.id)}

    if event_type and "fail" in event_type.lower():
        record.status = "failed"
        record.error_message = data.get("error") or data.get("message") or "heygen reported failure"
        await db.commit()
        logger.warning(
            "heygen.webhook.failed",
            video_id=video_id,
            media_id=str(record.id),
            error=record.error_message,
        )
        return {"status": "failed", "media_id": str(record.id)}

    # Success path — HeyGen delivers the MP4 URL as ``event_data.url``
    # (per the official docs). We also accept ``video_url`` defensively
    # in case a future payload shape renames the field.
    video_url = (
        data.get("url") or data.get("video_url") or payload.get("url") or payload.get("video_url")
    )
    if not video_url:
        try:
            async with HeyGenClient() as hc:
                remote = await hc.get_video(str(video_id))
            video_url = remote.video_url
        except Exception as exc:
            record.status = "failed"
            record.error_message = f"status lookup failed: {exc}"
            await db.commit()
            logger.error(
                "heygen.webhook.status_lookup_failed",
                video_id=video_id,
                error=str(exc),
            )
            return {
                "status": "failed",
                "media_id": str(record.id),
                "reason": "status lookup failed",
            }

    if not video_url:
        record.status = "failed"
        record.error_message = "heygen success event missing video_url"
        await db.commit()
        logger.error(
            "heygen.webhook.missing_video_url",
            video_id=video_id,
        )
        return {"status": "failed", "media_id": str(record.id)}

    duration_hint = data.get("duration") or data.get("video_duration")
    terminal = await finalize_video_summary(
        record,
        video_url=video_url,
        session=db,
        duration_hint=(duration_hint if isinstance(duration_hint, (int, float)) else None),
    )
    return {"status": terminal, "media_id": str(record.id)}
