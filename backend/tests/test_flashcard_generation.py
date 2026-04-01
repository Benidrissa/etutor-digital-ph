"""Tests for flashcard generation functionality."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.content import FlashcardContent, FlashcardGenerationRequest
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.services.flashcard_service import FlashcardGenerationService


@pytest.fixture
def mock_claude_service():
    """Mock Claude service."""
    service = AsyncMock(spec=ClaudeService)
    return service


@pytest.fixture
def mock_semantic_retriever():
    """Mock semantic retriever."""
    retriever = AsyncMock(spec=SemanticRetriever)
    return retriever


@pytest.fixture
def flashcard_service(mock_claude_service, mock_semantic_retriever):
    """FlashcardGenerationService with mocked dependencies."""
    return FlashcardGenerationService(mock_claude_service, mock_semantic_retriever)


@pytest.fixture
def sample_flashcard_data():
    """Sample flashcard data for testing."""
    return [
        {
            "term": "Surveillance épidémiologique",
            "definition_fr": "Collecte systématique et continue de données sur l'état de santé des populations pour guider les actions de santé publique en temps réel.",
            "definition_en": "Systematic and continuous collection of data on population health status to guide real-time public health actions.",
            "example_aof": "Au Sénégal, le système de surveillance du paludisme collecte des données hebdomadaires dans tous les centres de santé pour détecter rapidement les épidémies.",
            "formula": None,
            "sources_cited": ["Donaldson Ch.4, p.67", "Scutchfield Ch.8, p.145"],
        },
        {
            "term": "Incidence Rate",
            "definition_fr": "Nombre de nouveaux cas d'une maladie survenant dans une population définie pendant une période donnée, divisé par la population à risque.",
            "definition_en": "Number of new cases of a disease occurring in a defined population during a specified time period, divided by the population at risk.",
            "example_aof": "En Côte d'Ivoire, le taux d'incidence du paludisme est calculé mensuellement pour chaque district sanitaire.",
            "formula": "$\\text{Incidence Rate} = \\frac{\\text{Nouveaux cas}}{\\text{Population à risque} \\times \\text{Temps}} \\times 100,000$",
            "sources_cited": ["Triola Ch.3, p.89"],
        },
    ]


@pytest.fixture
def sample_search_results():
    """Sample RAG search results."""
    mock_chunk1 = MagicMock()
    mock_chunk1.content = "Epidemiological surveillance is the systematic collection..."
    mock_chunk1.source = "donaldson"
    mock_chunk1.chapter = 4
    mock_chunk1.page = 67

    mock_chunk2 = MagicMock()
    mock_chunk2.content = "Incidence rates measure the frequency of disease occurrence..."
    mock_chunk2.source = "triola"
    mock_chunk2.chapter = 3
    mock_chunk2.page = 89

    mock_result1 = MagicMock()
    mock_result1.chunk = mock_chunk1

    mock_result2 = MagicMock()
    mock_result2.chunk = mock_chunk2

    return [mock_result1, mock_result2]


@pytest.fixture
def sample_module():
    """Sample Module ORM object for testing."""
    module = Module(
        id=uuid.uuid4(),
        module_number=1,
        level=1,
        title_fr="Introduction à la Santé Publique",
        title_en="Introduction to Public Health",
        description_fr="Module introductif",
        description_en="Introductory module",
        estimated_hours=20,
        bloom_level="knowledge",
        books_sources={"donaldson": [1, 2, 3], "scutchfield": [1]},
    )
    return module


def _make_session_with_execute_sequence(return_values: list) -> AsyncMock:
    """Create a mock session whose execute calls return values in sequence."""
    session = AsyncMock(spec=AsyncSession)
    mock_results = [MagicMock() for _ in return_values]
    for mock_result, value in zip(mock_results, return_values, strict=True):
        mock_result.scalar_one_or_none.return_value = value
    session.execute = AsyncMock(side_effect=mock_results)
    return session


class TestFlashcardGenerationService:
    """Test cases for FlashcardGenerationService."""

    @pytest.mark.asyncio
    async def test_get_or_generate_flashcard_set_new_generation(
        self,
        flashcard_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_flashcard_data,
        sample_search_results,
        sample_module,
    ):
        """Test generating new flashcard set when none exists in cache."""
        module_id = sample_module.id
        language = "fr"
        country = "SN"
        level = 2

        session = _make_session_with_execute_sequence([None, sample_module])

        def mock_refresh(obj):
            if hasattr(obj, "generated_at") and obj.generated_at is None:
                obj.generated_at = datetime.now(UTC)

        session.refresh = AsyncMock(side_effect=mock_refresh)

        mock_semantic_retriever.search.return_value = sample_search_results
        mock_claude_service.generate_structured_content.return_value = json.dumps(
            sample_flashcard_data
        )

        result = await flashcard_service.get_or_generate_flashcard_set(
            module_id=module_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        assert result is not None
        assert result.module_id == module_id
        assert result.language == language
        assert result.level == level
        assert result.country_context == country
        assert result.content_type == "flashcard"
        assert not result.cached
        assert len(result.flashcards) == 2

        assert result.flashcards[0].term == "Surveillance épidémiologique"
        assert "Sénégal" in result.flashcards[0].example_aof
        assert result.flashcards[1].formula is not None
        assert "Incidence Rate" in result.flashcards[1].formula

        mock_semantic_retriever.search.assert_called_once()
        mock_claude_service.generate_structured_content.assert_called_once()
        session.add.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_or_generate_flashcard_set_from_cache(
        self,
        flashcard_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_flashcard_data,
    ):
        """Test retrieving existing flashcard set from cache."""
        module_id = uuid.uuid4()
        language = "fr"
        country = "SN"
        level = 2

        existing_content = GeneratedContent(
            id=uuid.uuid4(),
            module_id=module_id,
            content_type="flashcard",
            language=language,
            level=level,
            content={"flashcards": sample_flashcard_data},
            sources_cited=["Donaldson Ch.4, p.67", "Triola Ch.3, p.89"],
            country_context=country,
            validated=False,
            generated_at=datetime.now(UTC),
        )

        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_content
        session.execute = AsyncMock(return_value=mock_result)

        result = await flashcard_service.get_or_generate_flashcard_set(
            module_id=module_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        assert result is not None
        assert result.cached
        assert len(result.flashcards) == 2

        mock_semantic_retriever.search.assert_not_called()
        mock_claude_service.generate_structured_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_flashcard_set_module_not_found(
        self,
        flashcard_service,
        mock_semantic_retriever,
    ):
        """Test error handling when module does not exist in database."""
        module_id = uuid.uuid4()
        language = "fr"
        country = "SN"
        level = 2

        session = _make_session_with_execute_sequence([None, None])

        with pytest.raises(ValueError, match="not found"):
            await flashcard_service.get_or_generate_flashcard_set(
                module_id=module_id,
                language=language,
                country=country,
                level=level,
                session=session,
            )

        mock_semantic_retriever.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_flashcard_set_uses_module_title_in_rag_query(
        self,
        flashcard_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_flashcard_data,
        sample_search_results,
        sample_module,
    ):
        """Test that RAG search query contains the actual module title."""
        module_id = sample_module.id
        language = "fr"
        country = "SN"
        level = 1

        session = _make_session_with_execute_sequence([None, sample_module])

        def mock_refresh(obj):
            if hasattr(obj, "generated_at") and obj.generated_at is None:
                obj.generated_at = datetime.now(UTC)

        session.refresh = AsyncMock(side_effect=mock_refresh)
        mock_semantic_retriever.search.return_value = sample_search_results
        mock_claude_service.generate_structured_content.return_value = json.dumps(
            sample_flashcard_data
        )

        await flashcard_service.get_or_generate_flashcard_set(
            module_id=module_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        search_call_kwargs = mock_semantic_retriever.search.call_args
        query_used = (
            search_call_kwargs[1]["query"] if search_call_kwargs[1] else search_call_kwargs[0][0]
        )
        assert sample_module.title_fr in query_used

    @pytest.mark.asyncio
    async def test_generate_flashcard_set_no_search_results(
        self,
        flashcard_service,
        mock_semantic_retriever,
        sample_module,
    ):
        """Test error handling when no relevant content is found."""
        module_id = sample_module.id
        language = "fr"
        country = "SN"
        level = 2

        session = _make_session_with_execute_sequence([None, sample_module])

        mock_semantic_retriever.search.return_value = []

        with pytest.raises(ValueError, match="No relevant content found"):
            await flashcard_service.get_or_generate_flashcard_set(
                module_id=module_id,
                language=language,
                country=country,
                level=level,
                session=session,
            )

    @pytest.mark.asyncio
    async def test_generate_flashcard_set_claude_api_error(
        self,
        flashcard_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_search_results,
        sample_module,
    ):
        """Test error handling when Claude API fails."""
        module_id = sample_module.id
        language = "fr"
        country = "SN"
        level = 2

        session = _make_session_with_execute_sequence([None, sample_module])

        def mock_refresh(obj):
            if hasattr(obj, "generated_at") and obj.generated_at is None:
                obj.generated_at = datetime.now(UTC)

        session.refresh = AsyncMock(side_effect=mock_refresh)

        mock_semantic_retriever.search.return_value = sample_search_results
        mock_claude_service.generate_structured_content.side_effect = Exception("API Error")

        with pytest.raises(ValueError, match="Content generation failed"):
            await flashcard_service.get_or_generate_flashcard_set(
                module_id=module_id,
                language=language,
                country=country,
                level=level,
                session=session,
            )

    @pytest.mark.asyncio
    async def test_generate_flashcard_set_invalid_json_response(
        self,
        flashcard_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_search_results,
        sample_module,
    ):
        """Test error handling when Claude returns invalid JSON."""
        module_id = sample_module.id
        language = "fr"
        country = "SN"
        level = 2

        session = _make_session_with_execute_sequence([None, sample_module])

        def mock_refresh(obj):
            if hasattr(obj, "generated_at") and obj.generated_at is None:
                obj.generated_at = datetime.now(UTC)

        session.refresh = AsyncMock(side_effect=mock_refresh)

        mock_semantic_retriever.search.return_value = sample_search_results
        mock_claude_service.generate_structured_content.return_value = "Invalid JSON"

        with pytest.raises(ValueError, match="Invalid JSON response"):
            await flashcard_service.get_or_generate_flashcard_set(
                module_id=module_id,
                language=language,
                country=country,
                level=level,
                session=session,
            )

    def test_extract_sources_from_flashcards(
        self,
        flashcard_service,
        sample_flashcard_data,
    ):
        """Test extracting unique sources from flashcard data."""
        sources = flashcard_service._extract_sources_from_flashcards(sample_flashcard_data)

        assert len(sources) == 3
        assert "Donaldson Ch.4, p.67" in sources
        assert "Scutchfield Ch.8, p.145" in sources
        assert "Triola Ch.3, p.89" in sources

    def test_build_response_from_content(
        self,
        flashcard_service,
        sample_flashcard_data,
    ):
        """Test building response from GeneratedContent."""
        content = GeneratedContent(
            id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            content_type="flashcard",
            language="fr",
            level=2,
            content={"flashcards": sample_flashcard_data},
            sources_cited=["Donaldson Ch.4, p.67"],
            country_context="SN",
            validated=False,
            generated_at=datetime.now(UTC),
        )

        result = flashcard_service._build_response_from_content(content, cached=True)

        assert result.id == content.id
        assert result.module_id == content.module_id
        assert result.cached
        assert len(result.flashcards) == 2
        assert isinstance(result.flashcards[0], FlashcardContent)


class TestFlashcardGenerationRequest:
    """Test cases for request/response schemas."""

    def test_flashcard_generation_request_validation(self):
        """Test FlashcardGenerationRequest validation."""
        request = FlashcardGenerationRequest(
            module_id=uuid.uuid4(),
            language="fr",
            country="SN",
            level=2,
        )
        assert request.language == "fr"
        assert request.level == 2

        with pytest.raises(ValueError):
            FlashcardGenerationRequest(
                module_id=uuid.uuid4(),
                language="es",
                country="SN",
                level=2,
            )

        with pytest.raises(ValueError):
            FlashcardGenerationRequest(
                module_id=uuid.uuid4(),
                language="fr",
                country="SN",
                level=5,
            )

    def test_flashcard_content_validation(self):
        """Test FlashcardContent validation."""
        flashcard = FlashcardContent(
            term="Test Term",
            definition_fr="Définition française",
            definition_en="English definition",
            example_aof="African example",
            formula="$x = y$",
            sources_cited=["Source 1"],
        )
        assert flashcard.term == "Test Term"
        assert flashcard.formula == "$x = y$"

        flashcard_no_formula = FlashcardContent(
            term="Test Term",
            definition_fr="Définition française",
            definition_en="English definition",
            example_aof="African example",
            formula=None,
            sources_cited=["Source 1"],
        )
        assert flashcard_no_formula.formula is None
