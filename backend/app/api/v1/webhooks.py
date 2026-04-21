"""External-provider webhook receivers.

HeyGen pushes completion events to ``POST /api/v1/webhooks/heygen``
after each ``create_video`` call. Per HeyGen's docs, the HMAC-SHA256
of the raw body is sent in the ``Signature`` header and the success
event (``avatar_video.success``) carries ``event_data.video_id`` and
``event_data.url`` (note: field is ``url``, not ``video_url``). We
verify the signature against ``HEYGEN_WEBHOOK_SECRET`` and then
download the rendered MP4 into MinIO so the existing
``GET /modules/{id}/media`` endpoint can serve it. See issue #1791.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db as get_db_session
from app.domain.models.module_media import ModuleMedia
from app.infrastructure.storage.s3 import S3StorageService
from app.infrastructure.video.heygen_client import HeyGenClient

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _is_web_ready_mp4(data: bytes) -> bool:
    """Sniff the ISO-BMFF ``ftyp`` box to confirm a browser-playable MP4.

    HeyGen v2 consistently returns H.264/AAC MP4, which every
    modern browser plays natively. We still check the first 12 bytes
    of the file so a vendor change or a malformed download surfaces
    as a clear failure instead of silently landing an unplayable
    object in MinIO. Extension point: if a non-MP4 container ever
    appears here, a follow-up issue will plug in an ffmpeg re-mux
    (``-c copy -movflags +faststart``) to normalise back to MP4.
    """
    if len(data) < 12:
        return False
    # ISO-BMFF: bytes 4..7 carry the "ftyp" type box marker.
    return data[4:8] == b"ftyp"


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

    Idempotent: re-delivery for the same ``video_id`` is a no-op once
    the row has reached ``ready`` or ``failed``. Signature mismatch →
    403 (no row update). Unknown ``video_id`` → 200 with a log so
    HeyGen stops retrying; the scheduled reaper (future follow-up)
    reconciles truly-orphaned rows.
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

    # Success path — resolve the rendered MP4 URL, download, upload
    # to MinIO. HeyGen success events use the ``url`` key; we also
    # accept ``video_url`` defensively in case the field is renamed
    # or the payload was produced by a future event shape.
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

    try:
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            resp = await http_client.get(video_url)
            resp.raise_for_status()
            video_bytes = resp.content
    except Exception as exc:
        record.status = "failed"
        record.error_message = f"download failed: {exc}"
        await db.commit()
        logger.error(
            "heygen.webhook.download_failed",
            video_id=video_id,
            media_id=str(record.id),
            error=str(exc),
        )
        return {
            "status": "failed",
            "media_id": str(record.id),
            "reason": "download failed",
        }

    if not _is_web_ready_mp4(video_bytes):
        # Defensive guard: HeyGen v2 always returns H.264/AAC MP4
        # today, but a container change would land an unplayable
        # object in MinIO. Fail loudly so follow-up can add ffmpeg
        # normalisation if this ever trips.
        record.status = "failed"
        record.error_message = "downloaded bytes are not a recognisable MP4 container"
        await db.commit()
        logger.error(
            "heygen.webhook.unsupported_container",
            video_id=video_id,
            media_id=str(record.id),
            first_bytes=video_bytes[:16].hex(),
        )
        return {
            "status": "failed",
            "media_id": str(record.id),
            "reason": "unsupported container",
        }

    storage_key = f"video/{record.module_id}/{record.language}/summary.mp4"
    try:
        storage = S3StorageService()
        storage_url = await storage.upload_bytes(
            key=storage_key,
            data=video_bytes,
            content_type="video/mp4",
        )
    except Exception as exc:
        record.status = "failed"
        record.error_message = f"upload failed: {exc}"
        await db.commit()
        logger.error(
            "heygen.webhook.upload_failed",
            video_id=video_id,
            media_id=str(record.id),
            error=str(exc),
        )
        return {
            "status": "failed",
            "media_id": str(record.id),
            "reason": "upload failed",
        }

    record.status = "ready"
    record.storage_key = storage_key
    record.storage_url = storage_url
    record.file_size_bytes = len(video_bytes)
    duration_hint = data.get("duration") or data.get("video_duration")
    if isinstance(duration_hint, (int, float)):
        record.duration_seconds = int(duration_hint)
    record.generated_at = datetime.utcnow()
    await db.commit()

    logger.info(
        "heygen.webhook.ready",
        video_id=video_id,
        media_id=str(record.id),
        bytes=len(video_bytes),
    )
    return {"status": "ready", "media_id": str(record.id)}
