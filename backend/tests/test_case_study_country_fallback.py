"""Tests for country fallback in GET /api/v1/content/cases/{module_id}/{unit_id}.

Without fallback, a learner whose country has no generated case-study row gets
an exact-country cache miss → a fresh 3-min Celery generation re-dispatched on
every request → perpetual 202. This mirrors the lesson endpoint: serve any
country's row immediately with country_fallback=true and regenerate the
country-specific version in the background (#2474).

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

from app.api.v1 import content as content_module


def _fake_cached_case(country_context: str):
    """A GeneratedContent-like row carrying a complete case-study payload."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        content={
            "unit_id": "1.4",
            "aof_context": "Contexte régional",
            "real_data": "Données réelles",
            "guided_questions": ["Q1", "Q2"],
            "annotated_correction": "Correction",
            "sources_cited": ["src-1"],
        },
        language="fr",
        level=1,
        country_context=country_context,
        generated_at=datetime.now(tz=UTC),
    )


def _execute_returning(*rows):
    """Build an async session.execute side_effect yielding one row per call.

    Each call returns a result whose .scalars().first() is the next row.
    """
    results = []
    for row in rows:
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        results.append(result)
    return AsyncMock(side_effect=results)


@pytest.mark.asyncio
async def test_country_fallback_serves_other_country_and_dispatches():
    """Exact-country miss + any-country hit => 200, country_fallback=true,
    and a background country-specific generation is dispatched."""
    resolved_module_id = uuid.uuid4()
    fake_session = MagicMock()
    # 1st query (exact country "NG") misses; 2nd (fallback, any country) hits "CI".
    fake_session.execute = _execute_returning(None, _fake_cached_case("CI"))

    fake_task = MagicMock()

    with (
        patch.object(
            content_module, "_resolve_module_id", AsyncMock(return_value=resolved_module_id)
        ),
        patch(
            "app.domain.services._unit_resolution.resolve_module_unit_id",
            AsyncMock(return_value=uuid.uuid4()),
        ),
        patch.object(
            content_module,
            "rewrite_uuid_citations_for_module",
            AsyncMock(return_value=["src-1"]),
        ),
        patch.object(content_module, "ProgressService", MagicMock()),
        patch.object(content_module, "_dispatch_content_prefetch", MagicMock()),
        patch("app.tasks.content_generation.generate_country_content_task", fake_task),
    ):
        response = await content_module.get_or_generate_case_study(
            module_id=str(resolved_module_id),
            unit_id="1.4",
            language="fr",
            level=1,
            country="NG",
            force_regenerate=False,
            case_study_service=MagicMock(),
            session=fake_session,
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["country_fallback"] is True
    # background regen for the learner's actual country was dispatched
    fake_task.delay.assert_called_once()
    assert fake_task.delay.call_args.kwargs["content_type"] == "case"
    assert fake_task.delay.call_args.kwargs["country"] == "NG"


@pytest.mark.asyncio
async def test_exact_country_hit_no_fallback_no_dispatch():
    """Exact-country hit => 200, country_fallback=false, no background regen."""
    resolved_module_id = uuid.uuid4()
    fake_session = MagicMock()
    # 1st query (exact country "CI") hits; fallback query is never run.
    fake_session.execute = _execute_returning(_fake_cached_case("CI"))

    fake_task = MagicMock()

    with (
        patch.object(
            content_module, "_resolve_module_id", AsyncMock(return_value=resolved_module_id)
        ),
        patch(
            "app.domain.services._unit_resolution.resolve_module_unit_id",
            AsyncMock(return_value=uuid.uuid4()),
        ),
        patch.object(
            content_module,
            "rewrite_uuid_citations_for_module",
            AsyncMock(return_value=["src-1"]),
        ),
        patch.object(content_module, "ProgressService", MagicMock()),
        patch.object(content_module, "_dispatch_content_prefetch", MagicMock()),
        patch("app.tasks.content_generation.generate_country_content_task", fake_task),
    ):
        response = await content_module.get_or_generate_case_study(
            module_id=str(resolved_module_id),
            unit_id="1.4",
            language="fr",
            level=1,
            country="CI",
            force_regenerate=False,
            case_study_service=MagicMock(),
            session=fake_session,
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["country_fallback"] is False
    fake_task.delay.assert_not_called()
