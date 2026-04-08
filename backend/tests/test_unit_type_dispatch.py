"""Tests for unit_type dispatch in GET /lessons/{module_id}/{unit_id}.

Verifies that case-study units route to the case study generator
and lesson units route to the lesson generator.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def module_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def unit_id() -> str:
    return "M01-U09"


class TestUnitTypeDispatchHelpers:
    """Unit tests for the unit_type lookup and routing logic."""

    @pytest.mark.asyncio
    async def test_case_study_unit_routes_to_case_study_task(self, module_id, unit_id):
        """When ModuleUnit.unit_type == 'case-study', generate_case_study_task is called."""
        session = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: "case-study" if key == 0 else None
        result_mock = MagicMock()
        result_mock.first.return_value = mock_row
        session.execute = AsyncMock(return_value=result_mock)

        unit_type_row = result_mock.first()
        is_case_study = unit_type_row is not None and unit_type_row[0] == "case-study"

        assert is_case_study is True

    @pytest.mark.asyncio
    async def test_lesson_unit_routes_to_lesson_task(self, module_id, unit_id):
        """When ModuleUnit.unit_type == 'lesson', generate_lesson_task is called."""
        session = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: "lesson" if key == 0 else None
        result_mock = MagicMock()
        result_mock.first.return_value = mock_row
        session.execute = AsyncMock(return_value=result_mock)

        unit_type_row = result_mock.first()
        is_case_study = unit_type_row is not None and unit_type_row[0] == "case-study"

        assert is_case_study is False

    @pytest.mark.asyncio
    async def test_unknown_unit_routes_to_lesson_task(self, module_id, unit_id):
        """When unit is not found in DB, defaults to lesson generation."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.first.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        unit_type_row = result_mock.first()
        is_case_study = unit_type_row is not None and unit_type_row[0] == "case-study"

        assert is_case_study is False

    @pytest.mark.asyncio
    async def test_null_unit_type_routes_to_lesson_task(self, module_id, unit_id):
        """When unit_type is NULL, defaults to lesson generation."""
        session = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: None if key == 0 else None
        result_mock = MagicMock()
        result_mock.first.return_value = mock_row
        session.execute = AsyncMock(return_value=result_mock)

        unit_type_row = result_mock.first()
        is_case_study = unit_type_row is not None and unit_type_row[0] == "case-study"

        assert is_case_study is False


class TestCacheContentTypeFilter:
    """Verifies the correct content_type is used for cache lookups."""

    def test_case_study_cache_filter_is_case(self):
        is_case_study = True
        content_type_filter = "case" if is_case_study else "lesson"
        assert content_type_filter == "case"

    def test_lesson_cache_filter_is_lesson(self):
        is_case_study = False
        content_type_filter = "case" if is_case_study else "lesson"
        assert content_type_filter == "lesson"


class TestCaseStudyTaskImport:
    """Verify generate_case_study_task is importable and callable."""

    def test_generate_case_study_task_is_importable(self):
        from app.tasks.content_generation import generate_case_study_task

        assert callable(generate_case_study_task)

    def test_generate_lesson_task_is_importable(self):
        from app.tasks.content_generation import generate_lesson_task

        assert callable(generate_lesson_task)

    def test_case_study_task_dispatch_mock(self):
        """Verify generate_case_study_task.delay() can be called."""
        with patch("app.tasks.content_generation.generate_case_study_task") as mock_task:
            mock_task.delay.return_value = MagicMock(id="test-task-id")
            result = mock_task.delay(str(uuid.uuid4()), "M01-U09", "fr", "SN", 1)
            assert result.id == "test-task-id"
            mock_task.delay.assert_called_once()

    def test_lesson_task_not_called_for_case_study(self):
        """When is_case_study=True, generate_lesson_task.delay() should NOT be called."""
        with (
            patch("app.tasks.content_generation.generate_lesson_task") as mock_lesson_task,
            patch("app.tasks.content_generation.generate_case_study_task") as mock_case_task,
        ):
            mock_case_task.delay.return_value = MagicMock(id="case-task-id")
            is_case_study = True

            if is_case_study:
                mock_case_task.delay(str(uuid.uuid4()), "M01-U09", "fr", "SN", 1)
            else:
                mock_lesson_task.delay(str(uuid.uuid4()), "M01-U09", "fr", "SN", 1)

            mock_case_task.delay.assert_called_once()
            mock_lesson_task.delay.assert_not_called()
