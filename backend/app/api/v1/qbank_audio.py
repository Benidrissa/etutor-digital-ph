"""QBank question audio endpoints: TTS generation trigger, manual upload, and retrieval."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.domain.models.qbank_question_audio import QBankQuestionAudio
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/qbank/questions", tags=["qbank-audio"])

AudioLanguage = Literal["fr", "mos", "dyu"]

_ALLOWED_AUDIO_TYPES = frozenset(
    {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/ogg", "audio/webm"}
)
_MAX_AUDIO_SIZE = 10 * 1024 * 1024


class QBankAudioResponse(BaseModel):
    audio_id: uuid.UUID = Field(..., description="Audio record ID")
    question_id: uuid.UUID = Field(..., description="Question ID")
    language: str = Field(..., description="Language code (fr / mos / dyu)")
    status: str = Field(..., description="pending | generating | ready | failed")
    audio_url: str | None = Field(None, description="Proxied audio URL when ready")
    duration_seconds: int | None = Field(None)
    file_size_bytes: int | None = Field(None)
    is_manual_upload: bool = Field(False)


class TriggerAudioRequest(BaseModel):
    question_text: str = Field(..., min_length=1, description="Question stem text")
    choices: list[dict] | None = Field(None, description='List of {"text": "..."} option dicts')
    language: AudioLanguage = Field("fr", description="Target language")


class BatchTriggerRequest(BaseModel):
    bank_id: uuid.UUID = Field(..., description="Question bank UUID")
    language: AudioLanguage = Field("fr")
    questions: list[dict] = Field(
        ...,
        description='List of {"id": "uuid", "text": "...", "choices": [...]} dicts',
    )


def _audio_url(audio: QBankQuestionAudio) -> str | None:
    if audio.status != "ready":
        return None
    return f"/api/v1/qbank/questions/{audio.question_id}/audio/{audio.id}/data"


def _to_response(audio: QBankQuestionAudio) -> QBankAudioResponse:
    return QBankAudioResponse(
        audio_id=audio.id,
        question_id=audio.question_id,
        language=audio.language,
        status=audio.status,
        audio_url=_audio_url(audio),
        duration_seconds=audio.duration_seconds if audio.status == "ready" else None,
        file_size_bytes=audio.file_size_bytes if audio.status == "ready" else None,
        is_manual_upload=audio.is_manual_upload,
    )


@router.get(
    "/{question_id}/audio",
    response_model=QBankAudioResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "No audio found for this question + language"}},
)
async def get_question_audio(
    question_id: uuid.UUID,
    lang: Annotated[AudioLanguage, Query(description="Language: fr | mos | dyu")] = "fr",
    db: AsyncSession = Depends(get_db_session),
) -> QBankAudioResponse:
    """Return audio record (URL + status) for a question in the requested language."""
    result = await db.execute(
        select(QBankQuestionAudio)
        .where(
            QBankQuestionAudio.question_id == question_id,
            QBankQuestionAudio.language == lang,
        )
        .order_by(QBankQuestionAudio.created_at.desc())
        .limit(1)
    )
    audio = result.scalars().first()

    if audio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "qbank_audio_not_found",
                "message": f"No audio for question {question_id} in language '{lang}'",
            },
        )

    logger.info(
        "QBank audio retrieved",
        question_id=str(question_id),
        language=lang,
        audio_status=audio.status,
    )
    return _to_response(audio)


@router.post(
    "/{question_id}/audio/trigger",
    response_model=QBankAudioResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_question_audio(
    question_id: uuid.UUID,
    body: TriggerAudioRequest,
    db: AsyncSession = Depends(get_db_session),
) -> QBankAudioResponse:
    """Trigger async TTS generation for a question.

    Dispatches a Celery task. Returns a pending audio record immediately.
    """
    from app.tasks.qbank_processing import generate_question_audio_task

    existing = await db.execute(
        select(QBankQuestionAudio)
        .where(
            QBankQuestionAudio.question_id == question_id,
            QBankQuestionAudio.language == body.language,
            QBankQuestionAudio.status.in_(["ready", "generating", "pending"]),
        )
        .limit(1)
    )
    audio = existing.scalars().first()
    if audio is not None:
        return _to_response(audio)

    record = QBankQuestionAudio(
        id=uuid.uuid4(),
        question_id=question_id,
        language=body.language,
        status="pending",
        is_manual_upload=False,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    generate_question_audio_task.apply_async(
        kwargs={
            "question_id": str(question_id),
            "language": body.language,
            "question_text": body.question_text,
            "choices": body.choices,
        },
        priority=5,
    )

    logger.info(
        "QBank audio generation triggered",
        question_id=str(question_id),
        language=body.language,
        audio_id=str(record.id),
    )
    return _to_response(record)


@router.post(
    "/{question_id}/audio",
    response_model=QBankAudioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload manual audio recording for a question",
)
async def upload_question_audio(
    question_id: uuid.UUID,
    lang: Annotated[AudioLanguage, Query(description="Language: fr | mos | dyu")] = "fr",
    file: UploadFile = File(..., description="Audio file (WAV, MP3, OGG, WebM)"),
    db: AsyncSession = Depends(get_db_session),
) -> QBankAudioResponse:
    """Upload a manual audio recording as a fallback for TTS generation.

    Stores in MinIO, creates/updates the qbank_question_audio row.
    Content-Type must be a supported audio format.
    Max size: 10MB.
    """
    content_type = file.content_type or ""
    if content_type not in _ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": "unsupported_audio_type",
                "message": f"Content-Type '{content_type}' not supported. "
                f"Use one of: {sorted(_ALLOWED_AUDIO_TYPES)}",
            },
        )

    audio_bytes = await file.read()
    if len(audio_bytes) > _MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "audio_too_large",
                "message": f"Audio file exceeds 10MB limit ({len(audio_bytes)} bytes)",
            },
        )
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "empty_file", "message": "Uploaded file is empty"},
        )

    ext_map = {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpeg": "mp3",
        "audio/ogg": "ogg",
        "audio/webm": "webm",
    }
    ext = ext_map.get(content_type, "bin")
    storage_key = f"qbank-audio/{question_id}/{lang}/manual.{ext}"

    storage = S3StorageService()
    storage_url = await storage.upload_bytes(
        key=storage_key,
        data=audio_bytes,
        content_type=content_type,
    )

    existing = await db.execute(
        select(QBankQuestionAudio)
        .where(
            QBankQuestionAudio.question_id == question_id,
            QBankQuestionAudio.language == lang,
        )
        .limit(1)
    )
    record = existing.scalars().first()

    if record is None:
        record = QBankQuestionAudio(
            id=uuid.uuid4(),
            question_id=question_id,
            language=lang,
            is_manual_upload=True,
        )
        db.add(record)

    record.status = "ready"
    record.storage_key = storage_key
    record.storage_url = storage_url
    record.file_size_bytes = len(audio_bytes)
    record.is_manual_upload = True
    from datetime import datetime

    record.generated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(record)

    logger.info(
        "Manual audio uploaded for question",
        question_id=str(question_id),
        language=lang,
        audio_id=str(record.id),
        size_bytes=len(audio_bytes),
    )
    return _to_response(record)


@router.get(
    "/{question_id}/audio/{audio_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"content": {"audio/wav": {}, "audio/mpeg": {}}, "description": "Audio bytes"},
        404: {"description": "Audio not found or not ready"},
    },
)
async def get_audio_data(
    question_id: uuid.UUID,
    audio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Proxy audio bytes from MinIO for a question audio record."""
    from fastapi import Response

    result = await db.execute(select(QBankQuestionAudio).where(QBankQuestionAudio.id == audio_id))
    audio = result.scalar_one_or_none()

    if audio is None or audio.question_id != question_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "audio_not_found", "message": f"Audio {audio_id} not found"},
        )

    if audio.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "audio_not_ready",
                "message": f"Audio {audio_id} is not ready (status: {audio.status})",
            },
        )

    if not audio.storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "audio_data_unavailable", "message": "No stored audio data"},
        )

    try:
        storage = S3StorageService()
        audio_bytes = await storage.download_bytes(audio.storage_key)
    except Exception as exc:
        logger.warning("S3 download failed", key=audio.storage_key, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "audio_data_unavailable", "message": "Could not retrieve audio"},
        ) from exc

    media_type = "audio/wav"
    if audio.storage_key.endswith(".mp3"):
        media_type = "audio/mpeg"
    elif audio.storage_key.endswith(".ogg"):
        media_type = "audio/ogg"

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post(
    "/audio/batch",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger batch TTS audio generation for a question bank",
)
async def trigger_batch_audio(body: BatchTriggerRequest) -> dict:
    """Dispatch a Celery task to generate TTS audio for all questions in a bank."""
    from app.tasks.qbank_processing import generate_qbank_audio_task

    task = generate_qbank_audio_task.apply_async(
        kwargs={
            "bank_id": str(body.bank_id),
            "language": body.language,
            "questions": body.questions,
        },
        priority=3,
    )

    logger.info(
        "Batch qbank audio task dispatched",
        bank_id=str(body.bank_id),
        language=body.language,
        question_count=len(body.questions),
        task_id=task.id,
    )

    return {
        "task_id": task.id,
        "bank_id": str(body.bank_id),
        "language": body.language,
        "question_count": len(body.questions),
        "status": "queued",
    }
