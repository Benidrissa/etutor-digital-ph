"""Schemas for story read-aloud (#2704)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.services.story_audio_service import MAX_LINE_CHARS

StoryVoice = Literal["narrator", "girl", "boy", "woman", "man", "tutor"]


class StoryLineAudioRequest(BaseModel):
    """One line of a story, as the player is about to say it."""

    text: str = Field(..., min_length=1, max_length=MAX_LINE_CHARS)
    language: Literal["fr", "en"]
    voice: StoryVoice = "narrator"


class StoryLineAudioResponse(BaseModel):
    id: UUID
    url: str = Field(..., description="Relative URL of the clip (OGG Opus), playable as is")
