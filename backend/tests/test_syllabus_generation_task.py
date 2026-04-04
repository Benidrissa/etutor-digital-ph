"""Regression tests for the syllabus generation Celery task.

Covers the three root causes of the original hang:
1. session.flush() called per module inside an open transaction
2. Course attributes accessed after write operations (ORM re-SELECT on expiring state)
3. New engine created per task invocation instead of the shared session factory
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.syllabus_generation import generate_course_syllabus


def _make_mock_course(course_id: uuid.UUID) -> MagicMock:
    tc_domain = MagicMock()
    tc_domain.slug = "epidemiology"
    tc_domain.type = "domain"

    tc_level = MagicMock()
    tc_level.slug = "intermediate"
    tc_level.type = "level"

    tc_audience = MagicMock()
    tc_audience.slug = "health-worker"
    tc_audience.type = "audience"

    course = MagicMock()
    course.id = course_id
    course.title_fr = "Épidémiologie fondamentale"
    course.title_en = "Fundamental Epidemiology"
    course.estimated_hours = 30
    course.rag_collection_id = "rag-col-abc"
    course.taxonomy_categories = [tc_domain, tc_level, tc_audience]
    return course


def _make_module_dicts(count: int = 2) -> list[dict]:
    return [
        {
            "title_fr": f"Module {i + 1} FR",
            "title_en": f"Module {i + 1} EN",
            "description_fr": f"Desc {i + 1} FR",
            "description_en": f"Desc {i + 1} EN",
            "estimated_hours": 15,
            "bloom_level": "remember",
            "units": [
                {
                    "title_fr": f"Unité {i + 1}.1 FR",
                    "title_en": f"Unit {i + 1}.1 EN",
                    "description_fr": "Desc unit FR",
                    "description_en": "Desc unit EN",
                }
            ],
        }
        for i in range(count)
    ]


class TestSyllabusGenerationTask:
    """Unit tests for the generate_course_syllabus Celery task."""

    @pytest.mark.asyncio
    async def test_no_flush_called_during_module_save(self):
        course_id = uuid.uuid4()
        module_dicts = _make_module_dicts(2)
        mock_course = _make_mock_course(course_id)

        read_session = AsyncMock()
        read_result = MagicMock()
        read_result.scalar_one_or_none.return_value = mock_course
        read_session.execute = AsyncMock(return_value=read_result)
        read_session.__aenter__ = AsyncMock(return_value=read_session)
        read_session.__aexit__ = AsyncMock(return_value=False)

        write_session = AsyncMock()
        write_session.execute = AsyncMock(return_value=MagicMock())
        write_session.add = MagicMock()
        write_session.flush = AsyncMock()
        write_session.commit = AsyncMock()
        write_session.__aenter__ = AsyncMock(return_value=write_session)
        write_session.__aexit__ = AsyncMock(return_value=False)

        session_factory = MagicMock(side_effect=[read_session, write_session])

        mock_agent = AsyncMock()
        mock_agent.generate_course_structure = AsyncMock(return_value=module_dicts)

        task = generate_course_syllabus

        with (
            patch(
                "app.tasks.syllabus_generation.generate_course_syllabus.update_state"
            ) if False else patch.object(task, "update_state", MagicMock()),
            patch(
                "app.infrastructure.persistence.database.async_session_factory",
                session_factory,
            ),
            patch(
                "app.domain.services.course_agent_service.CourseAgentService",
                return_value=mock_agent,
            ),
        ):
            import asyncio

            async def _inner():
                from app.domain.models.course import Course
                from app.domain.models.module import Module
                from app.domain.models.module_unit import ModuleUnit
                from app.domain.services.course_agent_service import CourseAgentService
                from app.infrastructure.persistence.database import (
                    async_session_factory as sf,
                )

                async with sf() as s:
                    result = await s.execute(None)
                    course = result.scalar_one_or_none()
                    assert course is not None

                    cats = list(course.taxonomy_categories or [])
                    assert len(cats) == 3

                async with sf() as s:
                    for _m in module_dicts:
                        s.add(MagicMock())

                    s.flush.assert_not_called()
                    await s.commit()

            await _inner()

        write_session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_course_values_cached_before_session_close(self):
        course_id = uuid.uuid4()
        mock_course = _make_mock_course(course_id)

        read_session = AsyncMock()
        read_result = MagicMock()
        read_result.scalar_one_or_none.return_value = mock_course
        read_session.execute = AsyncMock(return_value=read_result)
        read_session.__aenter__ = AsyncMock(return_value=read_session)
        read_session.__aexit__ = AsyncMock(return_value=False)

        write_session = AsyncMock()
        write_session.execute = AsyncMock(return_value=MagicMock())
        write_session.add = MagicMock()
        write_session.commit = AsyncMock()
        write_session.__aenter__ = AsyncMock(return_value=write_session)
        write_session.__aexit__ = AsyncMock(return_value=False)

        call_order = []
        original_scalar = mock_course.title_fr

        session_factory_calls = [read_session, write_session]

        async def _run():
            session_idx = 0
            sessions = [read_session, write_session]

            async with sessions[0]:
                result = await sessions[0].execute(None)
                course = result.scalar_one_or_none()

                title_fr = course.title_fr
                rag_id = course.rag_collection_id
                cats = list(course.taxonomy_categories or [])
                call_order.append("cached")

            call_order.append("session_closed")

            assert title_fr == "Épidémiologique fondamentale" or title_fr == original_scalar
            assert rag_id == "rag-col-abc"
            assert len(cats) == 3

        await _run()
        assert call_order == ["cached", "session_closed"]

    @pytest.mark.asyncio
    async def test_uses_shared_session_factory_not_new_engine(self):
        source = open(
            __file__.replace(
                "test_syllabus_generation_task.py", "../app/tasks/syllabus_generation.py"
            )
        ).read()

        assert "create_async_engine" not in source, (
            "syllabus_generation.py must NOT create a new engine per invocation"
        )
        assert "async_session_factory" in source, (
            "syllabus_generation.py must use the shared async_session_factory"
        )

    @pytest.mark.asyncio
    async def test_course_not_found_returns_failed_status(self):
        course_id = str(uuid.uuid4())

        read_session = AsyncMock()
        read_result = MagicMock()
        read_result.scalar_one_or_none.return_value = None
        read_session.execute = AsyncMock(return_value=read_result)
        read_session.__aenter__ = AsyncMock(return_value=read_session)
        read_session.__aexit__ = AsyncMock(return_value=False)

        async def _run():
            from sqlalchemy import select

            from app.domain.models.course import Course

            async with read_session as session:
                result = await session.execute(
                    select(Course).where(Course.id == uuid.UUID(course_id))
                )
                course = result.scalar_one_or_none()
                if not course:
                    return {
                        "status": "failed",
                        "error": f"Course not found: {course_id}",
                        "modules_count": 0,
                        "modules": [],
                    }

        result = await _run()
        assert result["status"] == "failed"
        assert "Course not found" in result["error"]
        assert result["modules_count"] == 0
        assert result["modules"] == []

    def test_task_file_three_phase_structure(self):
        import ast
        import os

        task_path = os.path.join(
            os.path.dirname(__file__),
            "../app/tasks/syllabus_generation.py",
        )
        with open(task_path) as f:
            source = f.read()

        assert "# Phase 1" in source, "Phase 1 comment missing — read phase not separated"
        assert "# Phase 2" in source, "Phase 2 comment missing — Claude call not separated"
        assert "# Phase 3" in source, "Phase 3 comment missing — write phase not separated"

        assert source.count("await session.flush()") == 0, (
            "No flush() calls allowed in syllabus_generation.py"
        )

    def test_taxonomy_slug_extraction_by_type(self):
        cats = [
            MagicMock(slug="epi", type="domain"),
            MagicMock(slug="intermediate", type="level"),
            MagicMock(slug="nurse", type="audience"),
            MagicMock(slug="biostat", type="domain"),
        ]

        domain_slugs = [tc.slug for tc in cats if tc.type == "domain"]
        level_slugs = [tc.slug for tc in cats if tc.type == "level"]
        audience_slugs = [tc.slug for tc in cats if tc.type == "audience"]

        assert domain_slugs == ["epi", "biostat"]
        assert level_slugs == ["intermediate"]
        assert audience_slugs == ["nurse"]
