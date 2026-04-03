"""Tests for the content reviewer service."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.services.content_reviewer import (
    ContentReviewerService,
    IssueType,
)


def make_module(
    estimated_hours: int = 3,
    books_sources: dict | None = None,
) -> Module:
    module = Module(
        id=uuid.uuid4(),
        module_number=1,
        level=1,
        title_fr="Test module",
        title_en="Test module",
        estimated_hours=estimated_hours,
        books_sources=books_sources,
    )
    return module


def make_unit(
    order_index: int,
    unit_number: str,
    estimated_minutes: int = 45,
    title_fr: str = "",
) -> ModuleUnit:
    return ModuleUnit(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_number=unit_number,
        title_fr=title_fr or f"Unit {unit_number}",
        title_en=f"Unit {unit_number}",
        estimated_minutes=estimated_minutes,
        order_index=order_index,
    )


def _make_service_with_module(module: Module, units: list[ModuleUnit]) -> ContentReviewerService:
    module.units = units
    db = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = module
    db.execute = AsyncMock(return_value=mock_result)

    return ContentReviewerService(db)


class TestHoursConsistency:
    async def test_passes_when_hours_match(self):
        units = [
            make_unit(1, "1.1", 45),
            make_unit(2, "1.2", 45),
            make_unit(3, "1.3", 45),
            make_unit(4, "1.Q", 20),
            make_unit(5, "1.C", 30),
        ]
        total_minutes = sum(u.estimated_minutes for u in units)
        total_hours = total_minutes / 60
        module = make_module(estimated_hours=round(total_hours), books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        hour_issues = [i for i in result.issues if i.issue_type == IssueType.MODULE_HOURS_MISMATCH]
        assert len(hour_issues) == 0

    async def test_flags_when_hours_mismatch(self):
        units = [
            make_unit(1, "1.1", 45),
            make_unit(2, "1.2", 45),
            make_unit(3, "1.3", 45),
            make_unit(4, "1.Q", 20),
            make_unit(5, "1.C", 30),
        ]
        module = make_module(estimated_hours=20, books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        hour_issues = [i for i in result.issues if i.issue_type == IssueType.MODULE_HOURS_MISMATCH]
        assert len(hour_issues) == 1
        assert hour_issues[0].severity == "error"
        assert "20h" in hour_issues[0].message

    async def test_passes_within_margin(self):
        units = [
            make_unit(1, "1.1", 60),
            make_unit(2, "1.2", 60),
            make_unit(3, "1.3", 60),
            make_unit(4, "1.Q", 30),
            make_unit(5, "1.C", 30),
        ]
        module = make_module(estimated_hours=4, books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        hour_issues = [i for i in result.issues if i.issue_type == IssueType.MODULE_HOURS_MISMATCH]
        assert len(hour_issues) == 0


class TestUnitNumbering:
    async def test_passes_when_sequential(self):
        units = [make_unit(i, f"1.{i}") for i in range(1, 6)]
        module = make_module(estimated_hours=4, books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        num_issues = [i for i in result.issues if i.issue_type == IssueType.UNIT_NUMBERING_GAP]
        assert len(num_issues) == 0

    async def test_flags_when_starts_at_zero(self):
        units = [make_unit(i, f"1.{i + 1}") for i in range(5)]
        module = make_module(estimated_hours=4, books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        num_issues = [i for i in result.issues if i.issue_type == IssueType.UNIT_NUMBERING_GAP]
        assert len(num_issues) == 1

    async def test_flags_when_gap_in_numbering(self):
        units = [make_unit(1, "1.1"), make_unit(3, "1.3"), make_unit(4, "1.4")]
        module = make_module(estimated_hours=4, books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        num_issues = [i for i in result.issues if i.issue_type == IssueType.UNIT_NUMBERING_GAP]
        assert len(num_issues) == 1


class TestDuplicateTitles:
    async def test_flags_duplicate_titles(self):
        units = [
            make_unit(1, "1.1", title_fr="Introduction à la santé publique"),
            make_unit(2, "1.2", title_fr="Introduction à la santé publique"),
            make_unit(3, "1.3", title_fr="Autre sujet"),
        ]
        module = make_module(books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        dup_issues = [i for i in result.issues if i.issue_type == IssueType.DUPLICATE_UNIT_CONTENT]
        assert len(dup_issues) == 1

    async def test_passes_unique_titles(self):
        units = [make_unit(i, f"1.{i}", title_fr=f"Title {i}") for i in range(1, 4)]
        module = make_module(books_sources={"source": "book"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        dup_issues = [i for i in result.issues if i.issue_type == IssueType.DUPLICATE_UNIT_CONTENT]
        assert len(dup_issues) == 0


class TestModuleSources:
    async def test_flags_missing_sources(self):
        units = [make_unit(i, f"1.{i}") for i in range(1, 4)]
        module = make_module(books_sources=None)
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        src_issues = [i for i in result.issues if i.issue_type == IssueType.MISSING_SOURCES]
        assert len(src_issues) == 1

    async def test_passes_with_sources(self):
        units = [make_unit(i, f"1.{i}") for i in range(1, 4)]
        module = make_module(books_sources={"primary": "Gordis Epidemiology"})
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        src_issues = [i for i in result.issues if i.issue_type == IssueType.MISSING_SOURCES]
        assert len(src_issues) == 0


class TestModuleNotFound:
    async def test_raises_value_error_when_not_found(self):
        db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        service = ContentReviewerService(db)

        with pytest.raises(ValueError, match="not found"):
            await service.review_module(uuid.uuid4())


class TestPassedFlag:
    async def test_passed_true_when_no_issues(self):
        units = [make_unit(i, f"1.{i}", title_fr=f"Title {i}") for i in range(1, 6)]
        total_minutes = sum(u.estimated_minutes for u in units)
        module = make_module(
            estimated_hours=round(total_minutes / 60),
            books_sources={"source": "book"},
        )
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        assert result.passed is True

    async def test_passed_false_when_issues_exist(self):
        units = [make_unit(i, f"1.{i}") for i in range(1, 4)]
        module = make_module(estimated_hours=100, books_sources=None)
        service = _make_service_with_module(module, units)

        result = await service.review_module(module.id)

        assert result.passed is False
