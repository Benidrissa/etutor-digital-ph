"""Pydantic schemas for tutor API endpoints."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


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
    # Resolved figure metadata for any {{source_image:UUID}} markers in content.
    # Populated by get_conversation() so history-loaded messages render the
    # same inline images as the live stream (#1937).
    source_image_refs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Resolved source_image metadata for markers in content",
    )


class TutorChatRequest(BaseModel):
    """Request schema for tutor chat."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=16000,
        description="User message (max ~4 000 tokens — generous; bumped from 2k in #1988 to fit a pasted page).",
    )
    course_id: UUID | None = Field(
        None, description="Course ID for context (derived from enrollment if absent)"
    )
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
    locale: str | None = Field(
        None, description="Active UI locale ('fr' or 'en') from the frontend"
    )


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
    daily_messages_limit: int = Field(..., description="Daily message limit (daily + credits)")
    message_credits: int = Field(default=0, description="Non-resetting AI message credit pool")
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


class LastTouchedModuleResponse(BaseModel):
    """Response for the user's most recently accessed module (#1988).

    Used by the standalone ``/tutor`` page to anchor the chat in the user's
    last-touched module by default, so the tutor's prompt has a concrete
    module context to load full lesson/quiz/case content for. ``None`` when
    the user has no enrolled course or no recorded module activity yet.
    """

    module_id: UUID = Field(..., description="Most recently touched module ID")
    module_number: int | None = Field(None, description="Module number (e.g. 1, 2)")
    module_title: str = Field(
        ..., description="Localised module title (FR or EN per user's preferred_language)"
    )
    course_id: UUID | None = Field(None, description="Owning course ID")
    course_title: str | None = Field(None, description="Localised course title")
    last_accessed: datetime | None = Field(
        None, description="When the user last touched this module"
    )
