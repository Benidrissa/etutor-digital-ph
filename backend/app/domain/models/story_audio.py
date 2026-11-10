"""Read-aloud audio for story mode (#2704): one clip per spoken line.

A story line is spoken with OpenAI TTS (the model lesson audio and the tutor
"listen" button use) instead of the browser's synthesizer. A clip is keyed on
what makes it sound the way it does, not on the story it came from:
``text_hash`` is the sha256 of the TTS model, the voice profile, the language,
the voice version and the line's text
(:func:`app.domain.services.story_audio_service.line_hash`). The same line
heard by many learners, in any story, is synthesized once.

The audio itself (OGG Opus) lives in MinIO under ``story-audio/``
(``storage_key``). A row is written only once its clip is stored, so a row
always names a playable clip; a failed synthesis leaves no row and is tried
again on the next request.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class StoryLineAudio(Base):
    """One synthesized story line, shared by every learner who hears it."""

    __tablename__ = "story_line_audio"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    voice: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
