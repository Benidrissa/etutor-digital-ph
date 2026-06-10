"""Tests for country fallback in POST /api/v1/quiz/generate.

Without fallback, a learner whose country has no generated quiz row gets an
exact-country cache miss → a fresh Celery generation re-dispatched on every
request → perpetual 202 (and the frontend then crashes on quiz.content.title).
This mirrors the lesson/case-study endpoints: serve any country's row
immediately with country_fallback=true and regenerate the country-specific
version in the background (#2480).

The endpoint function is invoked directly with a mocked session (two queries:
exact-country, then any-country fallback), so no DB fixture is required.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import quiz as quiz_module
from app.api.v1.schemas.quiz import QuizGenerationRequest


def _fake_cached_quiz(country_context: str):
    """A GeneratedContent-like row carrying a complete quiz payload."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        content={
            "unit_id": "1.5",
            "title": "Quiz régional",
            "description": "Instructions",
            "questions": [
                {
                    "id": "q1",
                    "question": "Question 1?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": 0,
                    "explanation": "Parce que A.",
                    "sources_cited": ["src-1"],
                    "difficulty": "medium",
                }
            ],
            "time_limit_minutes": None,
            "passing_score": 70.0,
        },
        language="fr",
        level=1,
        country_context=country_context,
        generated_at=datetime.now(tz=UTC),
    )


def _execute_returning(*rows):
    """async session.execute side_effect yielding one row per call."""
    results = []
    for row in rows:
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        results.append(result)
    return AsyncMock(side_effect=results)


def _request(country: str) -> QuizGenerationRequest:
    return QuizGenerationRequest(
        module_id=str(uuid.uuid4()),
        unit_id="1.5",
        language="fr",
        country=country,
        level=1,
        num_questions=10,
    )


@pytest.mark.asyncio
async def test_country_fallback_serves_other_country_and_dispatches():
    """Exact-country miss + any-country hit => 200, country_fallback=true,
    and a background country-specific generation is dispatched."""
    module_uuid = uuid.uuid4()
    fake_session = MagicMock()
    # 1st query (exact country "NG") misses; 2nd (fallback) hits "CI".
    fake_session.execute = _execute_returning(None, _fake_cached_quiz("CI"))

    fake_task = MagicMock()

    with (
        patch.object(quiz_module, "_check_subscription_or_first_unit", AsyncMock()),
        patch.object(quiz_module, "_resolve_module_uuid", AsyncMock(return_value=module_uuid)),
        patch(
            "app.domain.services._unit_resolution.resolve_module_unit_id",
            AsyncMock(return_value=uuid.uuid4()),
        ),
        patch("app.tasks.content_generation.generate_country_content_task", fake_task),
    ):
        response = await quiz_module.generate_quiz(
            request=_request("NG"),
            quiz_service=MagicMock(),
            session=fake_session,
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["country_fallback"] is True
    fake_task.delay.assert_called_once()
    assert fake_task.delay.call_args.kwargs["content_type"] == "quiz"
    assert fake_task.delay.call_args.kwargs["country"] == "NG"


@pytest.mark.asyncio
async def test_exact_country_hit_no_fallback_no_dispatch():
    """Exact-country hit => 200, country_fallback=false, no background regen."""
    module_uuid = uuid.uuid4()
    fake_session = MagicMock()
    # 1st query (exact country "CI") hits; fallback query never runs.
    fake_session.execute = _execute_returning(_fake_cached_quiz("CI"))

    fake_task = MagicMock()

    with (
        patch.object(quiz_module, "_check_subscription_or_first_unit", AsyncMock()),
        patch.object(quiz_module, "_resolve_module_uuid", AsyncMock(return_value=module_uuid)),
        patch(
            "app.domain.services._unit_resolution.resolve_module_unit_id",
            AsyncMock(return_value=uuid.uuid4()),
        ),
        patch("app.tasks.content_generation.generate_country_content_task", fake_task),
    ):
        response = await quiz_module.generate_quiz(
            request=_request("CI"),
            quiz_service=MagicMock(),
            session=fake_session,
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["country_fallback"] is False
    fake_task.delay.assert_not_called()
