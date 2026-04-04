"""API endpoints for module audio/video summaries (issue #539).

Routes:
  GET  /modules/{module_id}/media           — list all media for a module
  POST /modules/{module_id}/media/generate  — trigger async generation
  GET  /modules/{module_id}/media/{media_id}/status — poll status
  GET  /modules/{module_id}/media/{media_id}/data   — serve binary media
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.v1.schemas.module_media import (
    GenerateMediaRequest,
    GenerateMediaResponse,
    MediaStatusResponse,
    ModuleMediaListResponse,
    ModuleMediaResponse,
)
from app.domain.models.module import Module
from app.domain.models.module_media import ModuleMedia
from app.domain.services.module_media_service import ModuleMediaService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/modules", tags=["module-media"])


def _media_response(record: ModuleMedia) -> ModuleMediaResponse:
    return ModuleMediaResponse(
        id=record.id,
        module_id=record.module_id,
        media_type=record.media_type,
        language=record.language,
        status=record.status,
        url=record.url if record.status == "ready" else None,
        duration_seconds=record.duration_seconds,
        file_size_bytes=record.file_size_bytes,
        mime_type=record.mime_type,
        generated_at=record.generated_at,
        created_at=record.created_at,
    )


@router.get(
    "/{module_id}/media",
    response_model=ModuleMediaListResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Module not found"}},
)
async def list_module_media(
    module_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ModuleMediaListResponse:
    """Return all media records for a module (audio and video, all languages)."""
    module_result = await db.execute(select(Module).where(Module.id == module_id))
    if module_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "module_not_found", "message": f"Module {module_id} not found"},
        )

    media_result = await db.execute(
        select(ModuleMedia).where(ModuleMedia.module_id == module_id)
    )
    records = media_result.scalars().all()

    return ModuleMediaListResponse(
        module_id=module_id,
        media=[_media_response(r) for r in records],
        total=len(records),
    )


@router.post(
    "/{module_id}/media/generate",
    response_model=GenerateMediaResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "Module not found"},
        409: {"description": "Media already generating"},
    },
)
async def generate_module_media(
    module_id: UUID,
    request: GenerateMediaRequest,
    db: AsyncSession = Depends(get_db_session),
) -> GenerateMediaResponse:
    """Trigger async generation of audio or video summary for a module.

    - Returns 202 Accepted with a `task_id` for polling.
    - If media already exists and `force_regenerate=false`, returns the existing record.
    - If media is currently `generating`, returns 409 to prevent double-triggering.
    """
    module_result = await db.execute(select(Module).where(Module.id == module_id))
    if module_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "module_not_found", "message": f"Module {module_id} not found"},
        )

    existing_result = await db.execute(
        select(ModuleMedia).where(
            ModuleMedia.module_id == module_id,
            ModuleMedia.media_type == request.media_type,
            ModuleMedia.language == request.language,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing and existing.status == "generating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "media_generating",
                "message": "Media is already being generated. Poll /status to check progress.",
                "media_id": str(existing.id),
            },
        )

    if existing and existing.status == "ready" and not request.force_regenerate:
        return GenerateMediaResponse(
            media_id=existing.id,
            task_id=None,
            status="ready",
            message="Media already available",
        )

    service = ModuleMediaService()
    record = await service.get_or_generate(
        module_id=module_id,
        media_type=request.media_type,
        language=request.language,
        session=db,
        force_regenerate=request.force_regenerate,
    )

    task_id: str | None = None
    if request.media_type == "audio_summary":
        from app.tasks.media_generation import generate_module_audio_task
        task = generate_module_audio_task.delay(
            str(record.id), str(module_id), request.language
        )
        task_id = task.id
    else:
        from app.tasks.media_generation import generate_module_video_task
        task = generate_module_video_task.delay(
            str(record.id), str(module_id), request.language
        )
        task_id = task.id

    media_label = "Audio" if request.media_type == "audio_summary" else "Video"
    lang_label = "FR" if request.language == "fr" else "EN"
    message = f"{media_label} summary generation started ({lang_label})"

    logger.info(
        "Module media generation triggered",
        module_id=str(module_id),
        media_type=request.media_type,
        language=request.language,
        media_id=str(record.id),
        task_id=task_id,
    )

    return GenerateMediaResponse(
        media_id=record.id,
        task_id=task_id,
        status="pending",
        message=message,
    )


@router.get(
    "/{module_id}/media/{media_id}/status",
    response_model=MediaStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Media not found"}},
)
async def get_media_status(
    module_id: UUID,
    media_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> MediaStatusResponse:
    """Poll media generation status."""
    result = await db.execute(
        select(ModuleMedia).where(
            ModuleMedia.id == media_id,
            ModuleMedia.module_id == module_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "media_not_found", "message": f"Media {media_id} not found"},
        )

    return MediaStatusResponse(
        media_id=record.id,
        status=record.status,
        url=record.url if record.status == "ready" else None,
    )


@router.get(
    "/{module_id}/media/{media_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Binary media data"},
        404: {"description": "Media not found or not ready"},
    },
)
async def get_media_data(
    module_id: UUID,
    media_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Serve binary media (MP3 audio or JSON video script).

    - Returns binary audio (`audio/mpeg` or `audio/wav`) when audio data is stored.
    - Returns JSON video script (`application/json`) for video summaries.
    - Returns text/plain for development fallback.
    - Returns 404 when media is not found or not ready.
    """
    result = await db.execute(
        select(ModuleMedia).where(
            ModuleMedia.id == media_id,
            ModuleMedia.module_id == module_id,
        )
    )
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "media_not_found", "message": f"Media {media_id} not found"},
        )

    if record.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "media_not_ready",
                "message": f"Media {media_id} is not ready (status: {record.status})",
            },
        )

    if not record.media_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "media_data_unavailable", "message": "No binary data stored"},
        )

    mime_type = record.mime_type or "application/octet-stream"
    cache_headers = {"Cache-Control": "public, max-age=86400"}

    if mime_type.startswith("audio/"):
        content_disposition = f'attachment; filename="module-summary-{record.language}.mp3"'
        cache_headers["Content-Disposition"] = content_disposition

    logger.info("Serving media data", media_id=str(media_id), mime_type=mime_type)
    return Response(
        content=record.media_data,
        media_type=mime_type,
        headers=cache_headers,
    )
