"""Qbank translation service — translate French (or any source) questions
into mos/dyu/bam/ful *before* MMS TTS synthesizes (#1690).

MMS is monolingual TTS; feeding it raw French makes gibberish in target
languages. This service calls the NLLB-200 sidecar, persists the result
per ``(question_id, language)``, and short-circuits on re-runs so audio
regeneration doesn't re-bill translations. Admin-edited rows
(``edited_by_admin=True``) are never overwritten.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.question_bank import (
    QBankQuestion,
    QBankQuestionTranslation,
    QuestionBank,
)
from app.integrations.nllb_translate import (
    NLLBTranslateClient,
    NLLBTranslateError,
    resolve_source_code,
)

logger = structlog.get_logger(__name__)

# Languages that need translation. French is the default source and is
# never translated by this service; other bank.language values (e.g. en)
# are mapped via resolve_source_code() in the NLLB client.
TARGET_LANGUAGES: tuple[str, ...] = ("mos", "dyu", "bam", "ful")


class QBankTranslationService:
    """Persist and retrieve qbank question translations."""

    def __init__(self, nllb_client: NLLBTranslateClient | None = None) -> None:
        self._nllb = nllb_client or NLLBTranslateClient()

    async def get_translation(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> QBankQuestionTranslation | None:
        """Return the stored translation row or ``None``."""
        result = await db.execute(
            select(QBankQuestionTranslation).where(
                QBankQuestionTranslation.question_id == question_id,
                QBankQuestionTranslation.language == language,
            )
        )
        return result.scalar_one_or_none()

    async def ensure_translation(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> QBankQuestionTranslation:
        """Translate ``question_id`` into ``language`` if not already stored.

        Idempotent: if a row exists (including admin-edited ones) it's
        returned as-is. Raises ``HTTPException`` 404 for unknown questions
        and ``NLLBTranslateError`` for transport failures — callers mark
        the audio row ``failed`` in that case.
        """
        if language not in TARGET_LANGUAGES:
            raise ValueError(f"ensure_translation called with non-target language: {language}")

        existing = await self.get_translation(db, question_id, language)
        if existing is not None:
            return existing

        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question not found.",
            )

        bank = await db.get(QuestionBank, question.question_bank_id)
        source_code = resolve_source_code(bank.language if bank else None)

        # Translate question_text + each option in one batch round-trip.
        source_texts = [question.question_text or ""]
        options = list(question.options or [])
        source_texts.extend(options)

        translations = await self._nllb.translate_batch(
            texts=source_texts,
            target=language,
            source=source_code,
        )

        translated_question = translations[0] if translations else ""
        translated_options = translations[1:] if len(translations) > 1 else []

        row = QBankQuestionTranslation(
            question_id=question_id,
            language=language,
            question_text=translated_question,
            options=translated_options,
            source_model=self._nllb_model_label(),
            edited_by_admin=False,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info(
            "qbank translation stored",
            question_id=str(question_id),
            language=language,
            source=source_code,
            options_count=len(translated_options),
        )
        return row

    async def batch_translate_bank(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        language: str,
    ) -> dict:
        """Translate every question in a bank into ``language``.

        Intended for Celery. Idempotent — questions already translated are
        skipped. Returns counters for observability.
        """
        if language not in TARGET_LANGUAGES:
            return {"bank_id": str(bank_id), "language": language, "skipped_lang": True}

        questions = (
            (
                await db.execute(
                    select(QBankQuestion).where(QBankQuestion.question_bank_id == bank_id)
                )
            )
            .scalars()
            .all()
        )

        existing_ids: set[uuid.UUID] = set()
        if questions:
            existing_rows = await db.execute(
                select(QBankQuestionTranslation.question_id).where(
                    QBankQuestionTranslation.question_id.in_([q.id for q in questions]),
                    QBankQuestionTranslation.language == language,
                )
            )
            existing_ids = {row for row in existing_rows.scalars()}

        translated = 0
        skipped = 0
        failed = 0
        for q in questions:
            if q.id in existing_ids:
                skipped += 1
                continue
            try:
                await self.ensure_translation(db, q.id, language)
                translated += 1
            except NLLBTranslateError as exc:
                failed += 1
                logger.warning(
                    "qbank translation failed",
                    question_id=str(q.id),
                    language=language,
                    error=str(exc),
                )

        return {
            "bank_id": str(bank_id),
            "language": language,
            "total": len(questions),
            "translated": translated,
            "skipped": skipped,
            "failed": failed,
        }

    async def invalidate_question(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
    ) -> int:
        """Drop non-admin-edited translation rows for a question.

        Called when a question's text or options change — the stored
        translation is stale. Admin-edited rows are preserved so manual
        corrections survive re-ingestion.
        """
        result = await db.execute(
            QBankQuestionTranslation.__table__.delete().where(
                QBankQuestionTranslation.question_id == question_id,
                QBankQuestionTranslation.edited_by_admin.is_(False),
            )
        )
        await db.commit()
        return result.rowcount or 0

    def _nllb_model_label(self) -> str:
        from app.infrastructure.config.settings import settings

        return f"nllb-200-{settings.nllb_model}"
