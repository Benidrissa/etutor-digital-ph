"""Tests for the force_regenerate cache overwrite (#2561).

The lesson Refresh button was a no-op: the endpoint dropped the
force_regenerate flag when dispatching the Celery task, and even when the
service regenerated, _cache_lesson_content was INSERT-only — the unique index
idx_unique_content_per_module_unit collided and the IntegrityError was
swallowed, so the stale row always survived. Regeneration must now update the
existing row in place (bumping content_revision) instead.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.content import LessonContent, LessonResponse
from app.domain.services.lesson_service import (
    LessonGenerationService,
    update_cached_content_in_place,
)


@pytest.fixture
def lesson_service():
    return LessonGenerationService(
        claude_service=AsyncMock(spec=ClaudeService),
        semantic_retriever=AsyncMock(spec=SemanticRetriever),
    )


def _make_session(existing_row):
    """AsyncMock session whose execute() resolves scalars().first() to existing_row."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing_row
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    return session


def _existing_row(revision=1, manually_edited=False):
    row = MagicMock()
    row.id = uuid.uuid4()
    row.content_revision = revision
    row.is_manually_edited = manually_edited
    return row


def _lesson_response():
    return LessonResponse(
        module_id=uuid.uuid4(),
        unit_id="1.3",
        language="fr",
        level=1,
        country_context="BF",
        content=LessonContent(
            introduction="Intro",
            concepts=["Concept A"],
            aof_example="Exemple",
            synthesis="Synthèse",
            key_points=["Point 1"],
            sources_cited=["Livre, p.6"],
        ),
        generated_at="2026-07-07T00:00:00",
        cached=False,
        source_image_refs=[],
    )


@pytest.mark.asyncio
async def test_update_in_place_replaces_content_and_bumps_revision():
    row = _existing_row(revision=3)
    session = _make_session(row)
    new_content = {"introduction": "Nouvelle intro", "concepts": ["C"], "unit_id": "1.3"}

    updated_id = await update_cached_content_in_place(
        session,
        module_unit_uuid=uuid.uuid4(),
        content_type="lesson",
        language="fr",
        level=1,
        country_context="BF",
        content=new_content,
        sources_cited=["Livre, p.6"],
    )

    assert updated_id == row.id
    assert row.content == new_content
    assert row.content_revision == 4
    assert row.validated is False


@pytest.mark.asyncio
async def test_update_in_place_skips_manually_edited_rows():
    session = _make_session(_existing_row(manually_edited=True))

    updated_id = await update_cached_content_in_place(
        session,
        module_unit_uuid=uuid.uuid4(),
        content_type="lesson",
        language="fr",
        level=1,
        country_context="BF",
        content={},
        sources_cited=None,
    )

    assert updated_id is None


@pytest.mark.asyncio
async def test_update_in_place_returns_none_without_unit_fk():
    session = _make_session(None)

    updated_id = await update_cached_content_in_place(
        session,
        module_unit_uuid=None,
        content_type="lesson",
        language="fr",
        level=1,
        country_context="BF",
        content={},
        sources_cited=None,
    )

    assert updated_id is None
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_lesson_content_updates_existing_row(lesson_service, monkeypatch):
    """When a cached row exists, _cache_lesson_content must UPDATE it (no
    INSERT) and point the response id at the surviving row."""
    row = _existing_row()
    session = _make_session(row)
    lesson_response = _lesson_response()

    async def _resolve(_session, _module_id, _unit_id):
        return uuid.uuid4()

    monkeypatch.setattr("app.domain.services._unit_resolution.resolve_module_unit_id", _resolve)

    await lesson_service._cache_lesson_content(lesson_response, session)

    session.add.assert_not_called()
    session.commit.assert_awaited()
    assert lesson_response.id == row.id
    assert row.content["introduction"] == "Intro"
    assert row.content["unit_id"] == "1.3"
    assert row.content_revision == 2


@pytest.mark.asyncio
async def test_cache_lesson_content_inserts_when_no_existing_row(lesson_service, monkeypatch):
    session = _make_session(None)
    lesson_response = _lesson_response()

    async def _resolve(_session, _module_id, _unit_id):
        return uuid.uuid4()

    monkeypatch.setattr("app.domain.services._unit_resolution.resolve_module_unit_id", _resolve)

    await lesson_service._cache_lesson_content(lesson_response, session)

    session.add.assert_called_once()
