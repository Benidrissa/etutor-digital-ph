"""API endpoints for module media (audio generation)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.domain.models.module import Module
from app.domain.models.module_media import ModuleMedia
from app.domain.models.user import UserRole
from app.infrastructure.storage.s3 import S3StorageService
from app.tasks.content_generation import generate_media_summary

logger = get_logger(__name__)
router = APIRouter(prefix="/modules", tags=["Module Media"])

FRONTEND_TO_BACKEND_MEDIA_TYPE: dict[str, str] = {
    "audio": "audio_summary",
}
BACKEND_TO_FRONTEND_MEDIA_TYPE: dict[str, str] = {
    "audio_summary": "audio",
}


class ModuleMediaResponse(BaseModel):
    id: str
    module_id: str
    media_type: str
    language: str
    status: str
    url: str | None
    duration_seconds: int | None


class GenerateMediaRequest(BaseModel):
    media_type: str
    language: str


def _media_to_response(
    media: ModuleMedia, storage: S3StorageService | None = None
) -> ModuleMediaResponse:
    url: str | None = None
    if media.status == "ready" and media.storage_key:
        if storage is not None:
            url = storage.public_url(media.storage_key)
        elif media.storage_url:
            url = media.storage_url

    frontend_media_type = BACKEND_TO_FRONTEND_MEDIA_TYPE.get(media.media_type, media.media_type)

    return ModuleMediaResponse(
        id=str(media.id),
        module_id=str(media.module_id),
        media_type=frontend_media_type,
        language=media.language,
        status=media.status,
        url=url,
        duration_seconds=media.duration_seconds,
    )


@router.get("/{module_id}/media", response_model=list[ModuleMediaResponse])
async def list_module_media(
    module_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[ModuleMediaResponse]:
    """List all media for a module. Any authenticated user."""
    module_result = await db.execute(select(Module).where(Module.id == module_id))
    if module_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

    result = await db.execute(
        select(ModuleMedia)
        .where(ModuleMedia.module_id == module_id)
        .order_by(ModuleMedia.created_at.desc())
    )
    media_list = result.scalars().all()
    storage = S3StorageService()
    return [_media_to_response(m, storage) for m in media_list]


@router.post(
    "/{module_id}/media/generate",
    response_model=ModuleMediaResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_media(
    module_id: uuid.UUID,
    request: GenerateMediaRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.expert)),
    db=Depends(get_db_session),
) -> ModuleMediaResponse:
    """Trigger audio generation for a module. Admin or expert only."""
    module_result = await db.execute(select(Module).where(Module.id == module_id))
    if module_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

    backend_media_type = FRONTEND_TO_BACKEND_MEDIA_TYPE.get(request.media_type, request.media_type)

    existing_result = await db.execute(
        select(ModuleMedia).where(
            ModuleMedia.module_id == module_id,
            ModuleMedia.language == request.language,
            ModuleMedia.media_type == backend_media_type,
            ModuleMedia.status.in_(["ready", "generating", "pending"]),
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        logger.info(
            "Returning existing media",
            module_id=str(module_id),
            media_id=str(existing.id),
            status=existing.status,
        )
        storage = S3StorageService()
        return _media_to_response(existing, storage)

    record = ModuleMedia(
        id=uuid.uuid4(),
        module_id=module_id,
        media_type=backend_media_type,
        language=request.language,
        status="pending",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    task = generate_media_summary.delay(str(module_id), request.language, backend_media_type)

    logger.info(
        "Media generation triggered",
        module_id=str(module_id),
        media_id=str(record.id),
        task_id=task.id,
        language=request.language,
        media_type=backend_media_type,
        admin_id=current_user.id,
    )

    return ModuleMediaResponse(
        id=str(record.id),
        module_id=str(record.module_id),
        media_type=BACKEND_TO_FRONTEND_MEDIA_TYPE.get(record.media_type, record.media_type),
        language=record.language,
        status=record.status,
        url=None,
        duration_seconds=None,
    )


@router.delete("/{module_id}/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    module_id: uuid.UUID,
    media_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> None:
    """Delete a media record and its S3 object. Admin only."""
    result = await db.execute(
        select(ModuleMedia).where(
            ModuleMedia.id == media_id,
            ModuleMedia.module_id == module_id,
        )
    )
    media = result.scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    if media.storage_key:
        try:
            storage = S3StorageService()
            await storage.delete_object(media.storage_key)
        except Exception as exc:
            logger.warning(
                "Failed to delete S3 object, proceeding with DB deletion",
                storage_key=media.storage_key,
                error=str(exc),
            )

    await db.delete(media)
    await db.commit()
    logger.info(
        "Media deleted",
        module_id=str(module_id),
        media_id=str(media_id),
        admin_id=current_user.id,
    )
