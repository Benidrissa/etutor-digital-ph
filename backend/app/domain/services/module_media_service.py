"""Service for AI-generated audio/video module summaries (issue #539).

Generation pipeline:
  Audio: Claude API (text summary) → Google Cloud TTS → MP3 bytes stored in DB
  Video: Claude API (script) → Gemini multimodal or ffmpeg/TTS compose → stored in DB

Fallback strategy:
  1. Google Gemini TTS (gemini-2.0-flash / gemini-2.5-pro) if google_api_key configured
  2. Google Cloud Text-to-Speech REST API if google_cloud_tts_api_key configured
  3. Anthropic Claude narrative summary as plain text if neither key is available
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.module import Module
from app.domain.models.module_media import ModuleMedia
from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

_SUMMARY_PROMPT_FR = (
    "Tu es un expert en santé publique pour l'Afrique de l'Ouest. "
    "Génère un résumé audio de ce module pour des professionnels de santé. "
    "Le résumé doit durer entre 5 et 7 minutes à la lecture à voix haute (environ 800-1000 mots). "
    "Structure: introduction (contexte africain), objectifs clés, concepts principaux, "
    "application pratique en Afrique de l'Ouest, conclusion. "
    "Utilise un langage clair et accessible. Ne mentionne pas de numéros de page ou de références bibliographiques. "
    "Réponds en français uniquement."
)

_SUMMARY_PROMPT_EN = (
    "You are a public health expert for West Africa. "
    "Generate an audio summary of this module for health professionals. "
    "The summary should take 5-7 minutes to read aloud (approximately 800-1000 words). "
    "Structure: introduction (African context), key objectives, main concepts, "
    "practical application in West Africa, conclusion. "
    "Use clear, accessible language. Do not mention page numbers or bibliographic references. "
    "Reply in English only."
)


class ModuleMediaService:
    """Generate and cache audio/video summaries for modules."""

    async def get_or_generate(
        self,
        module_id: uuid.UUID,
        media_type: str,
        language: str,
        session: AsyncSession,
        force_regenerate: bool = False,
    ) -> ModuleMedia:
        """Return existing ready media or create a new pending record.

        Does NOT perform the actual generation — that is handled by the Celery task.
        Returns the ModuleMedia record with status 'pending' or 'ready'.
        """
        if not force_regenerate:
            existing = await self._find_existing(module_id, media_type, language, session)
            if existing and existing.status == "ready":
                return existing

        record = ModuleMedia(
            id=uuid.uuid4(),
            module_id=module_id,
            media_type=media_type,
            language=language,
            status="pending",
        )
        session.add(record)
        await session.flush()
        await session.commit()
        return record

    async def generate_audio(
        self,
        media_id: uuid.UUID,
        module_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> ModuleMedia:
        """Full audio generation pipeline: script → TTS → store MP3.

        Status transitions: pending → generating → ready | failed
        """
        result = await session.execute(select(ModuleMedia).where(ModuleMedia.id == media_id))
        record = result.scalar_one_or_none()
        if record is None:
            raise ValueError(f"ModuleMedia {media_id} not found")

        try:
            record.status = "generating"
            await session.flush()

            module_result = await session.execute(select(Module).where(Module.id == module_id))
            module = module_result.scalar_one_or_none()
            if module is None:
                raise ValueError(f"Module {module_id} not found")

            module_title = module.title_fr if language == "fr" else module.title_en
            module_desc = (
                (module.description_fr if language == "fr" else module.description_en) or ""
            )

            script = await self._generate_script(module_title, module_desc, language)
            audio_bytes, mime = await self._text_to_speech(script, language)

            record.status = "ready"
            record.media_data = audio_bytes
            record.mime_type = mime
            record.file_size_bytes = len(audio_bytes)
            record.url = f"/api/v1/modules/{module_id}/media/{record.id}/data"
            record.duration_seconds = _estimate_duration(script)
            record.generated_at = datetime.utcnow()
            record.error_message = None
            await session.commit()

            logger.info(
                "Audio summary generated",
                media_id=str(media_id),
                module_id=str(module_id),
                language=language,
                size_bytes=len(audio_bytes),
            )
            return record

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            await session.commit()
            logger.error(
                "Audio summary generation failed",
                media_id=str(media_id),
                module_id=str(module_id),
                error=str(exc),
            )
            return record

    async def generate_video(
        self,
        media_id: uuid.UUID,
        module_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> ModuleMedia:
        """Video summary generation pipeline.

        Current implementation: generates a structured script with Claude,
        stores it as a JSON blob (media_data) with status='ready' and mime_type='application/json'.
        A future iteration can compose an actual video with ffmpeg + TTS.
        """
        result = await session.execute(select(ModuleMedia).where(ModuleMedia.id == media_id))
        record = result.scalar_one_or_none()
        if record is None:
            raise ValueError(f"ModuleMedia {media_id} not found")

        try:
            record.status = "generating"
            await session.flush()

            module_result = await session.execute(select(Module).where(Module.id == module_id))
            module = module_result.scalar_one_or_none()
            if module is None:
                raise ValueError(f"Module {module_id} not found")

            module_title = module.title_fr if language == "fr" else module.title_en
            module_desc = (
                (module.description_fr if language == "fr" else module.description_en) or ""
            )

            script_data = await self._generate_video_script(module_title, module_desc, language)
            script_bytes = json.dumps(script_data, ensure_ascii=False).encode("utf-8")

            record.status = "ready"
            record.media_data = script_bytes
            record.mime_type = "application/json"
            record.file_size_bytes = len(script_bytes)
            record.url = f"/api/v1/modules/{module_id}/media/{record.id}/data"
            record.duration_seconds = script_data.get("estimated_duration_seconds")
            record.generated_at = datetime.utcnow()
            record.error_message = None
            await session.commit()

            logger.info(
                "Video script generated",
                media_id=str(media_id),
                module_id=str(module_id),
                language=language,
            )
            return record

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            await session.commit()
            logger.error(
                "Video summary generation failed",
                media_id=str(media_id),
                module_id=str(module_id),
                error=str(exc),
            )
            return record

    async def _find_existing(
        self,
        module_id: uuid.UUID,
        media_type: str,
        language: str,
        session: AsyncSession,
    ) -> ModuleMedia | None:
        result = await session.execute(
            select(ModuleMedia).where(
                ModuleMedia.module_id == module_id,
                ModuleMedia.media_type == media_type,
                ModuleMedia.language == language,
            )
        )
        return result.scalar_one_or_none()

    async def _generate_script(
        self, module_title: str, module_description: str, language: str
    ) -> str:
        """Generate a spoken summary script via Claude API."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0)
        system = _SUMMARY_PROMPT_FR if language == "fr" else _SUMMARY_PROMPT_EN
        user_content = (
            f"Module: {module_title}\n\nDescription: {module_description}\n\n"
            "Generate the audio summary now."
        )

        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return message.content[0].text if message.content else ""

    async def _generate_video_script(
        self, module_title: str, module_description: str, language: str
    ) -> dict:
        """Generate a structured video script via Claude API."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0)

        if language == "fr":
            system = (
                "Tu es un expert en santé publique pour l'Afrique de l'Ouest. "
                "Génère un script structuré pour une vidéo résumé de 3-5 minutes de ce module. "
                "Réponds en JSON avec ce format exact:\n"
                '{"title": "...", "estimated_duration_seconds": 240, "slides": ['
                '{"slide_number": 1, "title": "...", "narration": "...", "key_points": ["..."]}]}'
            )
        else:
            system = (
                "You are a public health expert for West Africa. "
                "Generate a structured script for a 3-5 minute video summary of this module. "
                "Reply in JSON with this exact format:\n"
                '{"title": "...", "estimated_duration_seconds": 240, "slides": ['
                '{"slide_number": 1, "title": "...", "narration": "...", "key_points": ["..."]}]}'
            )

        user_content = (
            f"Module: {module_title}\n\nDescription: {module_description}\n\n"
            "Generate the video script now. Reply ONLY with valid JSON."
        )

        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        text = message.content[0].text if message.content else "{}"
        try:
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            return {
                "title": module_title,
                "estimated_duration_seconds": 240,
                "slides": [{"slide_number": 1, "title": module_title, "narration": text, "key_points": []}],
            }

    async def _text_to_speech(self, text: str, language: str) -> tuple[bytes, str]:
        """Convert text to audio using available TTS service.

        Priority:
          1. Google Cloud TTS (if google_cloud_tts_api_key set)
          2. Google Gemini TTS (if google_api_key set)
          3. Encoded plain text fallback (for development without API keys)
        """
        if settings.google_cloud_tts_api_key:
            return await self._google_cloud_tts(text, language)
        if settings.google_api_key:
            return await self._gemini_tts(text, language)
        return self._plain_text_fallback(text)

    async def _google_cloud_tts(self, text: str, language: str) -> tuple[bytes, str]:
        """Call Google Cloud Text-to-Speech REST API."""
        import httpx

        lang_code = "fr-FR" if language == "fr" else "en-US"
        voice_name = "fr-FR-Neural2-A" if language == "fr" else "en-US-Neural2-F"

        payload = {
            "input": {"text": text},
            "voice": {"languageCode": lang_code, "name": voice_name},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.95},
        }
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={settings.google_cloud_tts_api_key}"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            audio_bytes = base64.b64decode(data["audioContent"])
            return audio_bytes, "audio/mpeg"

    async def _gemini_tts(self, text: str, language: str) -> tuple[bytes, str]:
        """Call Google Gemini API to generate audio content."""
        import httpx

        model = "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.google_api_key}"

        lang_instruction = "Generate an audio narration in French." if language == "fr" else "Generate an audio narration in English."
        payload = {
            "contents": [{"parts": [{"text": f"{lang_instruction}\n\n{text}"}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}}},
        }

        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            audio_b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            audio_bytes = base64.b64decode(audio_b64)
            return audio_bytes, "audio/wav"

    def _plain_text_fallback(self, text: str) -> tuple[bytes, str]:
        """Return plain text encoded as bytes (development fallback, no TTS key)."""
        return text.encode("utf-8"), "text/plain; charset=utf-8"


def _estimate_duration(script: str) -> int:
    """Estimate audio duration based on word count (~150 words/min spoken)."""
    word_count = len(script.split())
    return max(60, int(word_count / 150 * 60))
