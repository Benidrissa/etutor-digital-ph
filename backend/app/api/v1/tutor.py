"""API endpoints for AI tutor functionality."""

import json
import uuid
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.tutor import (
    TutorChatRequest,
    TutorConversationListResponse,
    TutorConversationResponse,
    TutorStatsResponse,
)
from app.domain.services.tutor_service import TutorService
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

router = APIRouter(prefix="/tutor", tags=["tutor"])


async def get_tutor_service() -> TutorService:
    """Get tutor service with dependencies."""
    settings = get_settings()
    anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    embedding_service = EmbeddingService()
    semantic_retriever = SemanticRetriever(embedding_service)

    return TutorService(
        anthropic_client=anthropic_client,
        semantic_retriever=semantic_retriever,
        embedding_service=embedding_service,
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
    """
    logger.info(
        "Tutor chat request",
        user_id=str(current_user.id),
        message_length=len(request.message),
        module_id=str(request.module_id) if request.module_id else None,
        context_type=request.context_type,
    )

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
            ):
                # Format as SSE
                yield f"data: {json.dumps(chunk)}\n\n"

        except Exception as e:
            logger.error(
                "Error streaming tutor response", error=str(e), user_id=str(current_user.id)
            )
            error_chunk = {
                "type": "error",
                "data": {"message": "An error occurred. Please try again."},
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"

    return StreamingResponse(
        stream_tutor_response(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


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
