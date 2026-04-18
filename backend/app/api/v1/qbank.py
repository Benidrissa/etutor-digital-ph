"""Question Bank API — CRUD for banks, questions, tests, attempts."""

from __future__ import annotations

import uuid
from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.qbank import (
    AudioGenerateResponse,
    AudioStatusResponse,
    BankAnalyticsResponse,
    BankStudentsResponse,
    QuestionBankCreate,
    QuestionBankResponse,
    QuestionBankUpdate,
    QuestionListResponse,
    QuestionResponse,
    QuestionUpdate,
    StudentProgressResponse,
    TestAttemptResponse,
    TestCreate,
    TestResponse,
    TestReviewQuestion,
    TestReviewResponse,
    TestStartQuestion,
    TestStartResponse,
    TestSubmitRequest,
    TestUpdate,
)
from app.domain.models.question_bank import QBankQuestion
from app.domain.services.qbank_analytics_service import QBankAnalyticsService
from app.domain.services.qbank_audio_service import QBankAudioService
from app.domain.services.qbank_service import QBankService
from app.infrastructure.storage.s3 import S3StorageService

router = APIRouter(prefix="/qbank", tags=["Question Bank"])

_svc = QBankService()
_analytics = QBankAnalyticsService()
_audio = QBankAudioService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _image_url_for(request: Request, question_id, storage_key: str | None) -> str | None:
    """Build a browser-reachable URL for a question image.

    The DB-stored ``image_url`` column targets the internal Docker hostname
    ``http://minio:9000/...`` which the browser cannot reach. We derive a proxy
    URL on every request from the inbound host headers (matching the pattern
    used by the certificate-PDF download in #1590). Returns ``None`` when the
    question has no image stored.
    """
    if not storage_key:
        return None
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        return None
    return f"{proto}://{host}/api/v1/qbank/questions/{question_id}/image"


def _audio_url_for(
    request: Request,
    question_id,
    language: str,
    storage_key: str | None,
) -> str | None:
    """Build a browser-reachable proxy URL for a question's audio clip.

    Driving-school banks ship audio in fr/mos/dyu/bam/ful (required
    so learners who can't read can still take the test). The DB column
    stores ``http://minio:9000/...`` which the browser can't reach —
    same pattern as ``_image_url_for``. Returns ``None`` when the audio
    row has no bytes yet (pending/failed states).
    """
    if not storage_key:
        return None
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        return None
    return f"{proto}://{host}/api/v1/qbank/questions/{question_id}/audio/{language}/data"


def _bank_response(bank, question_count: int = 0, test_count: int = 0):
    return QuestionBankResponse(
        id=str(bank.id),
        organization_id=str(bank.organization_id),
        title=bank.title,
        description=bank.description,
        bank_type=bank.bank_type.value if hasattr(bank.bank_type, "value") else bank.bank_type,
        language=bank.language,
        time_per_question_sec=bank.time_per_question_sec,
        passing_score=bank.passing_score,
        status=bank.status.value if hasattr(bank.status, "value") else bank.status,
        question_count=question_count,
        test_count=test_count,
        created_by=str(bank.created_by),
        created_at=bank.created_at.isoformat(),
        updated_at=bank.updated_at.isoformat(),
    )


def _question_response(q, request: Request):
    return QuestionResponse(
        id=str(q.id),
        question_bank_id=str(q.question_bank_id),
        order_index=q.order_index,
        image_url=_image_url_for(request, q.id, q.image_storage_key),
        question_text=q.question_text,
        options=q.options,
        correct_answer_indices=q.correct_answer_indices,
        explanation=q.explanation,
        source_page=q.source_page,
        source_pdf_name=q.source_pdf_name,
        category=q.category,
        difficulty=q.difficulty.value if hasattr(q.difficulty, "value") else q.difficulty,
        created_at=q.created_at.isoformat(),
    )


