"""Tests for LessonGenerationService — especially _build_lesson_query and _unit_id_to_unit_number."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.services.lesson_service import LessonGenerationService


@pytest.fixture
def lesson_service():
    return LessonGenerationService(
        claude_service=AsyncMock(spec=ClaudeService),
        semantic_retriever=AsyncMock(spec=SemanticRetriever),
    )


@pytest.fixture
def sample_module():
    m = Module()
    m.id = uuid.uuid4()
    m.module_number = 1
    m.level = 1
    m.title_fr = "Fondements de la Santé Publique"
    m.title_en = "Foundations of Public Health"
    m.description_fr = "Introduction aux concepts fondamentaux de la santé publique"
    m.description_en = "Introduction to fundamental concepts of public health"
    m.bloom_level = "knowledge"
    m.books_sources = {}
    return m


@pytest.fixture
def sample_unit(sample_module):
    u = ModuleUnit()
    u.id = uuid.uuid4()
    u.module_id = sample_module.id
    u.unit_number = "1.1"
    u.title_fr = "Histoire et définition de la santé publique"
    u.title_en = "History and definition of public health"
    u.description_fr = "Evolution de la santé publique, définitions clés, cadre conceptuel moderne"
    u.description_en = "Evolution of public health, key definitions, modern conceptual framework"
    u.order_index = 1
    return u


class TestUnitIdToUnitNumber:
    def test_converts_m01_u01(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("M01-U01") == "1.1"

    def test_converts_m01_u02(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("M01-U02") == "1.2"

    def test_converts_m01_u03(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("M01-U03") == "1.3"

    def test_converts_m03_u02(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("M03-U02") == "3.2"

    def test_lowercase_input(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("m01-u01") == "1.1"

    def test_invalid_format_returns_none(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("invalid") is None

    def test_missing_unit_part_returns_none(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("M01") is None

    def test_wrong_prefix_returns_none(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("X01-Y01") is None

    def test_empty_string_returns_none(self, lesson_service):
        assert lesson_service._unit_id_to_unit_number("") is None


class TestBuildLessonQuery:
    @pytest.mark.asyncio
    async def test_uses_unit_title_and_description_when_unit_found_fr(
        self, lesson_service, sample_module, sample_unit
    ):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_unit
        session.execute = AsyncMock(return_value=mock_result)

        query = await lesson_service._build_lesson_query(sample_module, "M01-U01", "fr", session)

        assert "Histoire et définition de la santé publique" in query
        assert "Evolution de la santé publique" in query
        assert "unit M01-U01" not in query

    @pytest.mark.asyncio
    async def test_uses_unit_title_and_description_when_unit_found_en(
        self, lesson_service, sample_module, sample_unit
    ):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_unit
        session.execute = AsyncMock(return_value=mock_result)

        query = await lesson_service._build_lesson_query(sample_module, "M01-U01", "en", session)

        assert "History and definition of public health" in query
        assert "Evolution of public health" in query

    @pytest.mark.asyncio
    async def test_falls_back_to_module_data_when_unit_not_found(
        self, lesson_service, sample_module
    ):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        query = await lesson_service._build_lesson_query(sample_module, "M01-U99", "fr", session)

        assert "Fondements de la Santé Publique" in query
        assert "Introduction aux concepts fondamentaux" in query

    @pytest.mark.asyncio
    async def test_falls_back_to_module_data_when_unit_id_invalid(
        self, lesson_service, sample_module
    ):
        session = AsyncMock()

        query = await lesson_service._build_lesson_query(sample_module, "invalid-id", "fr", session)

        assert "Fondements de la Santé Publique" in query
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_units_produce_different_queries(self, lesson_service, sample_module):
        unit1 = ModuleUnit()
        unit1.id = uuid.uuid4()
        unit1.module_id = sample_module.id
        unit1.unit_number = "1.1"
        unit1.title_fr = "Histoire et définition de la santé publique"
        unit1.title_en = "History and definition of public health"
        unit1.description_fr = "Evolution de la santé publique, définitions clés"
        unit1.description_en = "Evolution of public health, key definitions"
        unit1.order_index = 1

        unit2 = ModuleUnit()
        unit2.id = uuid.uuid4()
        unit2.module_id = sample_module.id
        unit2.unit_number = "1.2"
        unit2.title_fr = "Principes de prévention et promotion"
        unit2.title_en = "Prevention and promotion principles"
        unit2.description_fr = "Prévention primaire, secondaire, tertiaire"
        unit2.description_en = "Primary, secondary, tertiary prevention"
        unit2.order_index = 2

        session1 = AsyncMock()
        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = unit1
        session1.execute = AsyncMock(return_value=mock_result1)

        session2 = AsyncMock()
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = unit2
        session2.execute = AsyncMock(return_value=mock_result2)

        query1 = await lesson_service._build_lesson_query(sample_module, "M01-U01", "fr", session1)
        query2 = await lesson_service._build_lesson_query(sample_module, "M01-U02", "fr", session2)

        assert query1 != query2
        assert "Histoire" in query1
        assert "Principes de prévention" in query2
