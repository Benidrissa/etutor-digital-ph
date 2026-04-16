"""QBank question audio generation: Gemini TTS (FR) + Meta MMS (Moore/Dioula) + MinIO upload."""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.qbank_question_audio import QBankQuestionAudio
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)

SUPPORTED_LANGUAGES = frozenset({"fr", "mos", "dyu"})
_GEMINI_LANGUAGES = frozenset({"fr"})
_MMS_LANGUAGES = frozenset({"mos", "dyu"})


def _build_question_audio_script(
    question_text: str,
    choices: list[dict[str, str]] | None = None,
) -> str:
    """Concatenate question text + options into a spoken audio script."""
    parts = [question_text.strip()]
    if choices:
        option_labels = ["A", "B", "C", "D", "E"]
        for i, choice in enumerate(choices[:5]):
            label = option_labels[i]
            text = choice.get("text", "").strip()
            if text:
                parts.append(f"Option {label}: {text}")
    return "  ".join(parts)


class QBankAudioService:
    """Pipeline: DB cache check → TTS (Gemini or MMS) → MinIO upload."""

    def __init__(self, storage: S3StorageService | None = None) -> None:
        self._storage = storage or S3StorageService()

    async def generate_question_audio(
        self,
        question_id: uuid.UUID,
        language: str,
        question_text: str,
        choices: list[dict[str, str]] | None = None,
        session: AsyncSession | None = None,
        *,
        _session: AsyncSession | None = None,
    ) -> QBankQuestionAudio:
        """Generate or return cached TTS audio for a single question.

        Args:
            question_id: UUID of the qbank question.
            language: "fr" (Gemini TTS), "mos" or "dyu" (Meta MMS).
            question_text: The question stem text.
            choices: Optional list of {"text": "..."} option dicts.
            session: Async SQLAlchemy session.

        Returns:
            QBankQuestionAudio record (status="ready" on success).
        """
        db = session or _session
        if db is None:
            raise ValueError("session is required")

        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. Supported: {sorted(SUPPORTED_LANGUAGES)}"
            )

        cached = await self._find_cached(question_id, language, db)
        if cached is not None:
            logger.info(
                "Returning cached question audio",
                question_id=str(question_id),
                language=language,
            )
            return cached

        record = QBankQuestionAudio(
            id=uuid.uuid4(),
            question_id=question_id,
            language=language,
            status="pending",
            is_manual_upload=False,
        )
        db.add(record)
        try:
            await db.flush()
        except Exception:
            await db.rollback()
            cached = await self._find_cached(question_id, language, db)
            if cached is not None:
                return cached
            raise

        try:
            record.status = "generating"
            await db.flush()

            script = _build_question_audio_script(question_text, choices)

            if language in _GEMINI_LANGUAGES:
                audio_bytes, content_type = await self._call_gemini_tts(script, language)
                ext = "wav"
            else:
                audio_bytes, content_type = await self._call_mms_tts(script, language)
                ext = "wav"

            storage_key = f"qbank-audio/{question_id}/{language}/question.{ext}"
            storage_url = await self._storage.upload_bytes(
                key=storage_key,
                data=audio_bytes,
                content_type=content_type,
            )

            record.status = "ready"
            record.storage_key = storage_key
            record.storage_url = storage_url
            record.duration_seconds = _estimate_duration_wav(len(audio_bytes))
            record.file_size_bytes = len(audio_bytes)
            record.generated_at = datetime.utcnow()
            await db.commit()

            logger.info(
                "Question audio generated",
                question_id=str(question_id),
                language=language,
                audio_id=str(record.id),
                size_bytes=len(audio_bytes),
            )

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            await db.commit()
            logger.error(
                "Question audio generation failed",
                question_id=str(question_id),
                language=language,
                error=str(exc),
            )
            raise

        return record

    async def batch_generate_audio(
        self,
        bank_id: uuid.UUID,
        language: str,
        questions: list[dict],
        session: AsyncSession,
    ) -> dict:
        """Generate TTS audio for all questions in a bank.

        Args:
            bank_id: UUID of the question bank (for logging).
            language: Target language ("fr", "mos", "dyu").
            questions: List of {"id": uuid, "text": str, "choices": [...]} dicts.
            session: Async SQLAlchemy session.

        Returns:
            {"generated": [...], "skipped": [...], "failed": [...]}
        """
        generated: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []

        for q in questions:
            qid_raw = q.get("id")
            question_text = q.get("text", "")
            choices = q.get("choices")
            if not qid_raw or not question_text:
                continue

            qid = uuid.UUID(str(qid_raw))
            label = str(qid)

            existing = await self._find_cached(qid, language, session)
            if existing is not None:
                skipped.append(label)
                continue

            try:
                await self.generate_question_audio(
                    question_id=qid,
                    language=language,
                    question_text=question_text,
                    choices=choices,
                    session=session,
                )
                generated.append(label)
            except Exception as exc:
                failed.append(label)
                logger.error(
                    "Batch audio: question failed",
                    bank_id=str(bank_id),
                    question_id=label,
                    language=language,
                    error=str(exc),
                )

        logger.info(
            "Batch audio generation complete",
            bank_id=str(bank_id),
            language=language,
            generated=len(generated),
            skipped=len(skipped),
            failed=len(failed),
        )

        return {"generated": generated, "skipped": skipped, "failed": failed}

    async def _find_cached(
        self,
        question_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> QBankQuestionAudio | None:
        result = await session.execute(
            select(QBankQuestionAudio)
            .where(
                QBankQuestionAudio.question_id == question_id,
                QBankQuestionAudio.language == language,
                QBankQuestionAudio.status == "ready",
            )
            .limit(1)
        )
        return result.scalars().first()

    async def _call_gemini_tts(self, script: str, language: str) -> tuple[bytes, str]:
        """Call Google Gemini TTS API for French synthesis.

        Returns:
            (audio_bytes, content_type)
        """
        import google.generativeai as genai

        genai.configure(api_key=settings.google_api_key)

        voice_name = "fr-FR-Standard-A"
        tts_config = {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": voice_name},
            }
        }

        model = genai.GenerativeModel("gemini-2.5-flash-preview-tts")
        response = model.generate_content(
            contents=script,
            generation_config=genai.types.GenerationConfig(
                response_modalities=["AUDIO"],
                speech_config=tts_config,
            ),
        )

        audio_bytes: bytes = b""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                audio_bytes += part.inline_data.data

        if not audio_bytes:
            raise ValueError("Gemini TTS returned empty audio for question")

        logger.info(
            "Gemini TTS: question audio generated",
            language=language,
            size_bytes=len(audio_bytes),
        )
        return audio_bytes, "audio/wav"

    async def _call_mms_tts(self, script: str, language: str) -> tuple[bytes, str]:
        """Call Meta MMS sidecar for Moore/Dioula synthesis.

        Returns:
            (audio_bytes, content_type)
        """
        from app.integrations.mms_tts import MMSTTSClient

        client = MMSTTSClient()
        audio_bytes = await client.synthesize(text=script, language=language)
        return audio_bytes, "audio/wav"


def _estimate_duration_wav(file_size_bytes: int) -> int:
    """Estimate WAV audio duration from file size.

    WAV PCM 16kHz mono 16-bit = 32000 bytes/sec.
    """
    bytes_per_second = 32000
    return max(1, file_size_bytes // bytes_per_second)