def _test_response(t):
    return TestResponse(
        id=str(t.id),
        question_bank_id=str(t.question_bank_id),
        title=t.title,
        mode=t.mode.value if hasattr(t.mode, "value") else t.mode,
        question_count=t.question_count,
        shuffle_questions=t.shuffle_questions,
        time_per_question_sec=t.time_per_question_sec,
        show_feedback=t.show_feedback,
        filter_categories=t.filter_categories,
        filter_failed_only=t.filter_failed_only,
        created_by=str(t.created_by),
        created_at=t.created_at.isoformat(),
    )


def _attempt_response(a):
    return TestAttemptResponse(
        id=str(a.id),
        test_id=str(a.test_id),
        score=a.score,
        total_questions=a.total_questions,
        correct_answers=a.correct_answers,
        time_taken_sec=a.time_taken_sec,
        passed=a.passed,
        category_breakdown=a.category_breakdown,
        attempted_at=a.attempted_at.isoformat(),
        attempt_number=a.attempt_number,
    )


# ---------------------------------------------------------------------------
# Question Bank CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/banks",
    status_code=status.HTTP_201_CREATED,
    response_model=QuestionBankResponse,
)
async def create_bank(
    body: QuestionBankCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    bank = await _svc.create_bank(
        db,
        organization_id=body.organization_id,
        title=body.title,
        description=body.description,
        bank_type=body.bank_type,
        language=body.language,
        time_per_question_sec=body.time_per_question_sec,
        passing_score=body.passing_score,
        created_by=uuid.UUID(current_user.id),
    )
    return _bank_response(bank)


@router.get("/banks", response_model=list[QuestionBankResponse])
async def list_banks(
    org_id: uuid.UUID = Query(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    items = await _svc.list_org_banks(db, org_id)
    return [
        _bank_response(item["bank"], item["question_count"], item["test_count"]) for item in items
    ]


@router.get("/banks/{bank_id}", response_model=QuestionBankResponse)
async def get_bank(
    bank_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    bank = await _svc.get_bank(db, bank_id)
    return _bank_response(bank)


@router.patch("/banks/{bank_id}", response_model=QuestionBankResponse)
async def update_bank(
    bank_id: uuid.UUID,
    body: QuestionBankUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    updates = body.model_dump(exclude_unset=True)
    bank = await _svc.update_bank(db, bank_id, uuid.UUID(current_user.id), **updates)
    return _bank_response(bank)


@router.delete("/banks/{bank_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bank(
    bank_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    await _svc.delete_bank(db, bank_id, uuid.UUID(current_user.id))


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


@router.get(
    "/banks/{bank_id}/questions",
    response_model=QuestionListResponse,
)
async def list_questions(
    bank_id: uuid.UUID,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    data = await _svc.list_questions(db, bank_id, page, per_page)
    return QuestionListResponse(
        questions=[_question_response(q, request) for q in data["questions"]],
        total=data["total"],
        page=data["page"],
        per_page=data["per_page"],
    )


@router.patch("/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: uuid.UUID,
    body: QuestionUpdate,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    updates = body.model_dump(exclude_unset=True)
    q = await _svc.update_question(db, question_id, uuid.UUID(current_user.id), **updates)
    return _question_response(q, request)


@router.delete(
    "/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question(
    question_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    await _svc.delete_question(db, question_id, uuid.UUID(current_user.id))


# ---------------------------------------------------------------------------
# Test CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/tests",
    status_code=status.HTTP_201_CREATED,
    response_model=TestResponse,
)
async def create_test(
    body: TestCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    test = await _svc.create_test(
        db,
        question_bank_id=body.question_bank_id,
        title=body.title,
        mode=body.mode,
        created_by=uuid.UUID(current_user.id),
        question_count=body.question_count,
        shuffle_questions=body.shuffle_questions,
        time_per_question_sec=body.time_per_question_sec,
        show_feedback=body.show_feedback,
        filter_categories=body.filter_categories,
        filter_failed_only=body.filter_failed_only,
    )
    return _test_response(test)


@router.get("/tests", response_model=list[TestResponse])
async def list_tests(
    bank_id: uuid.UUID = Query(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    tests = await _svc.list_tests(db, bank_id)
    return [_test_response(t) for t in tests]


@router.patch("/tests/{test_id}", response_model=TestResponse)
async def update_test(
    test_id: uuid.UUID,
    body: TestUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    updates = body.model_dump(exclude_unset=True)
    test = await _svc.update_test(db, test_id, uuid.UUID(current_user.id), **updates)
    return _test_response(test)


@router.delete("/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test(
    test_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    await _svc.delete_test(db, test_id, uuid.UUID(current_user.id))


# ---------------------------------------------------------------------------
# Test Session — start / submit / history / review
# ---------------------------------------------------------------------------


@router.get("/tests/{test_id}/start", response_model=TestStartResponse)
async def start_test(
    test_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from app.domain.models.question_bank import QBankAudioStatus, QBankQuestionAudio

    data = await _svc.start_test(db, test_id, uuid.UUID(current_user.id))
    test = data["test"]
    # Training mode with show_feedback relies on the client knowing the answer
    # key so it can show per-question "Correct/Incorrect" without an extra
    # round-trip. In exam mode the key stays server-side (#1632).
    mode_value = test.mode.value if hasattr(test.mode, "value") else test.mode
    expose_answers = mode_value == "training" and test.show_feedback
    questions = [
        TestStartQuestion(
            id=str(q.id),
            image_url=_image_url_for(request, q.id, q.image_storage_key),
            question_text=q.question_text,
            options=q.options,
            category=q.category,
            difficulty=q.difficulty.value if hasattr(q.difficulty, "value") else q.difficulty,
            correct_answer_indices=q.correct_answer_indices if expose_answers else None,
        )
        for q in data["questions"]
    ]

    # Preload ready audio URLs for every (question, language) pair so the
    # client can warm its HTTP cache before the timer starts (#1674).
    audio_map: dict[str, dict[str, str]] = {}
    question_ids = [q.id for q in data["questions"]]
    if question_ids:
        audio_rows = await db.execute(
            select(QBankQuestionAudio).where(
                QBankQuestionAudio.question_id.in_(question_ids),
                QBankQuestionAudio.status == QBankAudioStatus.ready,
            )
        )
        for row in audio_rows.scalars():
            url = _audio_url_for(request, row.question_id, row.language, row.storage_key)
            if url is None:
                continue
            audio_map.setdefault(str(row.question_id), {})[row.language] = url

    return TestStartResponse(
        test_id=str(test.id),
        title=test.title,
        mode=mode_value,
        time_per_question_sec=data["time_per_question_sec"],
        show_feedback=test.show_feedback,
        questions=questions,
        total_questions=len(questions),
        audio=audio_map,
    )


@router.post(
    "/tests/{test_id}/submit",
    response_model=TestAttemptResponse,
)
async def submit_test(
    test_id: uuid.UUID,
    body: TestSubmitRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    attempt = await _svc.submit_test(db, test_id, uuid.UUID(current_user.id), body.answers)
    return _attempt_response(attempt)


@router.get(
    "/tests/{test_id}/history",
    response_model=list[TestAttemptResponse],
)
async def get_history(
    test_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    attempts = await _svc.get_attempt_history(db, test_id, uuid.UUID(current_user.id))
    return [_attempt_response(a) for a in attempts]


@router.get(
    "/tests/{test_id}/review/{attempt_id}",
    response_model=TestReviewResponse,
)
async def get_review(
    test_id: uuid.UUID,
    attempt_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    data = await _svc.get_review(db, test_id, attempt_id, uuid.UUID(current_user.id))
    attempt = data["attempt"]
    review_questions = [
        TestReviewQuestion(
            id=str(item["question"].id),
            image_url=_image_url_for(
                request, item["question"].id, item["question"].image_storage_key
            ),
            question_text=item["question"].question_text,
            options=item["question"].options,
            correct_answer_indices=item["question"].correct_answer_indices,
            explanation=item["question"].explanation,
            category=item["question"].category,
            user_selected=item["user_selected"],
            is_correct=item["is_correct"],
        )
        for item in data["questions"]
    ]
    return TestReviewResponse(
        test_id=str(test_id),
        attempt_id=str(attempt.id),
        score=attempt.score,
        passed=attempt.passed,
        questions=review_questions,
    )


# ---------------------------------------------------------------------------
# PDF Upload & Processing
# ---------------------------------------------------------------------------

UPLOAD_DIR = Path("uploads/qbank")


@router.post(
    "/banks/{bank_id}/upload-pdf",
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_pdf(
    bank_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Upload a PDF to extract image-based MCQ questions from slides."""
    from app.domain.services.organization_service import OrganizationService
    from app.tasks.qbank_processing import process_qbank_pdf

    bank = await _svc.get_bank(db, bank_id)
    org_svc = OrganizationService()
    await org_svc.require_org_role(
        db,
        bank.organization_id,
        uuid.UUID(current_user.id),
    )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted.",
        )

    # Save PDF to disk
    bank_dir = UPLOAD_DIR / str(bank_id)
    bank_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = bank_dir / file.filename
    content = await file.read()
    pdf_path.write_bytes(content)

    # Dispatch Celery task
    task = process_qbank_pdf.delay(str(bank_id), file.filename)

    return {
        "task_id": task.id,
        "bank_id": str(bank_id),
        "filename": file.filename,
        "status": "processing",
    }


@router.get("/banks/{bank_id}/processing-status")
async def processing_status(
    bank_id: uuid.UUID,
    task_id: str = Query(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Check the status of a PDF processing task."""
    result = AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "bank_id": str(bank_id),
        "status": result.status.lower(),
    }
    if result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)
    return response


# ---------------------------------------------------------------------------
# Analytics (org reporting)
# ---------------------------------------------------------------------------


@router.get("/banks/{bank_id}/analytics", response_model=BankAnalyticsResponse)
async def get_bank_analytics(
    bank_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Org admin dashboard: aggregate metrics across all attempts in a bank."""
    return await _analytics.get_bank_analytics(db, bank_id, uuid.UUID(current_user.id))


@router.get("/banks/{bank_id}/students", response_model=BankStudentsResponse)
async def get_bank_students(
    bank_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Org admin: per-student roll-up (attempt count, avg score, pass count)."""
    students = await _analytics.get_bank_students(db, bank_id, uuid.UUID(current_user.id))
    return BankStudentsResponse(bank_id=str(bank_id), students=students)


@router.get(
    "/banks/{bank_id}/students/{user_id}",
    response_model=StudentProgressResponse,
)
async def get_student_progress(
    bank_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Individual student progress. Students may only view their own record."""
    return await _analytics.get_student_progress(db, bank_id, user_id, uuid.UUID(current_user.id))


# ---------------------------------------------------------------------------
# Audio generation
# ---------------------------------------------------------------------------


def _audio_response(
    row,
    question_id: uuid.UUID,
    language: str,
    request: Request,
) -> AudioStatusResponse:
    if row is None:
        return AudioStatusResponse(
            question_id=str(question_id),
            language=language,
            status="pending",
        )
    return AudioStatusResponse(
        question_id=str(question_id),
        language=language,
        status=row.status.value if hasattr(row.status, "value") else row.status,
        audio_url=_audio_url_for(request, question_id, language, row.storage_key),
        duration_seconds=row.duration_seconds,
    )


@router.post(
    "/banks/{bank_id}/audio/generate",
    response_model=AudioGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_bank_audio(
    bank_id: uuid.UUID,
    language: str = Query(..., pattern=r"^(fr|mos|dyu|bam|ful)$"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Kick off a batch audio-generation task for every question in a bank."""
    from app.domain.services.organization_service import OrganizationService
    from app.tasks.qbank_processing import generate_qbank_audio_task

    bank = await _svc.get_bank(db, bank_id)
    await OrganizationService().require_org_role(
        db, bank.organization_id, uuid.UUID(current_user.id)
    )
    task = generate_qbank_audio_task.delay(str(bank_id), language)
    return AudioGenerateResponse(task_id=task.id, bank_id=str(bank_id), language=language)


@router.post(
    "/questions/{question_id}/audio",
    response_model=AudioStatusResponse,
)
async def upload_question_audio(
    question_id: uuid.UUID,
    request: Request,
    language: str = Query(..., pattern=r"^(fr|mos|dyu|bam|ful)$"),
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Manual fallback: org admin uploads a pre-recorded audio file."""
    from fastapi import HTTPException

    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected an audio file.",
        )
    data = await file.read()
    row = await _audio.store_uploaded_audio(db, question_id, language, data, file.content_type)
    return _audio_response(row, question_id, language, request)


@router.get(
    "/questions/{question_id}/audio",
    response_model=AudioStatusResponse,
)
async def get_question_audio(
    question_id: uuid.UUID,
    request: Request,
    lang: str = Query(..., pattern=r"^(fr|mos|dyu|bam|ful)$"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """Return the audio URL + status for one question/language."""
    row = await _audio.get_audio_status(db, question_id, lang)
    return _audio_response(row, question_id, lang, request)


@router.get("/questions/{question_id}/audio/{language}/data")
async def get_question_audio_data(
    question_id: uuid.UUID,
    language: str,
    db=Depends(get_db_session),
):
    """Stream a qbank question's generated audio clip from MinIO.

    Same design as ``get_question_image`` (#1628) and
    ``lesson_audio.get_audio_data``: unauthenticated, with the
    unguessable question UUID + language as the capability. <audio>
    tags don't attach Authorization headers, and we never want to
    return the private MinIO URL. Driving-school learners who can't
    read rely on this — it's the playback endpoint for the fr/mos/dyu/bam
    TTS generated by QBankAudioService.
    """
    from sqlalchemy import select

    from app.domain.models.question_bank import QBankQuestionAudio

    result = await db.execute(
        select(QBankQuestionAudio).where(
            QBankQuestionAudio.question_id == question_id,
            QBankQuestionAudio.language == language,
        )
    )
    row = result.scalar_one_or_none()
    if row is None or not row.storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question audio not found.",
        )

    storage = S3StorageService()
    data = await storage.download_bytes(row.storage_key)
    return StreamingResponse(
        iter([data]),
        media_type="audio/ogg",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


# ---------------------------------------------------------------------------
# Image proxy — streams question images from MinIO (internal) to the browser
# ---------------------------------------------------------------------------


@router.get("/questions/{question_id}/image")
async def get_question_image(
    question_id: uuid.UUID,
    db=Depends(get_db_session),
):
    """Stream a qbank question's webp image from MinIO via the backend.

    MinIO only lives on the internal Docker network (no Traefik label), so the
    storage_url column targets ``http://minio:9000/...`` which is unreachable
    from browsers. This endpoint reuses the same pattern as the lesson audio
    streamer and serves the bytes with a long-lived cache header — the
    storage_key includes order_index so the URL is stable per question.

    No auth: <img> tags cannot attach an Authorization header, and the frontend
    embeds these URLs straight into src attributes. The unguessable question
    UUID is the capability, matching the pattern in source_images.get_image_data
    and lesson_audio.get_audio_data (#1628).
    """
    question = await db.get(QBankQuestion, question_id)
    if question is None or not question.image_storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Question image not found."
        )

    storage = S3StorageService()
    data = await storage.download_bytes(question.image_storage_key)
    return StreamingResponse(
        iter([data]),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )
