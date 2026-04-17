"""Question audio generation — French (OpenAI TTS) + Moore/Dioula/Bambara (MMS).

Each qbank question gets an OGG/Opus audio clip per language it supports.
French uses the same OpenAI gpt-4o-mini-tts path as LessonAudioService so
audio quality and file size stay consistent. Moore / Dioula / Bambara go
through the MMS sidecar (see app.integrations.mms_tts).

The audio script is the question read aloud followed by its options, so the
learner can take a test with eyes on the image while the text is read to
them. File size target is ~50 KB per 30s clip (Opus @ 24 kbps).
"""

from __future__ import annotations

import uuid
from typing import Literal

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.question_bank import (
    QBankAudioStatus,
    QBankQuestion,
    QBankQuestionAudio,
    QuestionBank,
)
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService
from app.integrations.mms_tts import MMSTTSClient, MMSTTSError

logger = structlog.get_logger(__name__)

SupportedLanguage = Literal["fr", "mos", "dyu", "bam"]
OPUS_CONTENT_TYPE = "audio/ogg"
OPUS_BYTES_PER_SECOND = 6 * 1024  # matches LessonAudioService._estimate_duration


def build_audio_script(question: QBankQuestion, language: str) -> str:
    """Return the text that should be spoken for a question.

    Prepends the option label in the speaker's language so the TTS reads
    "Option A: ..." in French and the native prefix in MMS languages.
    """
    prefixes = {
        "fr": "Option",
        "mos": "Tʋʋmde",  # Moore: "task/choice"
        "dyu": "Sugandili",  # Dioula/Jula: "choice"
        "bam": "Sugandili",  # Bambara: "choice"
    }
    prefix = prefixes.get(language, "Option")
    parts = [question.question_text.strip()]
    for idx, opt in enumerate(question.options or []):
        letter = chr(ord("A") + idx)
        parts.append(f"{prefix} {letter}: {opt}")
    return ". ".join(p for p in parts if p).strip() + "."


def estimate_duration_seconds(audio_bytes: int) -> int:
    """Estimate OGG/Opus clip duration from byte size (speech @ ~48 kbps)."""
    return max(1, audio_bytes // OPUS_BYTES_PER_SECOND)


class QBankAudioService:
    """Generate and store TTS audio for qbank questions."""

    def __init__(self, mms_client: MMSTTSClient | None = None) -> None:
        self._mms = mms_client or MMSTTSClient()
        self._storage = S3StorageService()

    def _storage_key(self, bank_id: uuid.UUID, question_id: uuid.UUID, language: str) -> str:
        return f"qbank-audio/{bank_id}/{question_id}/{language}.opus"

    async def _upsert_audio_row(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
        **updates: object,
    ) -> QBankQuestionAudio:
        """Create or update the (question, language) audio row."""
        existing = await db.execute(
            select(QBankQuestionAudio).where(
                QBankQuestionAudio.question_id == question_id,
                QBankQuestionAudio.language == language,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = QBankQuestionAudio(question_id=question_id, language=language)
            db.add(row)
        for field, value in updates.items():
            setattr(row, field, value)
        await db.commit()
        await db.refresh(row)
        return row

    async def _synthesize_bytes(self, script: str, language: str) -> bytes:
        """Dispatch to the right TTS backend and return OGG/Opus bytes."""
        if language == "fr":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice="nova",
                input=script,
                response_format="opus",
            )
            audio = response.content
            if not audio:
                raise ValueError("OpenAI TTS returned empty audio")
            return audio

        if MMSTTSClient.supports(language):
            return await self._mms.synthesize(script, language)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio language: {language}",
        )

    async def generate_question_audio(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> QBankQuestionAudio:
        """Generate audio for a single question in one language.

        Sets status ``generating`` while running and ``ready`` / ``failed``
        afterwards so the frontend poll endpoint can reflect progress.
        """
        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")

        await self._upsert_audio_row(db, question_id, language, status=QBankAudioStatus.generating)

        try:
            script = build_audio_script(question, language)
            audio_bytes = await self._synthesize_bytes(script, language)
            key = self._storage_key(question.question_bank_id, question_id, language)
            url = await self._storage.upload_bytes(
                key=key, data=audio_bytes, content_type=OPUS_CONTENT_TYPE
            )
        except MMSTTSError as exc:
            logger.warning("MMS synthesis failed", question_id=str(question_id), error=str(exc))
            return await self._upsert_audio_row(
                db,
                question_id,
                language,
                status=QBankAudioStatus.failed,
            )
        except Exception as exc:
            logger.exception(
                "qbank audio generation failed",
                question_id=str(question_id),
                language=language,
                error=str(exc),
            )
            return await self._upsert_audio_row(
                db, question_id, language, status=QBankAudioStatus.failed
            )

        return await self._upsert_audio_row(
            db,
            question_id,
            language,
            storage_key=key,
            storage_url=url,
            duration_seconds=estimate_duration_seconds(len(audio_bytes)),
            status=QBankAudioStatus.ready,
        )

    async def batch_generate(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        language: str,
    ) -> dict:
        """Generate audio for every question in a bank. Intended for Celery."""
        bank = await db.get(QuestionBank, bank_id)
        if bank is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question bank not found.",
            )

        questions = (
            (
                await db.execute(
                    select(QBankQuestion).where(QBankQuestion.question_bank_id == bank_id)
                )
            )
            .scalars()
            .all()
        )

        ready = 0
        failed = 0
        for q in questions:
            row = await self.generate_question_audio(db, q.id, language)
            if row.status == QBankAudioStatus.ready:
                ready += 1
            else:
                failed += 1

        return {
            "bank_id": str(bank_id),
            "language": language,
            "total": len(questions),
            "ready": ready,
            "failed": failed,
        }

    async def store_uploaded_audio(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
        audio_bytes: bytes,
        content_type: str,
    ) -> QBankQuestionAudio:
        """Handle the manual-upload fallback from the admin UI."""
        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")
        key = self._storage_key(question.question_bank_id, question_id, language)
        url = await self._storage.upload_bytes(key=key, data=audio_bytes, content_type=content_type)
        return await self._upsert_audio_row(
            db,
            question_id,
            language,
            storage_key=key,
            storage_url=url,
            duration_seconds=estimate_duration_seconds(len(audio_bytes)),
            status=QBankAudioStatus.ready,
        )

    async def get_audio_status(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> QBankQuestionAudio | None:
        result = await db.execute(
            select(QBankQuestionAudio).where(
                QBankQuestionAudio.question_id == question_id,
                QBankQuestionAudio.language == language,
            )
        )
        return result.scalar_one_or_none()
