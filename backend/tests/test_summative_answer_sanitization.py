"""Regression tests for issue #2550 — summative quiz answer-key leakage.

Summative (module-validation) quiz payloads used to ship ``correct_answer`` and
``explanation`` for every question to the client before submission, and the
practice-quiz submit endpoint accepted summative quiz ids and returned the full
answer key without recording a summative attempt or cooldown. A learner could
fail once, harvest the key, and pass the retake.

These tests exercise the route handlers directly with mocked sessions (pattern
from ``test_summative_attempt_eligibility.py``) — no database needed.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.deps_local_auth import require_active_subscription
from app.api.v1.quiz import (
    generate_summative_assessment,
    get_quiz,
    get_summative_assessment_review,
    submit_quiz_attempt,
    submit_summative_assessment_attempt,
)
from app.api.v1.schemas.quiz import (
    PublicQuizResponse,
    QuizAnswerSubmission,
    QuizAttemptRequest,
    QuizContent,
    QuizQuestion,
    QuizResponse,
    SummativeQuestionResult,
    to_public_quiz_response,
)


def _question(qid: str, correct: int = 1) -> dict:
    return {
        "id": qid,
        "question": f"Question {qid}?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": correct,
        "explanation": f"Because of {qid}.",
        "sources_cited": ["Ref p.1"],
        "difficulty": "medium",
    }


def _content_row(unit_id: str, questions: list[dict]) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.module_id = uuid.uuid4()
    row.language = "fr"
    row.level = 2
    row.country_context = "senegal"
    row.generated_at = datetime(2026, 1, 1, 12, 0, 0)
    row.content = {
        "title": "Test quiz",
        "description": "",
        "questions": questions,
        "time_limit_minutes": 30,
        "passing_score": 80.0,
        "unit_id": unit_id,
    }
    return row


def _quiz_response(unit_id: str = "summative") -> QuizResponse:
    return QuizResponse(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_id=unit_id,
        language="fr",
        level=2,
        country_context="senegal",
        content=QuizContent(
            title="Test quiz",
            questions=[QuizQuestion(**_question("q1"))],
            passing_score=80.0,
        ),
        generated_at="2026-01-01T12:00:00",
        cached=True,
    )


# ── Schema-level guarantees ──────────────────────────────────────────────────


def test_to_public_quiz_response_strips_answer_key():
    public = to_public_quiz_response(_quiz_response())

    serialized = public.model_dump_json()
    assert "correct_answer" not in serialized
    assert "explanation" not in serialized


def test_to_public_quiz_response_round_trips_other_fields():
    full = _quiz_response()
    public = to_public_quiz_response(full)

    assert public.id == full.id
    assert public.unit_id == "summative"
    assert public.content.passing_score == 80.0
    question = public.content.questions[0]
    assert question.options == ["A", "B", "C", "D"]
    assert question.sources_cited == ["Ref p.1"]
    assert question.difficulty == "medium"


def test_summative_question_result_has_no_answer_fields():
    assert "correct_answer" not in SummativeQuestionResult.model_fields
    assert "explanation" not in SummativeQuestionResult.model_fields


def test_summative_generate_requires_subscription():
    """The endpoint used to have no auth dependency at all (#2550)."""
    import inspect

    params = inspect.signature(generate_summative_assessment).parameters
    assert "current_user" in params
    assert params["current_user"].default.dependency is require_active_subscription


# ── GET /quiz/{quiz_id} ──────────────────────────────────────────────────────


def _session_returning(row) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


async def test_get_quiz_sanitizes_summative():
    row = _content_row("summative", [_question("q1")])

    resp = await get_quiz(row.id, _session_returning(row))

    assert isinstance(resp, PublicQuizResponse)
    assert not isinstance(resp, QuizResponse)
    serialized = resp.model_dump_json()
    assert "correct_answer" not in serialized
    assert "explanation" not in serialized


async def test_get_quiz_keeps_answers_for_practice_quiz():
    row = _content_row("1.2", [_question("q1")])

    resp = await get_quiz(row.id, _session_returning(row))

    assert isinstance(resp, QuizResponse)
    assert resp.content.questions[0].correct_answer == 1
    assert resp.content.questions[0].explanation


# ── POST /quiz/attempt side-channel ──────────────────────────────────────────


async def test_practice_attempt_rejects_summative_quiz():
    """One garbage submission used to return the full 20-question answer key."""
    row = _content_row("summative", [_question("q1")])
    request = QuizAttemptRequest(
        quiz_id=row.id,
        answers=[QuizAnswerSubmission(question_id="q1", selected_option=0, time_taken_seconds=5)],
        total_time_seconds=5,
    )
    user = MagicMock()
    user.id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await submit_quiz_attempt(request, _session_returning(row), user)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "not_practice_quiz"


# ── POST /quiz/summative/attempt ─────────────────────────────────────────────


async def test_summative_attempt_response_carries_no_answer_key():
    """Even a failed attempt must not reveal correct answers or explanations."""
    row = _content_row("summative", [_question("q1"), _question("q2")])

    content_result = MagicMock()
    content_result.scalar_one_or_none.return_value = row
    module_result = MagicMock()
    module_result.scalar_one_or_none.return_value = MagicMock()
    attempts_result = MagicMock()
    attempts_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[content_result, module_result, attempts_result])
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(
        side_effect=lambda obj: setattr(obj, "attempted_at", datetime(2026, 1, 2, 12, 0, 0))
    )

    user = MagicMock()
    user.id = uuid.uuid4()

    request = QuizAttemptRequest(
        quiz_id=row.id,
        answers=[
            QuizAnswerSubmission(question_id="q1", selected_option=1, time_taken_seconds=5),
            QuizAnswerSubmission(question_id="q2", selected_option=0, time_taken_seconds=5),
        ],
        total_time_seconds=10,
    )

    resp = await submit_summative_assessment_attempt(request, MagicMock(), session, user)

    assert resp.passed is False  # 50% < 80%
    assert all(isinstance(r, SummativeQuestionResult) for r in resp.results)
    serialized = resp.model_dump_json()
    # '"correct_answer":' (singular, per-question) must be gone; the top-level
    # '"correct_answers":' count is legitimate and would collide on a bare
    # substring check.
    assert '"correct_answer":' not in serialized
    assert '"explanation":' not in serialized
    assert [r.is_correct for r in resp.results] == [True, False]

    # The stored attempt keeps the full per-question record server-side — it
    # feeds the post-pass review endpoint.
    stored_attempt = session.add.call_args[0][0]
    assert stored_attempt.answers["results"][0]["correct_answer"] == 1


