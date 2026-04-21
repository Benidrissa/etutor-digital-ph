"""Module media endpoints (list, generate audio, delete)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.domain.models.module_media import ModuleMedia
from app.domain.models.user import UserRole
from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.storage.s3 import S3StorageService
from app.tasks.content_generation import generate_media_summary

logger = get_logger(__name__)
router = APIRouter(prefix="/modules", tags=["Module Media"])

# Map between frontend media_type ("audio") and backend ("audio_summary")
_FE_TO_BE_TYPE = {"audio": "audio_summary", "video": "video_summary"}
_BE_TO_FE_TYPE = {v: k for k, v in _FE_TO_BE_TYPE.items()}


class ModuleMediaResponse(BaseModel):
    id: str
    module_id: str
    media_type: str
    language: str
    status: str
    url: str | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    generated_at: str | None = None


class GenerateModuleMediaRequest(BaseModel):
    media_type: str  # "audio" or "video"
    language: str  # "fr" or "en"


def _to_response(media: ModuleMedia) -> ModuleMediaResponse:
    url: str | None = None
    if media.storage_key and media.status == "ready":
        try:
            storage = S3StorageService()
            url = storage.public_url(media.storage_key)
        except Exception as exc:
            logger.warning(
                "S3StorageService unavailable — returning url=None",
                media_id=str(media.id),
                error=str(exc),
            )
    return ModuleMediaResponse(
        id=str(media.id),
        module_id=str(media.module_id),
        media_type=_BE_TO_FE_TYPE.get(media.media_type, media.media_type),
        language=media.language,
        status=media.status,
        url=url,
        duration_seconds=media.duration_seconds,
        file_size_bytes=media.file_size_bytes,
        generated_at=media.generated_at.isoformat() if media.generated_at else None,
    )


@router.get("/{module_id}/media", response_model=list[ModuleMediaResponse])
async def list_module_media(
    module_id: uuid.UUID,
    _current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ModuleMediaResponse]:
    """List all media for a module."""
    try:
        result = await db.execute(select(ModuleMedia).where(ModuleMedia.module_id == module_id))
        items = result.scalars().all()
    except Exception as exc:
        logger.error(
            "Failed to query module_media table",
            module_id=str(module_id),
            error=str(exc),
        )
        return []

    responses: list[ModuleMediaResponse] = []
    for m in items:
        try:
            responses.append(_to_response(m))
        except Exception as exc:
            logger.warning(
                "Skipping media item due to serialisation error",
                media_id=str(m.id),
                error=str(exc),
            )
    return responses


@router.post(
    "/{module_id}/media/generate",
    response_model=ModuleMediaResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_module_media(
    module_id: uuid.UUID,
    request: GenerateModuleMediaRequest,
    _current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.expert)),
    db: AsyncSession = Depends(get_db_session),
) -> ModuleMediaResponse:
    """Trigger async audio/video generation for a module."""
    be_type = _FE_TO_BE_TYPE.get(request.media_type)
    if be_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported media_type: {request.media_type}",
        )

    if request.language not in ("fr", "en"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="language must be 'fr' or 'en'",
        )

    # Video summaries are admin-gated behind a platform-settings flag
    # so tenants can opt in after signing the HeyGen DPA. The flag is
    # editable from the admin Settings page without a redeploy.
    # See issue #1791.
    if be_type == "video_summary":
        _cache = SettingsCache.instance()
        if not _cache.get("video-summary-feature-enabled", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="video_summary feature is disabled",
            )
        avatar_id = (
            _cache.get("video-summary-default-avatar-id", "") or ""
        )
        voice_key = (
            "video-summary-voice-id-fr"
            if request.language == "fr"
            else "video-summary-voice-id-en"
        )
        voice_id = _cache.get(voice_key, "") or ""
        if not avatar_id.strip() or not voice_id.strip():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "video_summary is enabled but HeyGen avatar/voice "
                    "IDs are not configured"
                ),
            )

    # Check for existing ready or in-progress media
    existing = await db.execute(
        select(ModuleMedia).where(
            ModuleMedia.module_id == module_id,
            ModuleMedia.media_type == be_type,
            ModuleMedia.language == request.language,
            ModuleMedia.status.in_(["ready", "generating", "pending"]),
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return _to_response(found)

    # Create pending record
    media = ModuleMedia(
        id=uuid.uuid4(),
        module_id=module_id,
        media_type=be_type,
        language=request.language,
        status="pending",
    )
    db.add(media)
    await db.commit()
    await db.refresh(media)

    # Dispatch Celery task
    generate_media_summary.delay(str(module_id), request.language, be_type)

    logger.info(
        "Module media generation dispatched",
        module_id=str(module_id),
        media_type=be_type,
        language=request.language,
        media_id=str(media.id),
    )

    return _to_response(media)


@router.delete(
    "/{module_id}/media/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_module_media(
    module_id: uuid.UUID,
    media_id: uuid.UUID,
    _current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a module media record and its S3 object."""
    result = await db.execute(
        select(ModuleMedia).where(
            ModuleMedia.id == media_id,
            ModuleMedia.module_id == module_id,
        )
    )
    media = result.scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    # Delete S3 object if exists
    if media.storage_key:
        try:
            storage = S3StorageService()
            await storage.delete_object(media.storage_key)
        except Exception as exc:
            logger.warning("Failed to delete S3 object", key=media.storage_key, error=str(exc))

    await db.delete(media)
    await db.commit()
