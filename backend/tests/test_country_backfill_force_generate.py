"""generate_country_content_task must FORCE-generate the target country (#2591).

Before the fix, the task confirmed the exact-country row was absent and then
called ``get_or_generate_lesson(country=...)`` WITHOUT ``force_regenerate``. The
service's cache read returned another country's fallback row and re-dispatched
the task — an infinite loop that never generated the target country (the flood
observed on staging; #2581's self-heal could never heal because the row was
never created).

This test invokes the task body with the DB/engine/service mocked and asserts
the service is called with ``force_regenerate=True`` (so the fallback path is
bypassed and the exact country is generated).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.tasks import content_generation as cg


def _no_existing_row_session():
    """A mock async session whose queries return no existing content row."""
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None  # no exact-country row
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    return session


def _session_factory(session):
    @asynccontextmanager
    async def _factory():
        yield session

    return lambda: _factory()


def test_backfill_lesson_forces_generation_of_target_country():
    module_id = str(uuid.uuid4())
    session = _no_existing_row_session()

    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    generated = SimpleNamespace(id=uuid.uuid4(), content={"introduction": "x"})
    lesson_service = MagicMock()
    lesson_service.get_or_generate_lesson = AsyncMock(return_value=generated)

    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=fake_engine),
        patch(
            "sqlalchemy.ext.asyncio.async_sessionmaker",
            return_value=_session_factory(session),
        ),
        patch(
            "app.domain.services._unit_resolution.resolve_module_unit_id",
            AsyncMock(return_value=uuid.uuid4()),
        ),
        patch("app.ai.rag.embeddings.EmbeddingService", MagicMock()),
        patch("app.ai.rag.retriever.SemanticRetriever", MagicMock()),
        patch("app.ai.claude_service.ClaudeService", MagicMock()),
        patch(
            "app.domain.services.lesson_service.LessonGenerationService",
            return_value=lesson_service,
        ),
        patch("app.domain.services.lesson_service.extract_lesson_text", return_value="body"),
        patch.object(cg, "generate_lesson_audio", MagicMock()),
    ):
        result = cg.generate_country_content_task.apply(
            kwargs={
                "module_id": module_id,
                "unit_id": "1.3",
                "content_type": "lesson",
                "language": "fr",
                "level": 1,
                "country": "CI",
                "user_id": "",
            }
        ).get()

    assert result["status"] == "complete"
    lesson_service.get_or_generate_lesson.assert_awaited_once()
    kwargs = lesson_service.get_or_generate_lesson.await_args.kwargs
    assert kwargs["force_regenerate"] is True
    assert kwargs["country"] == "CI"
