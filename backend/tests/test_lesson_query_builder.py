"""Tests for lesson query builder — verifies unit-specific RAG queries and cache lookup."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.content import GeneratedContent
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
def sample_module() -> Module:
    module = Module(
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
    return module


@pytest.fixture
def sample_unit_u01() -> ModuleUnit:
    return ModuleUnit(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_number="1.1",
        title_fr="Histoire et définition de la santé publique",
        title_en="History and definition of public health",
        description_fr="Evolution de la santé publique, définitions clés, cadre conceptuel moderne",
        description_en="Evolution of public health, key definitions, modern conceptual framework",
        order_index=1,
    )


@pytest.fixture
def sample_unit_u02() -> ModuleUnit:
    return ModuleUnit(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_number="1.2",
        title_fr="Principes de prévention et promotion",
        title_en="Prevention and promotion principles",
        description_fr="Prévention primaire, secondaire, tertiaire et promotion de la santé",
        description_en="Primary, secondary, tertiary prevention and health promotion",
        order_index=2,
    )


class TestBuildLessonQuery:
    @pytest.mark.asyncio
    async def test_uses_unit_title_when_unit_found(
        self, lesson_service, sample_module, sample_unit_u01
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_unit_u01
        session.execute = AsyncMock(return_value=mock_result)

        query = await lesson_service._build_lesson_query(sample_module, "1.1", "fr", session)

        assert "Histoire et définition de la santé publique" in query
        assert "Evolution de la santé publique" in query
        assert "unit 1.1" not in query

    @pytest.mark.asyncio
    async def test_uses_english_title_for_en_language(
        self, lesson_service, sample_module, sample_unit_u01
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_unit_u01
        session.execute = AsyncMock(return_value=mock_result)

        query = await lesson_service._build_lesson_query(sample_module, "1.1", "en", session)

        assert "History and definition of public health" in query
        assert "Evolution of public health" in query

    @pytest.mark.asyncio
    async def test_different_units_produce_different_queries(
        self, lesson_service, sample_module, sample_unit_u01, sample_unit_u02
    ):
        session = AsyncMock(spec=AsyncSession)

        mock_result_u01 = MagicMock()
        mock_result_u01.scalar_one_or_none.return_value = sample_unit_u01

        mock_result_u02 = MagicMock()
        mock_result_u02.scalar_one_or_none.return_value = sample_unit_u02

        session.execute = AsyncMock(side_effect=[mock_result_u01, mock_result_u02])

        query_u01 = await lesson_service._build_lesson_query(
            sample_module, "1.1", "fr", session
        )
        query_u02 = await lesson_service._build_lesson_query(
            sample_module, "1.2", "fr", session
        )

        assert query_u01 != query_u02
        assert "Histoire et définition" in query_u01
        assert "Principes de prévention" in query_u02

    @pytest.mark.asyncio
    async def test_falls_back_to_module_data_when_unit_not_found(
        self, lesson_service, sample_module
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        query = await lesson_service._build_lesson_query(sample_module, "1.99", "fr", session)

        assert "Fondements de la Santé Publique" in query
        assert "unit 1.99" in query


@pytest.fixture
def sample_module_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def make_cached_content(sample_module_id):
    def _make(unit_id: str) -> GeneratedContent:
        content = GeneratedContent(
            id=uuid.uuid4(),
            module_id=sample_module_id,
            content_type="lesson",
            language="fr",
            level=1,
            content={
                "unit_id": unit_id,
                "introduction": f"Intro for {unit_id}",
                "concepts": ["Concept 1"],
                "aof_example": "Example",
                "synthesis": "Synthesis",
                "key_points": ["Point 1"],
                "sources_cited": ["Source 1"],
            },
            sources_cited=["Source 1"],
            country_context="SN",
            generated_at=datetime(2026, 1, 1, 0, 0, 0),
            validated=False,
        )
        return content

    return _make


class TestGetCachedLesson:
    @pytest.mark.asyncio
    async def test_returns_cached_lesson_for_matching_unit(
        self, lesson_service, sample_module_id, make_cached_content
    ):
        session = AsyncMock(spec=AsyncSession)
        cached = make_cached_content("1.1")
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = cached
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        result, is_fallback = await lesson_service._get_cached_lesson(
            sample_module_id, "1.1", "fr", "SN", 1, session
        )

        assert result is not None
        assert result.unit_id == "1.1"
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_returns_none_on_cache_miss(self, lesson_service, sample_module_id):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        result, _ = await lesson_service._get_cached_lesson(
            sample_module_id, "1.2", "fr", "SN", 1, session
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_different_units_return_their_own_cached_content(
        self, lesson_service, sample_module_id, make_cached_content
    ):
        cached_u01 = make_cached_content("1.1")
        cached_u02 = make_cached_content("1.2")

        mock_result_u01 = MagicMock()
        mock_scalars_u01 = MagicMock()
        mock_scalars_u01.first.return_value = cached_u01
        mock_result_u01.scalars.return_value = mock_scalars_u01

        mock_result_u02 = MagicMock()
        mock_scalars_u02 = MagicMock()
        mock_scalars_u02.first.return_value = cached_u02
        mock_result_u02.scalars.return_value = mock_scalars_u02

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=[mock_result_u01, mock_result_u02])

        result_u01, _ = await lesson_service._get_cached_lesson(
            sample_module_id, "1.1", "fr", "SN", 1, session
        )
        result_u02, _ = await lesson_service._get_cached_lesson(
            sample_module_id, "1.2", "fr", "SN", 1, session
        )

        assert result_u01 is not None
        assert result_u02 is not None
        assert result_u01.unit_id == "1.1"
        assert result_u02.unit_id == "1.2"
        assert result_u01.unit_id != result_u02.unit_id

    @pytest.mark.asyncio
    async def test_cached_lesson_has_correct_module_id(
        self, lesson_service, sample_module_id, make_cached_content
    ):
        session = AsyncMock(spec=AsyncSession)
        cached = make_cached_content("1.3")
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = cached
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        result, _ = await lesson_service._get_cached_lesson(
            sample_module_id, "1.3", "fr", "SN", 1, session
        )

        assert result is not None
        assert result.module_id == sample_module_id


class TestGetCachedLessonSourceImageRefs:
    """Tests that source_image_refs are extracted from all content fields in cached lessons."""

    def _make_session_with_cached(self, content: dict, module_id: uuid.UUID) -> AsyncMock:
        session = AsyncMock(spec=AsyncSession)
        cached = GeneratedContent(
            id=uuid.uuid4(),
            module_id=module_id,
            content_type="lesson",
            language="fr",
            level=1,
            content=content,
            sources_cited=["Source 1"],
            country_context="SN",
            generated_at=datetime(2026, 1, 1, 0, 0, 0),
            validated=False,
        )
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = cached
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)
        return session

    @pytest.mark.asyncio
    async def test_image_marker_in_concepts_list_is_found(self, lesson_service, sample_module_id):
        img_id = str(uuid.uuid4())
        mock_db_img = MagicMock()
        mock_db_img.id = uuid.UUID(img_id)
        mock_db_img.to_meta_dict.return_value = {
            "id": img_id,
            "figure_number": "1.10",
            "caption": "Diagram",
            "image_type": "diagram",
            "storage_url": "https://cdn.example.com/img.webp",
            "alt_text_fr": None,
            "alt_text_en": None,
            "attribution": None,
        }

        content = {
            "unit_id": "1.1",
            "introduction": "Introduction text",
            "concepts": [f"Concept with marker {{{{source_image:{img_id}}}}}"],
            "aof_example": "Example",
            "synthesis": "Synthesis",
            "key_points": ["Point 1"],
            "sources_cited": ["Source 1"],
            "source_image_refs": [],
        }

        session = AsyncMock(spec=AsyncSession)
        cached = GeneratedContent(
            id=uuid.uuid4(),
            module_id=sample_module_id,
            content_type="lesson",
            language="fr",
            level=1,
            content=content,
            sources_cited=["Source 1"],
            country_context="SN",
            generated_at=datetime(2026, 1, 1, 0, 0, 0),
            validated=False,
        )

        mock_first_result = MagicMock()
        mock_scalars_first = MagicMock()
        mock_scalars_first.first.return_value = cached
        mock_first_result.scalars.return_value = mock_scalars_first

        mock_db_result = MagicMock()
        mock_db_scalars = MagicMock()
        mock_db_scalars.all.return_value = [mock_db_img]
        mock_db_result.scalars.return_value = mock_db_scalars

        session.execute = AsyncMock(side_effect=[mock_first_result, mock_db_result])

        result, _ = await lesson_service._get_cached_lesson(
            sample_module_id, "1.1", "fr", "SN", 1, session
        )

        assert result is not None
        assert len(result.source_image_refs) == 1
        assert result.source_image_refs[0].id == img_id

    @pytest.mark.asyncio
    async def test_image_marker_in_key_points_list_is_found(self, lesson_service, sample_module_id):
        img_id = str(uuid.uuid4())
        mock_db_img = MagicMock()
        mock_db_img.id = uuid.UUID(img_id)
        mock_db_img.to_meta_dict.return_value = {
            "id": img_id,
            "figure_number": "2.1",
            "caption": "Key point figure",
            "image_type": "chart",
            "storage_url": "https://cdn.example.com/chart.webp",
            "alt_text_fr": None,
            "alt_text_en": None,
            "attribution": None,
        }

        content = {
            "unit_id": "1.1",
            "introduction": "Introduction text",
            "concepts": ["Normal concept"],
            "aof_example": "Example",
            "synthesis": "Synthesis",
            "key_points": ["Normal point", f"Point with {{{{source_image:{img_id}}}}}"],
            "sources_cited": ["Source 1"],
            "source_image_refs": [],
        }

        session = AsyncMock(spec=AsyncSession)
        cached = GeneratedContent(
            id=uuid.uuid4(),
            module_id=sample_module_id,
            content_type="lesson",
            language="fr",
            level=1,
            content=content,
            sources_cited=["Source 1"],
            country_context="SN",
            generated_at=datetime(2026, 1, 1, 0, 0, 0),
            validated=False,
        )

        mock_first_result = MagicMock()
        mock_scalars_first = MagicMock()
        mock_scalars_first.first.return_value = cached
        mock_first_result.scalars.return_value = mock_scalars_first

        mock_db_result = MagicMock()
        mock_db_scalars = MagicMock()
        mock_db_scalars.all.return_value = [mock_db_img]
        mock_db_result.scalars.return_value = mock_db_scalars

        session.execute = AsyncMock(side_effect=[mock_first_result, mock_db_result])

        result, _ = await lesson_service._get_cached_lesson(
            sample_module_id, "1.1", "fr", "SN", 1, session
        )

        assert result is not None
        assert len(result.source_image_refs) == 1
        assert result.source_image_refs[0].id == img_id

    @pytest.mark.asyncio
    async def test_extract_source_image_refs_handles_dict_text_directly(self, lesson_service):
        img_id = str(uuid.uuid4())
        img_meta = {
            "id": img_id,
            "figure_number": "3.5",
            "caption": "Concept dict figure",
            "image_type": "diagram",
            "storage_url": None,
            "alt_text_fr": None,
            "alt_text_en": None,
            "attribution": None,
        }
        text = f"title Concept A body Body with {{{{source_image:{img_id}}}}}"
        linked = {uuid.uuid4(): [img_meta]}

        result = await LessonGenerationService._extract_source_image_refs(text, linked)

        assert len(result) == 1
        assert result[0].id == img_id
