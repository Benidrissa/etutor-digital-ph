"""Backfill-task resilience + endpoint canonicalization (#2581).

Two guarantees:
1. ``generate_country_content_task`` carries retry config so a transient
   failure (e.g. an upstream 429/quota blip) is re-queued instead of silently
   dropped — otherwise the learner's own-country row is never produced and they
   are stranded on the fallback country forever.
2. A slug country (``burkina-faso``) sent to the content endpoint is
   canonicalized to its ISO code (``BF``) before the fallback lookup and the
   background dispatch, so slug and ISO can never fork into duplicate cache rows.
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
from app.tasks.content_generation import generate_country_content_task


def test_backfill_task_has_retry_config():
    """Without this, a quota blip drops the job and the CI row never appears."""
    assert generate_country_content_task.autoretry_for == (Exception,)
    assert generate_country_content_task.retry_kwargs["max_retries"] >= 1
    assert generate_country_content_task.max_retries >= 1


def _fake_cached_quiz(country_context: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        content={
            "unit_id": "1.5",
            "title": "Quiz",
            "description": "d",
            "questions": [
                {
                    "id": "q1",
                    "question": "Q1?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": 0,
                    "explanation": "A.",
                    "sources_cited": ["s"],
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
    results = []
    for row in rows:
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        results.append(result)
    return AsyncMock(side_effect=results)


@pytest.mark.asyncio
async def test_slug_country_is_canonicalized_before_dispatch():
    """Request country 'burkina-faso' must dispatch backfill with ISO 'BF'."""
    module_uuid = uuid.uuid4()
    fake_session = MagicMock()
    # exact-country ('BF') miss, then any-country fallback hit ('CI').
    fake_session.execute = _execute_returning(None, _fake_cached_quiz("CI"))
    fake_task = MagicMock()

    with (
        patch.object(quiz_module, "_check_subscription_or_first_unit", AsyncMock()),
        patch.object(quiz_module, "_resolve_module_uuid", AsyncMock(return_value=module_uuid)),
        patch(
            "app.domain.services._unit_resolution.resolve_module_unit_id",
            AsyncMock(return_value=uuid.uuid4()),
        ),
        patch.object(quiz_module, "should_dispatch_country_backfill", AsyncMock(return_value=True)),
        patch("app.tasks.content_generation.generate_country_content_task", fake_task),
    ):
        response = await quiz_module.generate_quiz(
            request=QuizGenerationRequest(
                module_id=str(uuid.uuid4()),
                unit_id="1.5",
                language="fr",
                country="burkina-faso",
                level=1,
                num_questions=10,
            ),
            quiz_service=MagicMock(),
            session=fake_session,
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["country_fallback"] is True
    fake_task.delay.assert_called_once()
    assert fake_task.delay.call_args.kwargs["country"] == "BF"
