"""Story read-aloud with OpenAI TTS (#2704).

Story mode used to read its lines with the browser's own speech synthesis,
which sounds robotic or stays silent on many phones (no French voice). This
service speaks a line with the same OpenAI TTS model as lesson audio and the
tutor's "listen" button, and caches the clip by what it sounds like: the same
line in the same voice is synthesized once for every learner and every story.

Each cast member gets a *voice profile* (``narrator``, ``girl``, ``boy``,
``woman``, ``man``, ``tutor``): an OpenAI voice plus style instructions, so the
hero, the mentor and Margo the gecko sound like different people.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.story_audio import StoryLineAudio
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)

# Bump when a profile's voice or instructions change: every line is then
# synthesized again in the new voice, under a new hash.
VOICE_VERSION = 1

MAX_LINE_CHARS = 600


@dataclass(frozen=True)
class VoiceProfile:
    voice: str
    style: str


VOICE_PROFILES: dict[str, VoiceProfile] = {
    "narrator": VoiceProfile(
        voice="sage",
        style="a warm, expressive storyteller narrating an animated story, calm and clear",
    ),
    "girl": VoiceProfile(
        voice="coral",
        style="a cheerful, curious young girl of about ten, bright and lively",
    ),
    "boy": VoiceProfile(
        voice="echo",
        style="an energetic, curious young boy of about ten, playful and friendly",
    ),
    "woman": VoiceProfile(
        voice="nova",
        style="a kind, confident adult woman, a patient teacher, warm and encouraging",
    ),
    "man": VoiceProfile(
        voice="onyx",
        style="a kind, confident adult man, a patient teacher, warm and encouraging",
    ),
    "tutor": VoiceProfile(
        voice="ballad",
        style="a playful, upbeat cartoon gecko who is a friendly tutor, light and funny",
    ),
}

LANGUAGE_NAMES = {"fr": "French", "en": "English"}


class StoryAudioError(Exception):
    """The line could not be synthesized (TTS or storage failed)."""


def normalize_line(text: str) -> str:
    """The line as it is spoken: whitespace collapsed, ends trimmed."""
    return re.sub(r"\s+", " ", text or "").strip()


def line_hash(text: str, language: str, voice: str, model: str) -> str:
    """The cache key of one clip: everything that changes how it sounds."""
    material = f"{VOICE_VERSION}\x1f{model}\x1f{voice}\x1f{language}\x1f{normalize_line(text)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def tts_instructions(voice: str, language: str) -> str:
    profile = VOICE_PROFILES[voice]
    lang = LANGUAGE_NAMES.get(language, language)
    return (
        f"Speak in {lang}, as {profile.style}. "
        "This is a line of dialogue in an educational cartoon: sound natural and "
        "expressive, never robotic, and pronounce names and numbers clearly."
    )


class StoryAudioService:
    """Return the cached clip of a story line, synthesizing it on first request."""

    def __init__(self, storage: S3StorageService | None = None) -> None:
        self._storage = storage or S3StorageService()

    @staticmethod
    async def find_cached(
        text: str, language: str, voice: str, session: AsyncSession
    ) -> StoryLineAudio | None:
        digest = line_hash(text, language, voice, settings.openai_tts_model)
        result = await session.execute(
            select(StoryLineAudio).where(StoryLineAudio.text_hash == digest)
        )
        return result.scalar_one_or_none()

    async def synthesize(
        self,
        text: str,
        language: str,
        voice: str,
        session: AsyncSession,
        user_id=None,
    ) -> StoryLineAudio:
        """Synthesize, store and record one line. The caller checked the cache."""
        clean = normalize_line(text)
        model = settings.openai_tts_model
        digest = line_hash(clean, language, voice, model)
        try:
            audio_bytes = await self._call_tts(clean, language, voice, model, user_id)
            storage_key = f"story-audio/{digest[:2]}/{digest}.opus"
            await self._storage.upload_bytes(
                key=storage_key, data=audio_bytes, content_type="audio/ogg"
            )
        except Exception as exc:
            logger.warning("Story line TTS failed", voice=voice, language=language, error=str(exc))
            raise StoryAudioError(str(exc)) from exc

        # Two requests for the same new line (a prefetch and a play) can both
        # get here: the second simply rewrites the same clip under the same key.
        stmt = (
            insert(StoryLineAudio)
            .values(
                text_hash=digest,
                language=language,
                voice=voice,
                model=model,
                storage_key=storage_key,
                file_size_bytes=len(audio_bytes),
            )
            .on_conflict_do_update(
                index_elements=[StoryLineAudio.text_hash],
                set_={"storage_key": storage_key, "file_size_bytes": len(audio_bytes)},
            )
            .returning(StoryLineAudio.id)
        )
        row_id = (await session.execute(stmt)).scalar_one()
        await session.commit()
        record = await session.get(StoryLineAudio, row_id)
        assert record is not None
        return record

    async def _call_tts(self, text: str, language: str, voice: str, model: str, user_id) -> bytes:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        from app.domain.models.ai_usage_event import FEATURE_STORY_TTS
        from app.domain.services.ai_usage_service import record_ai_usage

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            response = await client.audio.speech.create(
                model=model,
                voice=VOICE_PROFILES[voice].voice,
                input=text,
                instructions=tts_instructions(voice, language),
                response_format="opus",
            )
        except Exception as exc:
            await record_ai_usage(
                provider="openai",
                model=model,
                operation="tts",
                characters=len(text),
                feature=FEATURE_STORY_TTS,
                user_id=user_id,
                success=False,
                error_type=type(exc).__name__,
            )
            raise
        await record_ai_usage(
            provider="openai",
            model=model,
            operation="tts",
            characters=len(text),
            feature=FEATURE_STORY_TTS,
            user_id=user_id,
        )
        audio_bytes = response.content
        if not audio_bytes:
            raise ValueError("OpenAI TTS returned empty audio")
        return audio_bytes
