"""Celery tasks for question bank PDF processing."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/qbank")


class QBankTask(Task):
    def on_success(self, retval, task_id, args, kwargs):
        logger.info("QBank processing completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("QBank processing failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    base=QBankTask,
    bind=True,
    name="qbank.process_pdf",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=600,
    time_limit=660,
    rate_limit="2/m",
)
def process_qbank_pdf(
    self,
    bank_id: str,
    pdf_filename: str,
) -> dict:
    """Process a PDF into question bank questions.

    1. Extract questions from each slide via Claude Vision
    2. Store images in MinIO
    3. Create QBankQuestion rows in the database
    """
    return asyncio.run(_process_pdf_async(self, bank_id, pdf_filename))


async def _process_pdf_async(task, bank_id: str, pdf_filename: str) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.ai.qbank_slide_extractor import extract_questions_from_pdf
    from app.domain.models.question_bank import QBankQuestion
    from app.infrastructure.config.settings import settings
    from app.infrastructure.storage.s3 import S3StorageService

    bank_uuid = uuid.UUID(bank_id)
    pdf_dir = UPLOAD_DIR / bank_id
    pdf_path = pdf_dir / pdf_filename

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Extract questions from slides
    logger.info("Starting PDF extraction", bank_id=bank_id, pdf=pdf_filename)
    extracted = await extract_questions_from_pdf(pdf_path)

    if not extracted:
        logger.warning("No questions extracted from PDF", bank_id=bank_id)
        return {"bank_id": bank_id, "questions_created": 0, "errors": []}

    # Store images and create DB rows
    storage = S3StorageService()
    engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
    errors = []
    created = 0

    created_question_ids: list[str] = []
    with Session(engine) as session:
        # Get current max order_index for this bank
        from sqlalchemy import func, select

        max_order = session.scalar(
            select(func.coalesce(func.max(QBankQuestion.order_index), 0)).where(
                QBankQuestion.question_bank_id == bank_uuid
            )
        )
        next_order = (max_order or 0) + 1

        for idx, q in enumerate(extracted):
            try:
                # Upload image to MinIO directly — we're already in an async
                # context, so await the coroutine. A previous nested
                # run_until_complete call crashed with "no current event loop".
                storage_key = f"qbank/{bank_id}/images/{next_order + idx}.webp"
                image_url = await storage.upload_bytes(
                    key=storage_key,
                    data=q.image_bytes,
                    content_type="image/webp",
                )

                question = QBankQuestion(
                    question_bank_id=bank_uuid,
                    order_index=next_order + idx,
                    image_storage_key=storage_key,
                    image_url=image_url,
                    question_text=q.question_text,
                    options=q.options,
                    correct_answer_indices=q.correct_indices,
                    explanation=q.explanation,
                    source_page=q.page_number,
                    source_pdf_name=pdf_filename,
                    category=q.category,
                )
                session.add(question)
                session.flush()  # populate question.id before commit
                created_question_ids.append(str(question.id))
                created += 1

            except Exception as e:
                logger.warning(
                    "Failed to save question",
                    page=q.page_number,
                    error=str(e),
                )
                errors.append({"page": q.page_number, "error": str(e)})

        session.commit()

    engine.dispose()
    logger.info(
        "PDF processing complete",
        bank_id=bank_id,
        questions_created=created,
        errors_count=len(errors),
    )

    # Fire audio pregeneration for every supported language (#1674).
    # Per-question fan-out (#1708): each non-FR (question, language)
    # pair becomes its own task, so MMS synthesis for question K can
    # start as soon as NLLB translation for K is done — no more waiting
    # for the whole bank to finish translating. French has no
    # translation step, so it uses the single bank-level task.
    if created:
        from app.domain.services.qbank_audio_service import SUPPORTED_LANGUAGES
        from app.domain.services.qbank_translation_service import TARGET_LANGUAGES

        for language in SUPPORTED_LANGUAGES:
            try:
                if language in TARGET_LANGUAGES:
                    for qid in created_question_ids:
                        translate_and_synthesize_question_task.delay(qid, language)
                else:
                    generate_qbank_audio_task.delay(bank_id, language)
            except Exception as exc:
                logger.warning(
                    "failed to enqueue post-extract audio pregeneration",
                    bank_id=bank_id,
                    language=language,
                    error=str(exc),
                )

    return {
        "bank_id": bank_id,
        "questions_created": created,
        "errors": errors,
    }


@celery_app.task(
    base=QBankTask,
    bind=True,
    name="qbank.generate_audio",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=900,
    time_limit=960,
    rate_limit="5/m",
)
def generate_qbank_audio_task(self, bank_id: str, language: str) -> dict:
    """Generate TTS audio for every question in a bank, one language at a time."""
    return asyncio.run(_generate_audio_async(bank_id, language))


async def _generate_audio_async(bank_id: str, language: str) -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.domain.services.qbank_audio_service import QBankAudioService
    from app.infrastructure.config.settings import settings

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = QBankAudioService()

    async with session_factory() as session:
        try:
            result = await service.batch_generate(session, uuid.UUID(bank_id), language)
        finally:
            await engine.dispose()

    logger.info(
        "qbank audio batch complete",
        bank_id=bank_id,
        language=language,
        result=result,
    )
    return result


@celery_app.task(
    base=QBankTask,
    bind=True,
    name="qbank.translate",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=600,
    time_limit=660,
    rate_limit="5/m",
)
def translate_qbank_bank_task(self, bank_id: str, language: str) -> dict:
    """Translate every question in a bank into ``language`` via NLLB (#1690).

    Runs *before* ``generate_qbank_audio_task`` in the pregeneration chain
    so MMS TTS receives native-language text and produces intelligible
    audio rather than French-with-target-phonology gibberish.
    """
    return asyncio.run(_translate_bank_async(bank_id, language))


async def _translate_bank_async(bank_id: str, language: str) -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.domain.services.qbank_translation_service import (
        QBankTranslationService,
    )
    from app.infrastructure.config.settings import settings

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = QBankTranslationService()

    async with session_factory() as session:
        try:
            result = await service.batch_translate_bank(session, uuid.UUID(bank_id), language)
        finally:
            await engine.dispose()

    logger.info(
        "qbank translation batch complete",
        bank_id=bank_id,
        language=language,
        result=result,
    )
    return result


@celery_app.task(
    base=QBankTask,
    bind=True,
    name="qbank.translate_and_synthesize_question",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=600,
    time_limit=660,
    rate_limit="20/m",
)
def translate_and_synthesize_question_task(self, question_id: str, language: str) -> dict:
    """Translate one (question, language) pair then synthesize its audio (#1708).

    Per-question fan-out replaces the old bank-level translate→audio
    chain: as soon as NLLB finishes a single question's translation,
    the paired MMS synthesis starts for that question, in parallel with
    NLLB translating the next question. On a multi-worker Celery pool
    this serializes only on the sidecar side (NLLB semaphore=1, MMS
    semaphore=2) instead of on the whole 11-question batch.
    """
    return asyncio.run(_translate_and_synthesize_question_async(question_id, language))


async def _translate_and_synthesize_question_async(question_id: str, language: str) -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.domain.services.qbank_audio_service import QBankAudioService
    from app.domain.services.qbank_translation_service import (
        QBankTranslationService,
    )
    from app.infrastructure.config.settings import settings

    qid = uuid.UUID(question_id)
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await QBankTranslationService().ensure_translation(session, qid, language)
        async with session_factory() as session:
            audio_row = await QBankAudioService().generate_question_audio(session, qid, language)
    finally:
        await engine.dispose()

    logger.info(
        "qbank translate+synth complete",
        question_id=question_id,
        language=language,
        audio_status=audio_row.status.value
        if hasattr(audio_row.status, "value")
        else str(audio_row.status),
    )
    return {
        "question_id": question_id,
        "language": language,
        "audio_status": audio_row.status.value
        if hasattr(audio_row.status, "value")
        else str(audio_row.status),
    }
