"""Lesson audio summary generation: Claude script + Gemini TTS + MinIO upload."""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.prompts.audience import detect_audience
from app.domain.models.generated_audio import GeneratedAudio
from app.domain.models.module import Module
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)


def _build_lesson_audio_system_prompt(
    language: str,
    course_title: str | None = None,
    is_kids: bool = False,
    age_range: str = "",
) -> str:
    lang_label = "French" if language == "fr" else "English"
    domain = course_title or "general education"
    if is_kids:
        audience = f"young learners aged {age_range}"
        style = f"clear, engaging, and fun narration suitable for children aged {age_range}"
        context_note = "Reference concrete examples from West Africa that children can relate to"
    else:
        audience = f"learners in {domain}"
        style = f"clear, engaging narration suitable for {audience}"
        context_note = "Reference concrete examples from West African contexts where relevant"

    return f"""You are an expert educator in {domain} for West Africa (ECOWAS region).
Your task is to write a short spoken audio summary script for a single lesson.

Guidelines:
- Write in {lang_label}
- Length: approximately 500 words — about 3-4 minutes of spoken audio
- Style: {style}
- Structure: brief intro → key concepts recap → main takeaway
- Use simple language accessible on 2G/3G with limited bandwidth
- {context_note}
- DO NOT include headers, bullet points, or markdown — write plain spoken prose
- End with 2-3 key takeaways the listener should remember

Output only the script text, nothing else."""


LESSON_AUDIO_USER_TEMPLATE = """Module: {module_title}
Unit: {unit_id}
Language: {language_label}

Lesson content to summarize:

{lesson_content}

Write the audio summary script now."""


class LessonAudioService:
    """Pipeline: DB cache check → Claude script → Gemini TTS → MinIO upload."""

    def __init__(
        self,
        claude_service: ClaudeService | None = None,
        storage: S3StorageService | None = None,
    ) -> None:
        self._claude = claude_service or ClaudeService()
        self._storage = storage or S3StorageService()

    async def generate_for_lesson(
        self,
        lesson_id: uuid.UUID,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        lesson_content: str,
        session: AsyncSession,
    ) -> GeneratedAudio:
        """Generate or return cached audio summary for a lesson.

        Status transitions: pending → generating → ready | failed
        """
        cached = await self._find_cached(lesson_id, language, session)
        if cached is not None:
            logger.info("Returning cached lesson audio", lesson_id=str(lesson_id))
            return cached

        record = GeneratedAudio(
            id=uuid.uuid4(),
            lesson_id=lesson_id,
            module_id=module_id,
            unit_id=unit_id,
            language=language,
            status="pending",
        )
        session.add(record)
        await session.flush()

        try:
            record.status = "generating"
            await session.flush()

            # Fetch module + course context for prompt enrichment
            module = await self._fetch_module(module_id, session)
            module_title = ""
            course_title = None
            is_kids = False
            age_range = ""
            if module:
                module_title = (
                    module.title_fr if language == "fr" else module.title_en
                ) or f"Module {module.module_number}"
                course = module.course
                if course:
                    course_title = course.title_fr if language == "fr" else course.title_en
                audience_ctx = detect_audience(course)
                is_kids = audience_ctx.is_kids
                if is_kids:
                    age_range = f"{audience_ctx.age_min}-{audience_ctx.age_max}"

            script = await self._generate_script(
                lesson_content=lesson_content,
                language=language,
                module_title=module_title,
                unit_id=unit_id,
                course_title=course_title,
                is_kids=is_kids,
                age_range=age_range,
            )

            audio_bytes = await self._call_gemini_tts(script, language)

            storage_key = f"audio/lessons/{lesson_id}/{language}/summary.mp3"
            storage_url = await self._storage.upload_bytes(
                key=storage_key,
                data=audio_bytes,
                content_type="audio/mpeg",
            )

            record.status = "ready"
            record.script_text = script
            record.storage_key = storage_key
            record.storage_url = storage_url
            record.duration_seconds = _estimate_duration(len(audio_bytes))
            record.file_size_bytes = len(audio_bytes)
            record.generated_at = datetime.utcnow()
            await session.commit()

            logger.info(
                "Lesson audio generated successfully",
                lesson_id=str(lesson_id),
                audio_id=str(record.id),
                duration_seconds=record.duration_seconds,
            )

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            await session.commit()
            logger.error(
                "Lesson audio generation failed",
                lesson_id=str(lesson_id),
                audio_id=str(record.id),
                error=str(exc),
            )
            raise

        return record

    async def _find_cached(
        self,
        lesson_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> GeneratedAudio | None:
        result = await session.execute(
            select(GeneratedAudio).where(
                GeneratedAudio.lesson_id == lesson_id,
                GeneratedAudio.language == language,
                GeneratedAudio.status == "ready",
            )
        )
        return result.scalar_one_or_none()

    async def _fetch_module(self, module_id: uuid.UUID, session: AsyncSession) -> Module | None:
        result = await session.execute(
            select(Module).where(Module.id == module_id).options(selectinload(Module.course))
        )
        return result.scalar_one_or_none()

    async def _generate_script(
        self,
        lesson_content: str,
        language: str,
        module_title: str = "",
        unit_id: str = "",
        course_title: str | None = None,
        is_kids: bool = False,
        age_range: str = "",
    ) -> str:
        system_prompt = _build_lesson_audio_system_prompt(
            language=language,
            course_title=course_title,
            is_kids=is_kids,
            age_range=age_range,
        )
        language_label = "French" if language == "fr" else "English"
        user_message = LESSON_AUDIO_USER_TEMPLATE.format(
            module_title=module_title or "Unknown",
            unit_id=unit_id or "Unknown",
            language_label=language_label,
            lesson_content=lesson_content[:4000],
        )

        response = await self._claude.generate_lesson_content(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        script_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                script_text += block.text

        if not script_text.strip():
            raise ValueError("Claude returned empty script for lesson audio")

        logger.info(
            "Lesson audio script generated",
            language=language,
            script_length=len(script_text),
        )
        return script_text.strip()

    async def _call_gemini_tts(self, script: str, language: str) -> bytes:
        """Call Gemini TTS API to convert script to MP3 bytes."""
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini TTS")

        from google import genai  # type: ignore[import-untyped]
        from google.genai import types  # type: ignore[import-untyped]

        client = genai.Client(api_key=settings.google_api_key)

        # Use Aoede for French (warm female voice), Charon for English
        voice_name = "Aoede" if language == "fr" else "Charon"

        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=script,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        ),
                    ),
                ),
            ),
        )

        audio_bytes = _extract_audio_bytes(response)

        logger.info(
            "Gemini TTS audio generated for lesson",
            language=language,
            voice=voice_name,
            audio_size_bytes=len(audio_bytes),
        )
        return audio_bytes


def _extract_audio_bytes(response: object) -> bytes:
    """Extract raw audio bytes from Gemini TTS response."""
    try:
        for part in response.candidates[0].content.parts:  # type: ignore[union-attr]
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    except Exception as exc:
        logger.error("Failed to extract audio bytes from Gemini response", error=str(exc))

    raise ValueError("No audio data found in Gemini TTS response")


def _estimate_duration(file_size_bytes: int) -> int:
    """Estimate audio duration from file size. Assumes ~128kbps MP3."""
    bytes_per_second = (128 * 1024) // 8
    return max(1, file_size_bytes // bytes_per_second)
