"""Tests for CaseStudyGenerationService — verifies case study generation and routing."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.services.lesson_service import CaseStudyGenerationService


@pytest.fixture
def case_study_service():
    return CaseStudyGenerationService(
        claude_service=AsyncMock(spec=ClaudeService),
        semantic_retriever=AsyncMock(spec=SemanticRetriever),
    )


@pytest.fixture
def sample_module() -> Module:
    return Module(
        id=uuid.uuid4(),
        module_number=1,
        level=1,
        title_fr="Fondements de la Santé Publique",
        title_en="Foundations of Public Health",
        description_fr="Introduction aux concepts de santé publique",
        description_en="Introduction to public health concepts",
        bloom_level="remember",
        books_sources={"donaldson": ["chapter_1", "chapter_2"]},
    )


@pytest.fixture
def sample_unit_u05() -> ModuleUnit:
    return ModuleUnit(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_number="1.5",
        title_fr="Étude de cas : Analyse de défi sanitaire",
        title_en="Case Study: Health Challenge Analysis",
        description_fr="Appliquer la pensée systémique à un véritable défi sanitaire",
        description_en="Apply systems thinking to a real West African health challenge",
        order_index=5,
    )


class TestBuildCaseStudyQuery:
    @pytest.mark.asyncio
    async def test_uses_unit_title_when_unit_found(
        self, case_study_service, sample_module, sample_unit_u05
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_unit_u05
        session.execute = AsyncMock(return_value=mock_result)

        query = await case_study_service._build_case_study_query(
            sample_module, "M01-U05", "fr", session
        )

        assert "Étude de cas" in query or "défi sanitaire" in query

    @pytest.mark.asyncio
    async def test_uses_english_title_for_en_language(
        self, case_study_service, sample_module, sample_unit_u05
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_unit_u05
        session.execute = AsyncMock(return_value=mock_result)

        query = await case_study_service._build_case_study_query(
            sample_module, "M01-U05", "en", session
        )

        assert "Case Study" in query or "health challenge" in query.lower()

    @pytest.mark.asyncio
    async def test_falls_back_to_module_data_when_unit_not_found(
        self, case_study_service, sample_module
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        query = await case_study_service._build_case_study_query(
            sample_module, "M01-U05", "fr", session
        )

        assert "Fondements de la Santé Publique" in query

    @pytest.mark.asyncio
    async def test_falls_back_for_invalid_unit_id(self, case_study_service, sample_module):
        session = AsyncMock(spec=AsyncSession)

        query = await case_study_service._build_case_study_query(
            sample_module, "INVALID", "fr", session
        )

        assert "Fondements de la Santé Publique" in query
        session.execute.assert_not_called()


class TestParseCaseStudyContent:
    @pytest.mark.asyncio
    async def test_returns_case_study_content_with_sources(self, case_study_service):
        mock_chunk = MagicMock(spec=["source", "chapter", "page"])
        mock_chunk.source = "donaldson"
        mock_chunk.chapter = 4
        mock_chunk.page = 67

        content_text = "A" * 1000

        result = await case_study_service._parse_case_study_content(content_text, [mock_chunk])

        assert result.aof_context
        assert result.real_data is not None
        assert len(result.guided_questions) >= 2
        assert result.annotated_correction
        assert len(result.sources_cited) > 0
        assert "Donaldson Ch.4, p.67" in result.sources_cited

    @pytest.mark.asyncio
    async def test_returns_case_study_content_with_search_result_chunks(self, case_study_service):
        inner_chunk = MagicMock()
        inner_chunk.source = "scutchfield"
        inner_chunk.chapter = 2
        inner_chunk.page = 15

        mock_search_result = MagicMock()
        mock_search_result.chunk = inner_chunk

        content_text = "Context " * 50

        result = await case_study_service._parse_case_study_content(
            content_text, [mock_search_result]
        )

        assert "Scutchfield Ch.2, p.15" in result.sources_cited

    @pytest.mark.asyncio
    async def test_deduplicated_sources(self, case_study_service):
        mock_chunk = MagicMock(spec=["source", "chapter", "page"])
        mock_chunk.source = "donaldson"
        mock_chunk.chapter = 4
        mock_chunk.page = 67

        result = await case_study_service._parse_case_study_content(
            "content", [mock_chunk, mock_chunk]
        )

        assert result.sources_cited.count("Donaldson Ch.4, p.67") == 1


class TestCaseStudyPromptImports:
    def test_get_case_study_system_prompt_fr(self):
        from app.ai.prompts.case_study import get_case_study_system_prompt

        prompt = get_case_study_system_prompt("fr", "SN", 1, "remember")

        assert "fr" in prompt
        assert "West African Context" in prompt
        assert "Guided Questions" in prompt
        assert "Annotated Correction" in prompt

    def test_get_case_study_system_prompt_en(self):
        from app.ai.prompts.case_study import get_case_study_system_prompt

        prompt = get_case_study_system_prompt("en", "GH", 2, "understand")

        assert "en" in prompt
        assert "West African Context" in prompt
        assert "Guided Questions" in prompt
        assert "Annotated Correction" in prompt

    def test_format_rag_context_includes_topic_for_known_module(self):
        from app.ai.prompts.case_study import format_rag_context_for_case_study

        mock_chunk = MagicMock()
        mock_chunk.source = "donaldson"
        mock_chunk.chapter = 1
        mock_chunk.page = 10
        mock_chunk.content = "sample content"

        context = format_rag_context_for_case_study(
            [mock_chunk],
            "health challenge",
            "Fondements de la Santé Publique",
            "M01-U05",
            "fr",
            module_id="M01",
        )

        assert "Ebola" in context or "Guinée" in context

    def test_format_rag_context_without_known_module(self):
        from app.ai.prompts.case_study import format_rag_context_for_case_study

        mock_chunk = MagicMock()
        mock_chunk.source = "donaldson"
        mock_chunk.chapter = 1
        mock_chunk.page = 10
        mock_chunk.content = "sample content"

        context = format_rag_context_for_case_study(
            [mock_chunk],
            "health challenge",
            "Unknown Module",
            "M99-U01",
            "en",
            module_id="M99",
        )

        assert "Unknown Module" in context
        assert "health challenge" in context
