"""Tests for flashcard generation functionality."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.content import FlashcardContent, FlashcardGenerationRequest
from app.domain.models.content import GeneratedContent
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
    ):
        """Test generating new flashcard set when none exists in cache."""
        # Arrange
        module_id = uuid.uuid4()
        language = "fr"
        country = "SN"
        level = 2

        # Mock session without existing content
        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value.scalar_one_or_none.return_value = None

        # Mock RAG retrieval
        mock_semantic_retriever.search.return_value = sample_search_results

        # Mock Claude API response
        mock_claude_service.generate_structured_content.return_value = json.dumps(
            sample_flashcard_data
        )

        # Act
        result = await flashcard_service.get_or_generate_flashcard_set(
            module_id=module_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        # Assert
        assert result is not None
        assert result.module_id == module_id
        assert result.language == language
        assert result.level == level
        assert result.country_context == country
        assert result.content_type == "flashcard"
        assert not result.cached
        assert len(result.flashcards) == 2

        # Verify flashcard content
        assert result.flashcards[0].term == "Surveillance épidémiologique"
        assert "Sénégal" in result.flashcards[0].example_aof
        assert result.flashcards[1].formula is not None
        assert "Incidence Rate" in result.flashcards[1].formula

        # Verify service calls
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
        # Arrange
        module_id = uuid.uuid4()
        language = "fr"
        country = "SN"
        level = 2

        # Mock existing content in database
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
        )

        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value.scalar_one_or_none.return_value = existing_content

        # Act
        result = await flashcard_service.get_or_generate_flashcard_set(
            module_id=module_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        # Assert
        assert result is not None
        assert result.cached
        assert len(result.flashcards) == 2

        # Verify no generation calls were made
        mock_semantic_retriever.search.assert_not_called()
        mock_claude_service.generate_structured_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_flashcard_set_no_search_results(
        self,
        flashcard_service,
        mock_semantic_retriever,
    ):
        """Test error handling when no relevant content is found."""
        # Arrange
        module_id = uuid.uuid4()
        language = "fr"
        country = "SN"
        level = 2

        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value.scalar_one_or_none.return_value = None

        # Mock empty search results
        mock_semantic_retriever.search.return_value = []

        # Act & Assert
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
    ):
        """Test error handling when Claude API fails."""
        # Arrange
        module_id = uuid.uuid4()
        language = "fr"
        country = "SN"
        level = 2

        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value.scalar_one_or_none.return_value = None

        mock_semantic_retriever.search.return_value = sample_search_results
        mock_claude_service.generate_structured_content.side_effect = Exception("API Error")

        # Act & Assert
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
    ):
        """Test error handling when Claude returns invalid JSON."""
        # Arrange
        module_id = uuid.uuid4()
        language = "fr"
        country = "SN"
        level = 2

        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value.scalar_one_or_none.return_value = None

        mock_semantic_retriever.search.return_value = sample_search_results
        mock_claude_service.generate_structured_content.return_value = "Invalid JSON"

        # Act & Assert
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
        # Act
        sources = flashcard_service._extract_sources_from_flashcards(sample_flashcard_data)

        # Assert
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
        # Arrange
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
        )

        # Act
        result = flashcard_service._build_response_from_content(content, cached=True)

        # Assert
        assert result.id == content.id
        assert result.module_id == content.module_id
        assert result.cached
        assert len(result.flashcards) == 2
        assert isinstance(result.flashcards[0], FlashcardContent)


class TestFlashcardGenerationRequest:
    """Test cases for request/response schemas."""

    def test_flashcard_generation_request_validation(self):
        """Test FlashcardGenerationRequest validation."""
        # Valid request
        request = FlashcardGenerationRequest(
            module_id=uuid.uuid4(),
            language="fr",
            country="SN",
            level=2,
        )
        assert request.language == "fr"
        assert request.level == 2

        # Invalid language
        with pytest.raises(ValueError):
            FlashcardGenerationRequest(
                module_id=uuid.uuid4(),
                language="es",  # Not in allowed values
                country="SN",
                level=2,
            )

        # Invalid level
        with pytest.raises(ValueError):
            FlashcardGenerationRequest(
                module_id=uuid.uuid4(),
                language="fr",
                country="SN",
                level=5,  # Outside 1-4 range
            )

    def test_flashcard_content_validation(self):
        """Test FlashcardContent validation."""
        # Valid flashcard
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

        # Optional formula
        flashcard_no_formula = FlashcardContent(
            term="Test Term",
            definition_fr="Définition française",
            definition_en="English definition",
            example_aof="African example",
            formula=None,
            sources_cited=["Source 1"],
        )
        assert flashcard_no_formula.formula is None