# ── GET /quiz/summative/{module_id}/review ───────────────────────────────────


def _passed_attempt(row) -> MagicMock:
    attempt = MagicMock()
    attempt.id = uuid.uuid4()
    attempt.assessment_id = row.id
    attempt.score = 100.0
    attempt.correct_answers = 1
    attempt.total_questions = 1
    attempt.attempted_at = datetime(2026, 1, 2, 12, 0, 0)
    attempt.answers = {
        "results": [
            {"question_id": "q1", "is_correct": True, "user_answer": 1, "correct_answer": 1}
        ]
    }
    return attempt


async def test_review_locked_without_passing_attempt():
    attempt_result = MagicMock()
    attempt_result.scalars.return_value.first.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=attempt_result)
    user = MagicMock()
    user.id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await get_summative_assessment_review(uuid.uuid4(), session, user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "review_locked"


async def test_review_returns_full_correction_after_pass():
    row = _content_row("summative", [_question("q1")])
    attempt = _passed_attempt(row)

    attempt_result = MagicMock()
    attempt_result.scalars.return_value.first.return_value = attempt
    content_result = MagicMock()
    content_result.scalar_one_or_none.return_value = row

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[attempt_result, content_result])
    user = MagicMock()
    user.id = uuid.uuid4()

    module_id = uuid.uuid4()
    resp = await get_summative_assessment_review(module_id, session, user)

    assert resp.module_id == module_id
    assert resp.attempt_id == attempt.id
    assert len(resp.questions) == 1
    question = resp.questions[0]
    assert question.correct_answer == 1
    assert question.explanation == "Because of q1."
    assert question.is_correct is True
    assert question.options == ["A", "B", "C", "D"]
