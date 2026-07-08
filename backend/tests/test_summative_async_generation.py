"""Tests for issue #2608 — summative assessment async generation.

Summative generation covers every module unit and takes ~60-90s, which used to
run synchronously inside ``POST /quiz/summative/generate``. That exceeded the
frontend proxy's 30s timeout: the proxy severed the socket and the learner saw a
false "generation failed" while the backend quietly finished and cached the
quiz. Generation is now dispatched to a Celery task and the endpoint returns
``202`` with a ``task_id`` the client polls, or ``200`` with the cached quiz.

The handler is exercised directly with mocked collaborators (pattern from
``test_summative_answer_sanitization.py``) — no database or broker needed.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import status
from fastapi.responses import JSONResponse

from app.api.v1.quiz import generate_summative_assessment
from app.api.v1.schemas.quiz import (
    QuizContent,
    QuizQuestion,
    QuizResponse,
    SummativeAssessmentRequest,
)

MODULE_ID = "123e4567-e89b-12d3-a456-426614174000"


def _cached_quiz() -> QuizResponse:
    """A cached summative quiz whose questions carry the answer key."""
    return QuizResponse(
        id=uuid.uuid4(),
        module_id=uuid.UUID(MODULE_ID),
        unit_id="summative",
        language="fr",
        level=2,
        country_context="CI",
        content=QuizContent(
            title="Évaluation sommative",
            questions=[
                QuizQuestion(
                    id="q1",
                    question="Question q1 ?",
                    options=["A", "B", "C", "D"],
                    correct_answer=1,
                    explanation="Parce que q1.",
                    sources_cited=["Ref p.1"],
                    difficulty="medium",
                )
            ],
            passing_score=80.0,
        ),
        generated_at="2026-01-01T12:00:00",
        cached=True,
    )


def _request() -> SummativeAssessmentRequest:
    return SummativeAssessmentRequest(
        module_id=MODULE_ID, language="fr", country="CI", level=2, num_questions=20
    )


async def test_cache_hit_returns_200_without_answer_key():
    """A cached assessment is served immediately (200) with answers stripped (#2550)."""
    quiz_service = MagicMock()
    quiz_service.get_cached_quiz = AsyncMock(return_value=_cached_quiz())

    with patch("app.api.v1.quiz.generate_quiz_task") as task:
        resp = await generate_summative_assessment(
            _request(), quiz_service, MagicMock(), MagicMock()
        )

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == status.HTTP_200_OK
    body = resp.body.decode()
    assert '"correct_answer"' not in body
    assert '"explanation"' not in body
    # A cache hit must never dispatch a (paid) generation task.
    task.delay.assert_not_called()


async def test_cache_hit_country_fallback_dispatches_backfill():
    """Serving another country's cached assessment backfills the learner's own."""
    fallback = _cached_quiz()
    fallback.country_fallback = True
    quiz_service = MagicMock()
    quiz_service.get_cached_quiz = AsyncMock(return_value=fallback)

    with (
        patch(
            "app.api.v1.quiz.should_dispatch_country_backfill",
            new=AsyncMock(return_value=True),
        ),
        patch("app.tasks.content_generation.generate_country_content_task") as backfill,
    ):
        resp = await generate_summative_assessment(
            _request(), quiz_service, MagicMock(), MagicMock()
        )

    assert resp.status_code == status.HTTP_200_OK
    backfill.delay.assert_called_once()
    kwargs = backfill.delay.call_args.kwargs
    assert kwargs["unit_id"] == "summative"
    assert kwargs["content_type"] == "quiz"
    assert kwargs["country"] == "CI"


async def test_cache_miss_dispatches_task_and_returns_202():
    """An uncached assessment is generated in the background; the client polls."""
    quiz_service = MagicMock()
    quiz_service.get_cached_quiz = AsyncMock(return_value=None)

    dispatched = MagicMock()
    dispatched.id = "task-abc-123"

    with (
        patch("app.api.v1.quiz.generate_quiz_task") as task,
        patch("app.api.v1.quiz.mark_task_dispatched", new=AsyncMock()) as mark,
    ):
        task.delay.return_value = dispatched
        resp = await generate_summative_assessment(
            _request(), quiz_service, MagicMock(), MagicMock()
        )

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == status.HTTP_202_ACCEPTED
    payload = json.loads(resp.body)
    assert payload["status"] == "generating"
    assert payload["task_id"] == "task-abc-123"

    # Dispatched with the summative sentinel and the request's context.
    task.delay.assert_called_once_with(MODULE_ID, "summative", "fr", "CI", 2, 20)
    # The dispatch marker lets /content/status distinguish queued from lost.
    mark.assert_awaited_once_with("task-abc-123")
