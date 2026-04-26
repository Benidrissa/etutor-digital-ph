"""Integration tests for the FK-based generated_content ↔ module_units join.

These tests pin down the contract introduced by issue #2007 / migration 084:
the link from a cached lesson/quiz/case row to its unit is now the
``module_unit_id`` foreign key, not the JSON ``content->>'unit_id'`` string.

Concretely, we verify:
1. ``resolve_module_unit_id`` returns the correct UUID for an existing
   unit_number, ``None`` for the ``"summative"`` sentinel, and ``None`` for
   unknown unit_numbers.
2. ``_get_cached_lesson`` joins by ``module_unit_id`` — renaming the unit's
   title without touching ``generated_content`` still returns the same
   cached row (the FK is the source of truth, not the JSON).
3. Deleting a ``module_units`` row cascade-deletes every
   ``generated_content`` row that pointed at it via ``module_unit_id``.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.services._unit_resolution import (
    SUMMATIVE_SENTINEL,
    resolve_module_unit_id,
)
from app.domain.services.lesson_service import LessonGenerationService


@pytest.fixture
async def seeded_module(db_session) -> Module:
    """Insert a Module with three units; return the persisted Module."""
    module = Module(
        id=uuid.uuid4(),
        module_number=1,
        level=1,
        title_fr="Module Test",
        title_en="Module Test",
        description_fr="",
        description_en="",
        bloom_level="remember",
    )
    db_session.add(module)

    db_session.add_all(
        [
            ModuleUnit(
                id=uuid.uuid4(),
                module_id=module.id,
                unit_number="1.1",
                title_fr="Sujet A",
                title_en="Topic A",
                description_fr="Description A",
                description_en="Description A",
                order_index=0,
                unit_type="lesson",
            ),
            ModuleUnit(
                id=uuid.uuid4(),
                module_id=module.id,
                unit_number="1.2",
                title_fr="Sujet B",
                title_en="Topic B",
                description_fr="Description B",
                description_en="Description B",
                order_index=1,
                unit_type="lesson",
            ),
            ModuleUnit(
                id=uuid.uuid4(),
                module_id=module.id,
                unit_number="1.3",
                title_fr="Sujet C",
                title_en="Topic C",
                description_fr="Description C",
                description_en="Description C",
                order_index=2,
                unit_type="lesson",
            ),
        ]
    )
    await db_session.commit()
    return module


class TestResolveModuleUnitId:
    @pytest.mark.asyncio
    async def test_returns_uuid_for_known_unit(self, db_session, seeded_module):
        unit = (
            await db_session.execute(
                select(ModuleUnit).where(
                    ModuleUnit.module_id == seeded_module.id,
                    ModuleUnit.unit_number == "1.2",
                )
            )
        ).scalar_one()

        resolved = await resolve_module_unit_id(db_session, seeded_module.id, "1.2")
        assert resolved == unit.id

    @pytest.mark.asyncio
    async def test_returns_none_for_summative_sentinel(self, db_session, seeded_module):
        resolved = await resolve_module_unit_id(db_session, seeded_module.id, SUMMATIVE_SENTINEL)
        assert resolved is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_unit(self, db_session, seeded_module):
        resolved = await resolve_module_unit_id(db_session, seeded_module.id, "9.9")
        assert resolved is None


class TestStaleCacheDoesNotDriftWhenUnitTitleChanges:
    """The whole point of issue #2007: a unit's title can change in
    ``module_units`` but the cached lesson stays bound by FK to the same
    row, so look-ups don't silently match a different unit's content."""

    @pytest.mark.asyncio
    async def test_lookup_follows_fk_after_title_rename(self, db_session, seeded_module):
        unit_b = (
            await db_session.execute(
                select(ModuleUnit).where(
                    ModuleUnit.module_id == seeded_module.id,
                    ModuleUnit.unit_number == "1.2",
                )
            )
        ).scalar_one()

        cached = GeneratedContent(
            id=uuid.uuid4(),
            module_id=seeded_module.id,
            module_unit_id=unit_b.id,
            content_type="lesson",
            language="fr",
            level=1,
            country_context="CI",
            content={
                "introduction": "About Topic B specifically",
                "concepts": ["B1", "B2"],
                "aof_example": "",
                "synthesis": "",
                "key_points": [],
                "sources_cited": [],
                "unit_id": "1.2",
            },
            sources_cited=[],
            validated=False,
        )
        db_session.add(cached)
        await db_session.commit()

        # Rename the unit's title without touching generated_content.
        unit_b.title_fr = "Sujet B — RENAMED"
        await db_session.commit()

        service = LessonGenerationService(
            claude_service=AsyncMock(spec=ClaudeService),
            semantic_retriever=AsyncMock(spec=SemanticRetriever),
        )
        result, _ = await service._get_cached_lesson(
            seeded_module.id, "1.2", "fr", "CI", 1, db_session
        )

        assert result is not None
        assert result.id == cached.id
        assert "Topic B" in result.content.introduction or "B" in result.content.introduction


class TestUnitDeleteCascadesToGeneratedContent:
    @pytest.mark.asyncio
    async def test_deleting_unit_purges_its_cached_content(self, db_session, seeded_module):
        unit_c = (
            await db_session.execute(
                select(ModuleUnit).where(
                    ModuleUnit.module_id == seeded_module.id,
                    ModuleUnit.unit_number == "1.3",
                )
            )
        ).scalar_one()

        cached_id = uuid.uuid4()
        db_session.add(
            GeneratedContent(
                id=cached_id,
                module_id=seeded_module.id,
                module_unit_id=unit_c.id,
                content_type="lesson",
                language="fr",
                level=1,
                country_context="CI",
                content={
                    "introduction": "C",
                    "concepts": [],
                    "aof_example": "",
                    "synthesis": "",
                    "key_points": [],
                    "sources_cited": [],
                    "unit_id": "1.3",
                },
                sources_cited=[],
                validated=False,
            )
        )
        await db_session.commit()

        await db_session.delete(unit_c)
        await db_session.commit()

        leftover = (
            await db_session.execute(
                select(GeneratedContent).where(GeneratedContent.id == cached_id)
            )
        ).scalar_one_or_none()
        assert leftover is None, "ON DELETE CASCADE should have purged the row"
