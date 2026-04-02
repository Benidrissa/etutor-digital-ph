"""Pydantic schemas for tutor API endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TutorMessage(BaseModel):
    """A message in a tutor conversation."""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    sources: list[dict[str, Any]] = Field(default_factory=list, description="Source citations")
    timestamp: datetime = Field(..., description="Message timestamp")
    activity_suggestions: list[dict[str, str]] = Field(
        default_factory=list, description="Suggested activities"
    )


class TutorChatRequest(BaseModel):
    """Request schema for tutor chat."""

    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    module_id: UUID | None = Field(None, description="Current module ID for context")
    context_type: str | None = Field(
        None, description="Context type: 'module', 'lesson', 'quiz', or None"
    )
    context_id: UUID | None = Field(None, description="Context-specific ID")
    conversation_id: UUID | None = Field(None, description="Existing conversation ID")


class TutorChatResponse(BaseModel):
    """Response schema for tutor chat."""

    message: TutorMessage = Field(..., description="Tutor response message")
    conversation_id: UUID = Field(..., description="Conversation ID")
    remaining_messages: int = Field(..., description="Remaining daily messages")
    sources_cited: list[dict[str, Any]] = Field(
        default_factory=list, description="Sources referenced in response"
    )
    activity_suggestions: list[dict[str, str]] = Field(
        default_factory=list, description="Suggested next activities"
    )


class ConversationSummary(BaseModel):
    """Summary of a tutor conversation."""

    id: UUID = Field(..., description="Conversation ID")
    module_id: UUID | None = Field(None, description="Associated module ID")
    message_count: int = Field(..., description="Number of messages")
    last_message_at: datetime = Field(..., description="Timestamp of last message")
    preview: str = Field(..., description="First few words of conversation")
    has_context: bool = Field(
        False, description="Whether this conversation has prior compacted context"
    )


class TutorConversationListResponse(BaseModel):
    """Response for listing tutor conversations."""

    conversations: list[ConversationSummary] = Field(..., description="List of conversations")
    total: int = Field(..., description="Total conversation count")


class TutorConversationResponse(BaseModel):
    """Response for getting a full conversation."""

    id: UUID = Field(..., description="Conversation ID")
    module_id: UUID | None = Field(None, description="Associated module ID")
    messages: list[TutorMessage] = Field(..., description="All messages in conversation")
    created_at: datetime = Field(..., description="Conversation creation timestamp")


class TutorStatsResponse(BaseModel):
    """Response for tutor usage statistics."""

    daily_messages_used: int = Field(..., description="Messages used today")
    daily_messages_limit: int = Field(..., description="Daily message limit")
    total_conversations: int = Field(..., description="Total conversation count")
    most_discussed_topics: list[str] = Field(
        default_factory=list, description="Most frequently discussed topics"
    )


class StreamChunk(BaseModel):
    """A chunk of streaming response data."""

    type: str = Field(..., description="Chunk type: 'content', 'sources', 'activity_suggestions'")
    data: Any = Field(..., description="Chunk data")
    conversation_id: UUID | None = Field(None, description="Conversation ID")
    finished: bool = Field(False, description="Whether streaming is complete")
