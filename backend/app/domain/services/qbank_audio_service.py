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

import re
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
    QBankQuestionTranslation,
    QuestionBank,
)
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService
from app.integrations.mms_tts import MMSTTSClient, MMSTTSError
from app.integrations.nllb_translate import NLLBTranslateError

logger = structlog.get_logger(__name__)

SupportedLanguage = Literal["fr", "mos", "dyu", "bam", "ful"]

# Canonical list of languages audio is generated for. Pregeneration loops
# over this tuple when a bank is published so every (question, language)
# pair has a ready clip by the time a learner starts a test (#1674).
SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "mos", "dyu", "bam", "ful")

OPUS_CONTENT_TYPE = "audio/ogg"
OPUS_BYTES_PER_SECOND = 6 * 1024  # matches LessonAudioService._estimate_duration


_MMS_PUNCT_RE = re.compile(r"[^\w\s'\-]+", flags=re.UNICODE)
_MMS_SPACES_RE = re.compile(r"\s+")


def _normalize_for_mms(text: str) -> str:
    """Strip characters the Meta MMS VITS tokenizer can't encode (#1719).

    facebook/mms-tts-{mos,dyu,bam,ful} have 32-token character vocabs:
    lowercase letters, a few language-specific diacritics (ɛ, ɔ, ɲ, ŋ,
    ɓ, ɗ, ʋ, ã, ẽ, ĩ, õ, ũ…), plus ``'``, ``-``, space. Anything else —
    including ``? . , : ; !`` and uppercase — becomes an ``<unk>`` token
    that the model renders as noise or silence. VITS learns prosody from
    the ``add_blank`` pad tokens the tokenizer interleaves between
    characters, so stripping punctuation doesn't hurt intelligibility.

    This normalization replaces every non-word, non-hyphen, non-apostrophe
    character with a single space and collapses repeats. Uppercase is
    handled by the tokenizer itself (``normalize_text`` lowercases), but
    we do it here too for clarity in logs.
    """
    lowered = (text or "").lower()
    squashed = _MMS_PUNCT_RE.sub(" ", lowered)
    return _MMS_SPACES_RE.sub(" ", squashed).strip()


def build_audio_script(
    question: QBankQuestion,
    language: str,
    translation: QBankQuestionTranslation | None = None,
) -> str:
    """Return the text that should be spoken for a question.

    Prepends the option label in the speaker's language so the TTS reads
    "Option A: ..." in French and the native prefix in MMS languages.

    When ``translation`` is provided (#1690), its translated question_text
    and options are used instead of the source-language ones. Without it
    the raw ``question.question_text`` falls through, which is correct
    for ``fr`` (source) but produces gibberish if fed into an MMS model
    for mos/dyu/bam/ful.

    For MMS target languages the final script is passed through
    ``_normalize_for_mms`` so the per-language character vocab sees only
    tokens it can encode (#1719).
    """
    prefixes = {
        "fr": "Option",
        "mos": "Tʋʋmde",  # Moore: "task/choice"
        "dyu": "Sugandili",  # Dioula/Jula: "choice"
        "bam": "Sugandili",  # Bambara: "choice"
        "ful": "Suɓaande",  # Fulfulde: "choice"
    }
    prefix = prefixes.get(language, "Option")

    if translation is not None:
        q_text = (translation.question_text or "").strip()
        options = list(translation.options or [])
    else:
        q_text = (question.question_text or "").strip()
        options = list(question.options or [])

    parts = [q_text]
    for idx, opt in enumerate(options):
        letter = chr(ord("A") + idx)
        parts.append(f"{prefix} {letter}: {opt}")
    script = ". ".join(p for p in parts if p).strip() + "."

    if language != "fr":
        script = _normalize_for_mms(script)
    return script


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

        For non-source languages (mos/dyu/bam/ful), translates the
        question + options via NLLB first so the MMS sidecar receives
        native-language text and produces intelligible speech (#1690).
        Sets status ``generating`` while running and ``ready`` / ``failed``
        afterwards so the frontend poll endpoint can reflect progress.
        """
        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")

        await self._upsert_audio_row(db, question_id, language, status=QBankAudioStatus.generating)

        # Translate FR → target before TTS for all non-source languages.
        # Translation fetch is idempotent; on NLLB failure we mark audio
        # as failed rather than falling back to French-in-MMS (the broken
        # behavior that shipped in #1670 and was fixed by #1681/#1690).
        translation: QBankQuestionTranslation | None = None
        if language != "fr":
            from app.domain.services.qbank_translation_service import (
                QBankTranslationService,
            )

            try:
                translation = await QBankTranslationService().ensure_translation(
                    db, question_id, language
                )
            except NLLBTranslateError as exc:
                logger.warning(
                    "NLLB translation failed",
                    question_id=str(question_id),
                    language=language,
                    error=str(exc),
                )
                return await self._upsert_audio_row(
                    db, question_id, language, status=QBankAudioStatus.failed
                )

        try:
            script = build_audio_script(question, language, translation=translation)
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
        *,
        skip_ready: bool = True,
    ) -> dict:
        """Generate audio for every question in a bank. Intended for Celery.

        Idempotent by default: questions whose ``(question, language)`` row
        is already ``ready`` are skipped so republishing or retrying a
        bank doesn't re-bill TTS for clips that already exist (#1674).
        """
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

        ready_question_ids: set[uuid.UUID] = set()
        if skip_ready and questions:
            existing = await db.execute(
                select(QBankQuestionAudio).where(
                    QBankQuestionAudio.question_id.in_([q.id for q in questions]),
                    QBankQuestionAudio.language == language,
                    QBankQuestionAudio.status == QBankAudioStatus.ready,
                )
            )
            ready_question_ids = {row.question_id for row in existing.scalars()}

        ready = 0
        failed = 0
        skipped = 0
        for q in questions:
            if q.id in ready_question_ids:
                skipped += 1
                ready += 1  # Already-ready clips still count as ready.
                continue
            row = await self.generate_question_audio(db, q.id, language)
            if row.status == QBankAudioStatus.ready:
                ready += 1
            else:
                failed += 1

        return {
            "bank_id": str(bank_id),
            "language": language,
            "total": len(questions),
            "skipped": skipped,
            "ready": ready,
            "failed": failed,
        }

    async def invalidate_question(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
    ) -> None:
        """Drop every cached audio row for a question.

        Called when a question's text or options change — the stored
        clip no longer matches the script and must be regenerated.
        """
        await db.execute(
            QBankQuestionAudio.__table__.delete().where(
                QBankQuestionAudio.question_id == question_id,
            )
        )
        await db.commit()

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
