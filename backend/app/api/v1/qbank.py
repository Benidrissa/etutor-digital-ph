"""Question Bank API — CRUD for banks, questions, tests, attempts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.qbank import (
    QuestionBankCreate,
    QuestionBankResponse,
    QuestionBankUpdate,
    QuestionListResponse,
    QuestionResponse,
    QuestionUpdate,
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
from app.domain.services.qbank_service import QBankService

router = APIRouter(prefix="/qbank", tags=["Question Bank"])

_svc = QBankService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bank_response(bank, question_count: int = 0, test_count: int = 0):
    return QuestionBankResponse(
        id=str(bank.id),
        organization_id=str(bank.organization_id),
        title=bank.title,
        description=bank.description,
        bank_type=bank.bank_type.value
        if hasattr(bank.bank_type, "value")
        else bank.bank_type,
        language=bank.language,
        time_per_question_sec=bank.time_per_question_sec,
        passing_score=bank.passing_score,
        status=bank.status.value
        if hasattr(bank.status, "value")
        else bank.status,
        question_count=question_count,
        test_count=test_count,
        created_by=str(bank.created_by),
        created_at=bank.created_at.isoformat(),
        updated_at=bank.updated_at.isoformat(),
    )


def _question_response(q):
    return QuestionResponse(
        id=str(q.id),
        question_bank_id=str(q.question_bank_id),
        order_index=q.order_index,
        image_url=q.image_url,
        question_text=q.question_text,
        options=q.options,
        correct_answer_indices=q.correct_answer_indices,
        explanation=q.explanation,
        source_page=q.source_page,
        source_pdf_name=q.source_pdf_name,
        category=q.category,
        difficulty=q.difficulty.value
        if hasattr(q.difficulty, "value")
        else q.difficulty,
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
        _bank_response(
            item["bank"], item["question_count"], item["test_count"]
        )
        for item in items
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
    bank = await _svc.update_bank(
        db, bank_id, uuid.UUID(current_user.id), **updates
    )
    return _bank_response(bank)


@router.delete(
    "/banks/{bank_id}", status_code=status.HTTP_204_NO_CONTENT
)
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
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    data = await _svc.list_questions(db, bank_id, page, per_page)
    return QuestionListResponse(
        questions=[_question_response(q) for q in data["questions"]],
        total=data["total"],
        page=data["page"],
        per_page=data["per_page"],
    )


@router.patch(
    "/questions/{question_id}", response_model=QuestionResponse
)
async def update_question(
    question_id: uuid.UUID,
    body: QuestionUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    updates = body.model_dump(exclude_unset=True)
    q = await _svc.update_question(
        db, question_id, uuid.UUID(current_user.id), **updates
    )
    return _question_response(q)


@router.delete(
    "/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question(
    question_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    await _svc.delete_question(
        db, question_id, uuid.UUID(current_user.id)
    )


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
    test = await _svc.update_test(
        db, test_id, uuid.UUID(current_user.id), **updates
    )
    return _test_response(test)


@router.delete(
    "/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_test(
    test_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    await _svc.delete_test(
        db, test_id, uuid.UUID(current_user.id)
    )


# ---------------------------------------------------------------------------
# Test Session — start / submit / history / review
# ---------------------------------------------------------------------------


@router.get(
    "/tests/{test_id}/start", response_model=TestStartResponse
)
async def start_test(
    test_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    data = await _svc.start_test(
        db, test_id, uuid.UUID(current_user.id)
    )
    test = data["test"]
    questions = [
        TestStartQuestion(
            id=str(q.id),
            image_url=q.image_url,
            question_text=q.question_text,
            options=q.options,
            category=q.category,
            difficulty=q.difficulty.value
            if hasattr(q.difficulty, "value")
            else q.difficulty,
        )
        for q in data["questions"]
    ]

    return TestStartResponse(
        test_id=str(test.id),
        title=test.title,
        mode=test.mode.value
        if hasattr(test.mode, "value")
        else test.mode,
        time_per_question_sec=data["time_per_question_sec"],
        show_feedback=test.show_feedback,
        questions=questions,
        total_questions=len(questions),
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
    attempt = await _svc.submit_test(
        db, test_id, uuid.UUID(current_user.id), body.answers
    )
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
    attempts = await _svc.get_attempt_history(
        db, test_id, uuid.UUID(current_user.id)
    )
    return [_attempt_response(a) for a in attempts]


@router.get(
    "/tests/{test_id}/review/{attempt_id}",
    response_model=TestReviewResponse,
)
async def get_review(
    test_id: uuid.UUID,
    attempt_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
):
    data = await _svc.get_review(
        db, test_id, attempt_id, uuid.UUID(current_user.id)
    )
    attempt = data["attempt"]
    review_questions = [
        TestReviewQuestion(
            id=str(item["question"].id),
            image_url=item["question"].image_url,
            question_text=item["question"].question_text,
            options=item["question"].options,
            correct_answer_indices=item[
                "question"
            ].correct_answer_indices,
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
