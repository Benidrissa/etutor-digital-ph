"""API endpoints for AI tutor functionality."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.tutor import (
    FileUploadResponse,
    TutorChatRequest,
    TutorConversationListResponse,
    TutorConversationResponse,
    TutorStatsResponse,
)
from app.domain.services.file_processor import FileProcessor
from app.domain.services.tutor_service import TutorService
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

router = APIRouter(prefix="/tutor", tags=["tutor"])

_file_upload_counts: dict[str, list[datetime]] = {}


async def get_tutor_service() -> TutorService:
    """Get tutor service with dependencies."""
    settings = get_settings()
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=600.0)
    embedding_service = EmbeddingService(api_key=settings.openai_api_key)
    semantic_retriever = SemanticRetriever(embedding_service)

    return TutorService(
        anthropic_client=anthropic_client,
        semantic_retriever=semantic_retriever,
        embedding_service=embedding_service,
    )


def _check_upload_rate_limit(user_id: str, daily_limit: int) -> None:
    """Check and enforce per-user daily upload rate limit (in-memory, resets at UTC midnight)."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    timestamps = _file_upload_counts.get(user_id, [])
    timestamps = [ts for ts in timestamps if ts >= today_start]
    _file_upload_counts[user_id] = timestamps

    if len(timestamps) >= daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily file upload limit reached. Try again tomorrow.",
        )

    _file_upload_counts[user_id] = timestamps + [datetime.utcnow()]


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> FileUploadResponse:
    """Upload a file for use in tutor chat (images, PDFs, documents).

    Returns a file_id to include in subsequent chat requests.
    Files are stored temporarily with a 24h TTL.
    """
    settings = get_settings()
    _check_upload_rate_limit(str(current_user.id), settings.upload_daily_limit)

    data = await file.read()
    filename = file.filename or "upload"
    mime_type = file.content_type or "application/octet-stream"

    processor = FileProcessor()

    try:
        processed = await processor.process(
            filename=filename,
            mime_type=mime_type,
            data=data,
            user_id=current_user.id,
        )
    except ValueError as exc:
        logger.warning(
            "File upload rejected",
            reason=str(exc),
            filename=filename,
            mime_type=mime_type,
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "File uploaded",
        file_id=processed.file_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=processed.size_bytes,
        user_id=str(current_user.id),
    )

    return FileUploadResponse(
        file_id=processed.file_id,
        original_name=processed.original_name,
        mime_type=processed.mime_type,
        size_bytes=processed.size_bytes,
        expires_at=processed.expires_at,
    )


@router.post("/chat", response_model=None)
async def chat_with_tutor(
    request: TutorChatRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    tutor_service: TutorService = Depends(get_tutor_service),
) -> StreamingResponse:
    """
    Chat with the AI tutor using Socratic pedagogical approach.

    Streams response using Server-Sent Events (SSE).
    Optionally attach file_ids from previously uploaded files.
    """
    logger.info(
        "Tutor chat request",
        user_id=str(current_user.id),
        message_length=len(request.message),
        module_id=str(request.module_id) if request.module_id else None,
        context_type=request.context_type,
        file_count=len(request.file_ids),
    )

    file_content_blocks = _load_file_content_blocks(request.file_ids, str(current_user.id))

    async def stream_tutor_response():
        """Stream the tutor response."""
        try:
            async for chunk in tutor_service.send_message(
                user_id=current_user.id,
                message=request.message,
                session=session,
                module_id=request.module_id,
                context_type=request.context_type,
                context_id=request.context_id,
                conversation_id=request.conversation_id,
                tutor_mode=request.tutor_mode,
                file_content_blocks=file_content_blocks,
                course_id=request.course_id,
            ):
                yield f"data: {json.dumps(chunk)}\n\n"

        except Exception as e:
            logger.error(
                "Error streaming tutor response", error=str(e), user_id=str(current_user.id)
            )
            error_chunk = {
                "type": "error",
                "data": {"code": "tutor_error", "message": "An error occurred. Please try again."},
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"

    return StreamingResponse(
        stream_tutor_response(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _load_file_content_blocks(file_ids: list[str], user_id: str) -> list[dict[str, Any]]:
    """Load content blocks for the given file_ids from temp storage."""
    if not file_ids:
        return []

    settings = get_settings()
    temp_dir = Path(settings.upload_temp_dir)
    processor = FileProcessor()
    blocks: list[dict[str, Any]] = []

    for file_id in file_ids:
        matching = list(temp_dir.glob(f"{user_id}_{file_id}.*")) if temp_dir.exists() else []
        if not matching:
            logger.warning("File not found for file_id", file_id=file_id, user_id=user_id)
            continue

        file_path = matching[0]
        ext = file_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".csv": "text/csv",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        try:
            file_blocks = processor.load_content_blocks_from_path(str(file_path), mime_type)
            blocks.extend(file_blocks)
        except Exception as e:
            logger.warning(
                "Failed to load file content blocks",
                file_id=file_id,
                error=str(e),
            )

    return blocks


@router.get("/conversations", response_model=TutorConversationListResponse)
async def list_conversations(
    limit: int = 20,
    offset: int = 0,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    tutor_service: TutorService = Depends(get_tutor_service),
) -> TutorConversationListResponse:
    """List user's tutor conversations."""
    result = await tutor_service.list_conversations(
        user_id=current_user.id,
        session=session,
        limit=limit,
        offset=offset,
    )

    return TutorConversationListResponse(**result)


@router.get("/conversations/{conversation_id}", response_model=TutorConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    tutor_service: TutorService = Depends(get_tutor_service),
) -> TutorConversationResponse:
    """Get a specific tutor conversation."""
    conversation = await tutor_service.get_conversation(
        user_id=current_user.id,
        conversation_id=conversation_id,
        session=session,
    )

    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    return TutorConversationResponse(**conversation)


@router.get("/stats", response_model=TutorStatsResponse)
async def get_tutor_stats(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    tutor_service: TutorService = Depends(get_tutor_service),
) -> TutorStatsResponse:
    """Get tutor usage statistics."""
    stats = await tutor_service.get_tutor_stats(
        user_id=current_user.id,
        session=session,
    )

    return TutorStatsResponse(**stats)


@router.get("/remaining", response_model=dict[str, Any])
async def get_remaining_messages(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    tutor_service: TutorService = Depends(get_tutor_service),
) -> dict[str, Any]:
    """Get remaining daily messages for the user."""
    stats = await tutor_service.get_tutor_stats(
        user_id=current_user.id,
        session=session,
    )

    remaining = stats["daily_messages_limit"] - stats["daily_messages_used"]

    return {
        "remaining_messages": max(0, remaining),
        "daily_limit": stats["daily_messages_limit"],
        "messages_used": stats["daily_messages_used"],
    }


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    tutor_service: TutorService = Depends(get_tutor_service),
) -> None:
    """Delete a specific conversation."""
    deleted = await tutor_service.delete_conversation(
        user_id=current_user.id,
        conversation_id=conversation_id,
        session=session,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )


@router.delete("/conversations")
async def delete_all_conversations(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    tutor_service: TutorService = Depends(get_tutor_service),
) -> dict[str, int]:
    """Delete all conversations for the authenticated user."""
    count = await tutor_service.delete_all_conversations(
        user_id=current_user.id,
        session=session,
    )
    return {"deleted_count": count}
