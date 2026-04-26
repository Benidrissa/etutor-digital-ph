"""Unit tests for the FK-based generated_content ↔ module_units join.

Pins down the contract introduced by issue #2007 / migration 084:
- ``resolve_module_unit_id`` returns the correct UUID for unit_numbers,
  ``None`` for the ``"summative"`` sentinel, and ``None`` for unknown
  unit_numbers.
- ``_get_cached_lesson`` resolves the unit FK FIRST and then filters
  ``generated_content`` by ``module_unit_id`` rather than the JSON
  ``content->>'unit_id'``.
- The SQLAlchemy model declares ``ON DELETE CASCADE`` on the FK so that
  deleting a unit purges its cached content.

Cascade *behavior* is left for migration smoke testing on staging — these
unit tests verify the schema declaration, which is what guarantees the
behavior at the DB level.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.content import GeneratedContent
from app.domain.models.module_unit import ModuleUnit
from app.domain.services._unit_resolution import (
    SUMMATIVE_SENTINEL,
    resolve_module_unit_id,
)
from app.domain.services.lesson_service import LessonGenerationService


def _resolve_result(unit_uuid: uuid.UUID | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = unit_uuid
    return result


def _cache_result(cached) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = cached
    result.scalars.return_value = scalars
    return result


class TestResolveModuleUnitId:
    @pytest.mark.asyncio
    async def test_returns_uuid_for_known_unit(self):
        expected_uuid = uuid.uuid4()
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=_resolve_result(expected_uuid))

        resolved = await resolve_module_unit_id(session, uuid.uuid4(), "1.2")
        assert resolved == expected_uuid

    @pytest.mark.asyncio
    async def test_returns_none_for_summative_sentinel(self):
        """Summative quizzes are module-scoped (module_unit_id IS NULL).
        The helper short-circuits without hitting the DB."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()

        resolved = await resolve_module_unit_id(
            session, uuid.uuid4(), SUMMATIVE_SENTINEL
        )
        assert resolved is None
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_unit_id(self):
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()

        resolved = await resolve_module_unit_id(session, uuid.uuid4(), "")
        assert resolved is None
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_unit(self):
        """Unknown unit_number → no match → None. Caller decides what to do
        (typically 404)."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=_resolve_result(None))

        resolved = await resolve_module_unit_id(session, uuid.uuid4(), "9.9")
        assert resolved is None


class TestGetCachedLessonUsesFkLookup:
    """``_get_cached_lesson`` must resolve the unit_uuid first and then filter
    ``generated_content`` by ``module_unit_id``. This is the read-path half
    of the fix — guarantees a renamed unit's cached content stays bound to
    the same row instead of drifting to whatever JSON ``unit_id`` happens
    to match (#2007)."""

    @pytest.mark.asyncio
    async def test_no_cache_lookup_when_unit_does_not_exist(self):
        """If the unit_number doesn't resolve to a module_units row, the
        cache lookup short-circuits — no second query, no risk of matching
        a different unit's content."""
        service = LessonGenerationService(
            claude_service=AsyncMock(spec=ClaudeService),
            semantic_retriever=AsyncMock(spec=SemanticRetriever),
        )
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=[_resolve_result(None)])

        result, fallback = await service._get_cached_lesson(
            uuid.uuid4(), "9.9", "fr", "CI", 1, session
        )

        assert result is None
        assert fallback is False
        # Exactly one execute() call: the resolve query. No cache lookup.
        assert session.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_cache_query_filters_by_module_unit_id(self):
        """When the unit resolves, the cache query must be parameterized
        by ``GeneratedContent.module_unit_id == resolved_uuid`` — not by
        the legacy JSON expression."""
        service = LessonGenerationService(
            claude_service=AsyncMock(spec=ClaudeService),
            semantic_retriever=AsyncMock(spec=SemanticRetriever),
        )
        unit_uuid = uuid.uuid4()
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(
            side_effect=[_resolve_result(unit_uuid), _cache_result(None), _cache_result(None)]
        )

        await service._get_cached_lesson(
            uuid.uuid4(), "1.2", "fr", "CI", 1, session
        )

        # Inspect the second call (the primary cache query) and assert its
        # WHERE clause references the FK column. Render to SQL and grep.
        primary_query = session.execute.await_args_list[1].args[0]
        compiled = str(primary_query.compile(compile_kwargs={"literal_binds": False}))
        assert "module_unit_id" in compiled
        assert "content -> 'unit_id'" not in compiled


class TestSchemaDeclaresCascadeOnUnitDelete:
    """The whole point of #2007 is that deleting a unit purges its cached
    content. The cascade is encoded in the FK definition; verify it.
    Actual cascade *behavior* is verified by manual smoke testing on
    staging after migration 084 runs."""

    def test_module_unit_id_fk_has_on_delete_cascade(self):
        fk_cols = [
            c
            for c in GeneratedContent.__table__.columns
            if c.name == "module_unit_id"
        ]
        assert len(fk_cols) == 1, "module_unit_id column must exist on generated_content"

        col = fk_cols[0]
        assert col.nullable, "module_unit_id must be nullable for module-scoped content"

        fks = list(col.foreign_keys)
        assert len(fks) == 1, "module_unit_id must have exactly one FK"
        fk = fks[0]
        assert fk.column.table is ModuleUnit.__table__
        assert fk.ondelete == "CASCADE", (
            "FK must declare ON DELETE CASCADE so removing a unit "
            "purges its cached generated_content rows (#2007)"
        )
