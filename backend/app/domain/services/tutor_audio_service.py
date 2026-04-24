"""On-demand TTS for the tutor "listen" button (#1932).

Mirrors ``LessonAudioService`` but keyed on (conversation_id, message_index,
language) instead of (module_id, unit_id, language), because tutor messages
are positional entries in ``tutor_conversations.messages`` JSON and carry no
per-message UUID.

Kept intentionally thin: the heavy lifting (OpenAI TTS call, MinIO upload,
style-instruction building) is reused from ``lesson_audio_service`` so that
if OpenAI consolidates TTS into the realtime stack medium-term, the swap
is isolated to one place.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.conversation import TutorConversation
from app.domain.models.tutor_voice import TutorMessageAudio
from app.domain.services.lesson_audio_service import _build_tts_instructions
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)


def _estimate_duration(file_size_bytes: int) -> int:
    """OGG Opus speech ≈ 48 kbps = 6 KB/s."""
    bytes_per_second = 6 * 1024
    return max(1, file_size_bytes // bytes_per_second)


class TutorAudioService:
    """Generate + cache TTS audio for a single tutor reply."""

    def __init__(self, storage: S3StorageService | None = None) -> None:
        self._storage = storage or S3StorageService()

    async def synthesize_for_message(
        self,
        conversation: TutorConversation,
        message_index: int,
        language: str,
        session: AsyncSession,
    ) -> TutorMessageAudio:
        """Return cached audio or synthesize, persist, and return it.

        Raises ``ValueError`` if the message index is out of range, the message
        at that index is a user message (listen button is only offered on
        assistant replies), or the message has no text content.
        """
        messages = conversation.messages or []
        if message_index < 0 or message_index >= len(messages):
            raise ValueError(
                f"message_index {message_index} out of range for conversation "
                f"{conversation.id} (len={len(messages)})"
            )
        msg = messages[message_index]
        if msg.get("role") != "assistant":
            raise ValueError(
                f"Only assistant messages support TTS; role was {msg.get('role')!r}"
            )
        text = (msg.get("content") or "").strip()
        if not text:
            raise ValueError("Cannot synthesize empty message")

        cached = await self._find_cached(
            conversation.id, message_index, language, session
        )
        if cached is not None and cached.status == "ready":
            return cached

        record = cached or TutorMessageAudio(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            message_index=message_index,
            language=language,
            status="pending",
        )
        if cached is None:
            session.add(record)
            try:
                await session.flush()
            except Exception:
                await session.rollback()
                cached = await self._find_cached(
                    conversation.id, message_index, language, session
                )
                if cached is not None:
                    return cached
                raise

        try:
            record.status = "generating"
            await session.flush()

            audio_bytes = await self._call_tts(text=text, language=language)

            storage_key = (
                f"tutor-audio/{conversation.user_id}/{conversation.id}/"
                f"{message_index:04d}/{language}.opus"
            )
            storage_url = await self._storage.upload_bytes(
                key=storage_key,
                data=audio_bytes,
                content_type="audio/ogg",
            )

            record.status = "ready"
            record.storage_key = storage_key
            record.storage_url = storage_url
            record.duration_seconds = _estimate_duration(len(audio_bytes))
            record.file_size_bytes = len(audio_bytes)
            record.generated_at = datetime.utcnow()
            await session.commit()

            logger.info(
                "Tutor message audio synthesized",
                conversation_id=str(conversation.id),
                message_index=message_index,
                language=language,
                duration_seconds=record.duration_seconds,
            )

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)[:500]
            await session.commit()
            logger.error(
                "Tutor message audio synthesis failed",
                conversation_id=str(conversation.id),
                message_index=message_index,
                language=language,
                error=str(exc),
            )
            raise

        return record

    async def _find_cached(
        self,
        conversation_id: uuid.UUID,
        message_index: int,
        language: str,
        session: AsyncSession,
    ) -> TutorMessageAudio | None:
        result = await session.execute(
            select(TutorMessageAudio).where(
                TutorMessageAudio.conversation_id == conversation_id,
                TutorMessageAudio.message_index == message_index,
                TutorMessageAudio.language == language,
            )
        )
        return result.scalars().first()

    async def _call_tts(self, text: str, language: str) -> bytes:
        """Invoke OpenAI TTS via the configured model alias."""
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        voice = "nova" if language == "fr" else "ash"
        instructions = _build_tts_instructions(
            language=language,
            course_title=None,
            is_kids=False,
            age_range="",
            level=2,
        )

        response = await client.audio.speech.create(
            model=settings.openai_tts_model,
            voice=voice,
            input=text[:4000],
            instructions=instructions,
            response_format="opus",
        )
        audio_bytes = response.content
        if not audio_bytes:
            raise ValueError("OpenAI TTS returned empty audio")
        return audio_bytes
