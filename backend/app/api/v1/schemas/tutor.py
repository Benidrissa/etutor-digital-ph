"""Pydantic schemas for tutor API endpoints."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class FileUploadResponse(BaseModel):
    """Response schema for file upload endpoint."""

    file_id: str = Field(..., description="Unique identifier for the uploaded file")
    original_name: str = Field(..., description="Original filename")
    mime_type: str = Field(..., description="Detected MIME type")
    size_bytes: int = Field(..., description="File size in bytes")
    expires_at: datetime = Field(..., description="When the temp file will be deleted")


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
    tutor_mode: Literal["socratic", "explanatory"] = Field(
        default="socratic",
        description="Tutor mode: socratic (guided questions) or explanatory (direct answers)",
    )
    file_ids: list[str] = Field(default_factory=list, description="Uploaded file IDs to attach")
    course_filter: list[UUID] | None = Field(
        None,
        description="Optional list of course IDs to scope this conversation (max 2)",
    )

    @field_validator("course_filter")
    @classmethod
    def validate_course_filter(cls, v: list[UUID] | None) -> list[UUID] | None:
        if v is not None and len(v) > 2:
            raise ValueError("course_filter may contain at most 2 course IDs")
        return v


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
