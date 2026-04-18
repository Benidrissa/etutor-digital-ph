"""NLLB-backed QBank question translation (#1694).

Translates the ``question_text``, ``options``, and ``explanation`` of a
QBankQuestion from the bank's source language to a target language
(currently driving-school only: fr → mos/dyu/bam) so audio generation
can read real local-language content instead of French phonemes played
by a Moore/Dyula/Bambara TTS voice.

Results are cached in ``qbank_question_translations`` keyed by
(question_id, language) with a content hash on the source fields so
edits invalidate stale translations automatically.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.question_bank import (
    QBankQuestion,
    QBankQuestionTranslation,
    QuestionBank,
)
from app.integrations.nllb import NLLBClient, NLLBError

logger = structlog.get_logger(__name__)


# Languages the driving-school flow translates into. We deliberately keep
# this small in v1 — NLLB-200 supports 200 languages but only these four
# have MMS-TTS voices, so translating to e.g. swh_Latn would produce a
# translation with no downstream audio consumer.
TRANSLATE_LANGUAGES: tuple[str, ...] = ("mos", "dyu", "bam")


def source_hash(question: QBankQuestion) -> str:
    """Content hash for (question_text, options, explanation).

    Used to detect when a cached translation is stale because the
    source question has been edited. sha256 over a canonical JSON
    representation — any field change flips the hash.
    """
    payload = json.dumps(
        {
            "t": question.question_text or "",
            "o": list(question.options or []),
            "e": question.explanation or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class QBankTranslationService:
    """Translate and cache qbank question content per target language."""

    def __init__(self, nllb_client: NLLBClient | None = None) -> None:
        self._nllb = nllb_client or NLLBClient()

    async def get_translation(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> QBankQuestionTranslation | None:
        """Return the cached translation row for (question, language) if any."""
        result = await db.execute(
            select(QBankQuestionTranslation).where(
                QBankQuestionTranslation.question_id == question_id,
                QBankQuestionTranslation.language == language,
            )
        )
        return result.scalar_one_or_none()

    async def ensure_question_translation(
        self,
        db: AsyncSession,
        question: QBankQuestion,
        target_language: str,
        source_language: str,
    ) -> QBankQuestionTranslation | None:
        """Return a cached or freshly-generated translation for one question.

        Returns ``None`` if NLLB is unreachable — the caller should fall
        back to source-language synthesis rather than crashing the whole
        audio-gen batch.
        """
        if source_language == target_language:
            return None

        current_hash = source_hash(question)
        existing = await self.get_translation(db, question.id, target_language)
        if existing is not None and existing.source_hash == current_hash:
            return existing

        texts = [question.question_text] + list(question.options or [])
        if question.explanation:
            texts.append(question.explanation)

        try:
            translated = await self._nllb.translate_batch(
                texts, source_language, target_language
            )
        except NLLBError as exc:
            logger.warning(
                "NLLB translation failed; downstream will use source text",
                question_id=str(question.id),
                target=target_language,
                error=str(exc),
            )
            return None

        new_question_text = translated[0]
        opt_count = len(question.options or [])
        new_options = list(translated[1 : 1 + opt_count])
        new_explanation = (
            translated[1 + opt_count]
            if question.explanation and len(translated) > 1 + opt_count
            else None
        )

        if existing is None:
            existing = QBankQuestionTranslation(
                question_id=question.id,
                language=target_language,
            )
            db.add(existing)
        existing.source_hash = current_hash
        existing.question_text = new_question_text
        existing.options = new_options
        existing.explanation = new_explanation
        existing.translator = "nllb-200-distilled-600M"
        await db.commit()
        await db.refresh(existing)
        return existing

    async def translate_bank(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        target_language: str,
    ) -> dict:
        """Translate every question in a bank into ``target_language``.

        Idempotent — questions whose source hash matches the cached row
        are skipped so republishing a bank doesn't re-bill the sidecar.
        """
        bank = await db.get(QuestionBank, bank_id)
        if bank is None:
            return {
                "bank_id": str(bank_id),
                "language": target_language,
                "total": 0,
                "translated": 0,
                "skipped": 0,
                "failed": 0,
            }

        questions = (
            await db.execute(
                select(QBankQuestion).where(QBankQuestion.question_bank_id == bank_id)
            )
        ).scalars().all()

        translated = 0
        skipped = 0
        failed = 0
        for question in questions:
            current_hash = source_hash(question)
            existing = await self.get_translation(db, question.id, target_language)
            if existing is not None and existing.source_hash == current_hash:
                skipped += 1
                continue
            row = await self.ensure_question_translation(
                db, question, target_language, bank.language
            )
            if row is None:
                failed += 1
            else:
                translated += 1

        return {
            "bank_id": str(bank_id),
            "language": target_language,
            "total": len(questions),
            "translated": translated,
            "skipped": skipped,
            "failed": failed,
        }

    async def invalidate_question(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
    ) -> None:
        """Drop every cached translation for a question (on edit)."""
        await db.execute(
            QBankQuestionTranslation.__table__.delete().where(
                QBankQuestionTranslation.question_id == question_id,
            )
        )
        await db.commit()
