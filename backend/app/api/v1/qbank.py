"""Question bank REST API — banks, questions, tests, attempts."""

from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.qbank import (
    AnswerInput,
    AttemptHistoryResponse,
    CategoryScore,
    PaginatedQuestionsResponse,
    QuestionBankCreate,
    QuestionBankResponse,
    QuestionBankUpdate,
    QuestionResponse,
    QuestionUpdate,
    TestAttemptResponse,
    TestCreate,
    TestResponse,
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


def _bank_to_response(bank, question_count: int = 0) -> QuestionBankResponse:
    return QuestionBankResponse(
        id=str(bank.id),
        organization_id=str(bank.organization_id),
        title=bank.title,
        description=bank.description,
        bank_type=bank.bank_type.value if hasattr(bank.bank_type, "value") else bank.bank_type,
        is_active=bank.is_active,
        created_by=str(bank.created_by) if bank.created_by else None,
        created_at=bank.created_at.isoformat(),
        updated_at=bank.updated_at.isoformat(),
        question_count=question_count,
    )


def _question_to_response(q) -> QuestionResponse:
    return QuestionResponse(
        id=str(q.id),
        bank_id=str(q.bank_id),
        question_text=q.question_text,
        options=q.options,
        correct_answer=q.correct_answer,
        explanation=q.explanation,
        category=q.category,
        difficulty=q.difficulty,
        image_url=q.image_url,
        source_ref=q.source_ref,
        is_active=q.is_active,
        created_at=q.created_at.isoformat(),
        updated_at=q.updated_at.isoformat(),
    )


def _test_to_response(test) -> TestResponse:
    return TestResponse(
        id=str(test.id),
        bank_id=str(test.bank_id),
        title=test.title,
        description=test.description,
        mode=test.mode.value if hasattr(test.mode, "value") else test.mode,
        question_count=test.question_count,
        time_limit_minutes=test.time_limit_minutes,
        passing_score=test.passing_score,
        category_filter=test.category_filter,
        difficulty_filter=test.difficulty_filter,
        shuffle_questions=test.shuffle_questions,
        show_answers=test.show_answers,
        is_active=test.is_active,
        created_by=str(test.created_by) if test.created_by else None,
        created_at=test.created_at.isoformat(),
        updated_at=test.updated_at.isoformat(),
    )


def _attempt_to_response(attempt) -> TestAttemptResponse:
    breakdown = {
        cat: CategoryScore(
            correct=v.get("correct", 0),
            total=v.get("total", 0),
            score=v.get("score", 0.0),
        )
        for cat, v in (attempt.category_breakdown or {}).items()
    }
    return TestAttemptResponse(
        attempt_id=str(attempt.id),
        test_id=str(attempt.test_id),
        user_id=str(attempt.user_id),
        score=attempt.score or 0.0,
        total_questions=attempt.total_questions,
        correct_count=attempt.correct_count,
        passed=attempt.passed or False,
        category_breakdown=breakdown,
        time_taken_sec=attempt.time_taken_sec,
        attempted_at=attempt.attempted_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Question Bank endpoints
# ---------------------------------------------------------------------------


@router.post("/banks", status_code=status.HTTP_201_CREATED, response_model=QuestionBankResponse)
async def create_bank(
    body: QuestionBankCreate,
    org_id: uuid.UUID = Query(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> QuestionBankResponse:
    bank = await _svc.create_question_bank(
        db,
        org_id=org_id,
        title=body.title,
        bank_type=body.bank_type,
        description=body.description,
        creator_id=uuid.UUID(current_user.id),
    )
    return _bank_to_response(bank)


@router.get("/banks", response_model=list[QuestionBankResponse])
async def list_banks(
    org_id: uuid.UUID = Query(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[QuestionBankResponse]:
    await _svc._require_org_member(db, org_id, uuid.UUID(current_user.id))
    banks = await _svc.list_org_question_banks(db, org_id)
    return [_bank_to_response(b) for b in banks]


@router.get("/banks/{bank_id}", response_model=QuestionBankResponse)
async def get_bank(
    bank_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> QuestionBankResponse:
    bank = await _svc.get_question_bank(db, bank_id)
    await _svc._require_org_member(db, bank.organization_id, uuid.UUID(current_user.id))
    return _bank_to_response(bank)


@router.put("/banks/{bank_id}", response_model=QuestionBankResponse)
async def update_bank(
    bank_id: uuid.UUID,
    body: QuestionBankUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> QuestionBankResponse:
    updates = body.model_dump(exclude_unset=True)
    bank = await _svc.update_question_bank(
        db, bank_id, uuid.UUID(current_user.id), **updates
    )
    return _bank_to_response(bank)


@router.delete("/banks/{bank_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bank(
    bank_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    await _svc.delete_question_bank(db, bank_id, uuid.UUID(current_user.id))


# ---------------------------------------------------------------------------
# Question endpoints
# ---------------------------------------------------------------------------


@router.get("/banks/{bank_id}/questions", response_model=PaginatedQuestionsResponse)
async def list_questions(
    bank_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> PaginatedQuestionsResponse:
    bank = await _svc.get_question_bank(db, bank_id)
    await _svc._require_org_member(db, bank.organization_id, uuid.UUID(current_user.id))
    questions, total = await _svc.list_questions(db, bank_id, page=page, per_page=per_page)
    pages = math.ceil(total / per_page) if total > 0 else 1
    return PaginatedQuestionsResponse(
        items=[_question_to_response(q) for q in questions],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.put("/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: uuid.UUID,
    body: QuestionUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> QuestionResponse:
    updates = body.model_dump(exclude_unset=True)
    question = await _svc.update_question(
        db, question_id, uuid.UUID(current_user.id), **updates
    )
    return _question_to_response(question)


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    await _svc.delete_question(db, question_id, uuid.UUID(current_user.id))


# ---------------------------------------------------------------------------
# Test endpoints
# ---------------------------------------------------------------------------


@router.post("/tests", status_code=status.HTTP_201_CREATED, response_model=TestResponse)
async def create_test(
    body: TestCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> TestResponse:
    test = await _svc.create_test(
        db,
        bank_id=uuid.UUID(body.bank_id),
        title=body.title,
        mode=body.mode,
        description=body.description,
        question_count=body.question_count,
        time_limit_minutes=body.time_limit_minutes,
        passing_score=body.passing_score,
        category_filter=body.category_filter,
        difficulty_filter=body.difficulty_filter,
        shuffle_questions=body.shuffle_questions,
        show_answers=body.show_answers,
        creator_id=uuid.UUID(current_user.id),
    )
    return _test_to_response(test)


@router.get("/tests", response_model=list[TestResponse])
async def list_tests(
    bank_id: uuid.UUID = Query(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[TestResponse]:
    bank = await _svc.get_question_bank(db, bank_id)
    await _svc._require_org_member(db, bank.organization_id, uuid.UUID(current_user.id))
    tests = await _svc.list_tests(db, bank_id)
    return [_test_to_response(t) for t in tests]


@router.put("/tests/{test_id}", response_model=TestResponse)
async def update_test(
    test_id: uuid.UUID,
    body: TestUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> TestResponse:
    updates = body.model_dump(exclude_unset=True)
    test = await _svc.update_test(db, test_id, uuid.UUID(current_user.id), **updates)
    return _test_to_response(test)


@router.delete("/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test(
    test_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    await _svc.delete_test(db, test_id, uuid.UUID(current_user.id))


@router.get("/tests/{test_id}/start", response_model=TestStartResponse)
async def start_test(
    test_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> TestStartResponse:
    test, questions = await _svc.start_test(db, test_id, uuid.UUID(current_user.id))

    question_responses = [_question_to_response(q) for q in questions]

    if not test.show_answers:
        for qr in question_responses:
            qr.correct_answer = -1
            qr.explanation = None

    return TestStartResponse(
        test_id=str(test.id),
        mode=test.mode.value if hasattr(test.mode, "value") else test.mode,
        questions=question_responses,
        time_limit_minutes=test.time_limit_minutes,
        passing_score=test.passing_score,
    )


@router.post("/tests/{test_id}/submit", response_model=TestAttemptResponse)
async def submit_test(
    test_id: uuid.UUID,
    body: TestSubmitRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> TestAttemptResponse:
    raw_answers = {
        qid: {"selected": v.selected, "time_sec": v.time_sec}
        for qid, v in body.answers.items()
    }
    attempt = await _svc.submit_test(
        db,
        test_id=test_id,
        user_id=uuid.UUID(current_user.id),
        answers=raw_answers,
    )
    return _attempt_to_response(attempt)


@router.get("/tests/{test_id}/history", response_model=AttemptHistoryResponse)
async def get_attempt_history(
    test_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> AttemptHistoryResponse:
    attempts = await _svc.get_attempt_history(
        db, test_id, uuid.UUID(current_user.id)
    )
    return AttemptHistoryResponse(
        attempts=[_attempt_to_response(a) for a in attempts],
        total=len(attempts),
    )
