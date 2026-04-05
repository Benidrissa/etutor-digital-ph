"""Tests for search_source_images tool, available_figures in search_knowledge_base, and DALL-E fallback."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.user import User
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_user():
    return User(
        id=uuid.uuid4(),
        email="img@test.com",
        name="Image Tester",
        preferred_language="fr",
        country="SN",
        professional_role="nurse",
        current_level=2,
        streak_days=0,
        last_active=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_retriever():
    retriever = AsyncMock(spec=SemanticRetriever)
    retriever.search_for_module = AsyncMock(return_value=[])
    retriever.get_linked_images = AsyncMock(return_value={})
    retriever.search_source_images = AsyncMock(return_value=[])
    return retriever


@pytest.fixture
def tool_executor(mock_retriever, sample_user):
    return TutorToolExecutor(
        retriever=mock_retriever,
        anthropic_client=MagicMock(),
        user_id=sample_user.id,
        user_level=sample_user.current_level,
        user_language=sample_user.preferred_language,
    )


# ---------------------------------------------------------------------------
# TOOL_DEFINITIONS checks
# ---------------------------------------------------------------------------


def test_tool_definitions_has_six_tools():
    assert len(TOOL_DEFINITIONS) == 6


def test_search_source_images_tool_defined():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert "search_source_images" in names


def test_search_source_images_schema():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "search_source_images")
    props = tool["input_schema"]["properties"]
    assert "query" in props
    assert "image_type" in props
    assert tool["input_schema"]["required"] == ["query"]
    assert "any" in props["image_type"]["enum"]


# ---------------------------------------------------------------------------
# _search_source_images handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_source_images_returns_figures(tool_executor, mock_retriever):
    img_id = str(uuid.uuid4())
    mock_retriever.search_source_images.return_value = [
        {
            "id": img_id,
            "figure_number": "3.1",
            "caption": "Cycle épidémique",
            "image_type": "diagram",
            "source": "Donaldson",
            "chapter": "3",
            "similarity": 0.85,
        }
    ]
    mock_session = AsyncMock(spec=AsyncSession)

    result = json.loads(
        await tool_executor._search_source_images({"query": "cycle épidémique"}, mock_session)
    )

    assert result["count"] == 1
    assert result["figures"][0]["figure_number"] == "3.1"
    assert f"{{{{source_image:{img_id}}}}}" == result["figures"][0]["ref"]


@pytest.mark.asyncio
async def test_search_source_images_filters_by_type(tool_executor, mock_retriever):
    mock_retriever.search_source_images.return_value = [
        {
            "id": str(uuid.uuid4()),
            "image_type": "diagram",
            "figure_number": "1.1",
            "caption": "D",
            "source": "S",
            "chapter": "1",
            "similarity": 0.9,
        },
        {
            "id": str(uuid.uuid4()),
            "image_type": "photo",
            "figure_number": "1.2",
            "caption": "P",
            "source": "S",
            "chapter": "1",
            "similarity": 0.8,
        },
    ]
    mock_session = AsyncMock(spec=AsyncSession)

    result = json.loads(
        await tool_executor._search_source_images(
            {"query": "test", "image_type": "diagram"}, mock_session
        )
    )

    assert result["count"] == 1
    assert result["figures"][0]["image_type"] == "diagram"


@pytest.mark.asyncio
async def test_search_source_images_any_returns_all(tool_executor, mock_retriever):
    mock_retriever.search_source_images.return_value = [
        {
            "id": str(uuid.uuid4()),
            "image_type": "diagram",
            "figure_number": "1.1",
            "caption": "D",
            "source": "S",
            "chapter": "1",
            "similarity": 0.9,
        },
        {
            "id": str(uuid.uuid4()),
            "image_type": "photo",
            "figure_number": "1.2",
            "caption": "P",
            "source": "S",
            "chapter": "1",
            "similarity": 0.8,
        },
    ]
    mock_session = AsyncMock(spec=AsyncSession)

    result = json.loads(
        await tool_executor._search_source_images(
            {"query": "test", "image_type": "any"}, mock_session
        )
    )

    assert result["count"] == 2


@pytest.mark.asyncio
async def test_search_source_images_empty(tool_executor, mock_retriever):
    mock_retriever.search_source_images.return_value = []
    mock_session = AsyncMock(spec=AsyncSession)

    result = json.loads(await tool_executor._search_source_images({"query": "xyz"}, mock_session))

    assert result["count"] == 0
    assert result["figures"] == []


# ---------------------------------------------------------------------------
# search_knowledge_base with available_figures
# ---------------------------------------------------------------------------


def _make_chunk_result(chunk_id=None, source="Donaldson"):
    chunk_id = chunk_id or uuid.uuid4()
    chunk = MagicMock()
    chunk.id = chunk_id
    chunk.content = "Some content"
    chunk.source = source
    chunk.chapter = "2"
    chunk.page = 42
    result = MagicMock()
    result.chunk = chunk
    result.similarity_score = 0.9
    return result


@pytest.mark.asyncio
async def test_search_knowledge_base_includes_available_figures(tool_executor, mock_retriever):
    chunk_id = uuid.uuid4()
    img_id = str(uuid.uuid4())
    mock_retriever.search_for_module.return_value = [_make_chunk_result(chunk_id=chunk_id)]
    mock_retriever.get_linked_images.return_value = {
        chunk_id: [
            {
                "id": img_id,
                "figure_number": "2.3",
                "caption": "Pyramide sanitaire",
                "image_type": "diagram",
            }
        ]
    }
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result = json.loads(
        await tool_executor._search_knowledge_base({"query": "pyramide sanitaire"}, mock_session)
    )

    assert "available_figures" in result
    assert len(result["available_figures"]) == 1
    fig = result["available_figures"][0]
    assert fig["figure_number"] == "2.3"
    assert f"{{{{source_image:{img_id}}}}}" == fig["ref"]


@pytest.mark.asyncio
async def test_search_knowledge_base_empty_figures(tool_executor, mock_retriever):
    mock_retriever.search_for_module.return_value = []
    mock_retriever.get_linked_images.return_value = {}
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result = json.loads(await tool_executor._search_knowledge_base({"query": "test"}, mock_session))

    assert result["available_figures"] == []


@pytest.mark.asyncio
async def test_search_knowledge_base_deduplicates_figures(tool_executor, mock_retriever):
    chunk_id1 = uuid.uuid4()
    chunk_id2 = uuid.uuid4()
    img_id = str(uuid.uuid4())

    mock_retriever.search_for_module.return_value = [
        _make_chunk_result(chunk_id=chunk_id1),
        _make_chunk_result(chunk_id=chunk_id2),
    ]
    shared_figure = {
        "id": img_id,
        "figure_number": "1.1",
        "caption": "Shared",
        "image_type": "diagram",
    }
    mock_retriever.get_linked_images.return_value = {
        chunk_id1: [shared_figure],
        chunk_id2: [shared_figure],
    }
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result = json.loads(await tool_executor._search_knowledge_base({"query": "test"}, mock_session))

    assert len(result["available_figures"]) == 1


# ---------------------------------------------------------------------------
# execute() dispatches search_source_images
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_dispatches_search_source_images(tool_executor, mock_retriever):
    mock_retriever.search_source_images.return_value = []
    mock_session = AsyncMock(spec=AsyncSession)

    result = json.loads(
        await tool_executor.execute("search_source_images", {"query": "test"}, mock_session)
    )

    assert "figures" in result
    mock_retriever.search_source_images.assert_awaited_once()


# ---------------------------------------------------------------------------
# DALL-E fallback: _find_source_image + generate_for_lesson
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_source_image_returns_none_when_no_lesson():
    from app.domain.services.image_service import ImageGenerationService

    svc = ImageGenerationService()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result = await svc._find_source_image(uuid.uuid4(), mock_session)
    assert result is None


@pytest.mark.asyncio
async def test_find_source_image_returns_none_when_no_sources():
    from app.domain.models.content import GeneratedContent
    from app.domain.services.image_service import ImageGenerationService

    svc = ImageGenerationService()
    lesson = MagicMock(spec=GeneratedContent)
    lesson.sources_cited = []
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=lesson)

    result = await svc._find_source_image(uuid.uuid4(), mock_session)
    assert result is None


@pytest.mark.asyncio
async def test_find_source_image_returns_none_when_no_linked_images():
    from app.domain.models.content import GeneratedContent
    from app.domain.services.image_service import ImageGenerationService

    svc = ImageGenerationService()
    chunk_id = uuid.uuid4()
    lesson = MagicMock(spec=GeneratedContent)
    lesson.sources_cited = [{"chunk_id": str(chunk_id)}]
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=lesson)

    mock_result = MagicMock()
    mock_result.first = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await svc._find_source_image(uuid.uuid4(), mock_session)
    assert result is None


@pytest.mark.asyncio
async def test_generate_for_lesson_skips_dalle_when_source_image_found():
    from app.domain.services.image_service import ImageGenerationService

    svc = ImageGenerationService()
    lesson_id = uuid.uuid4()

    mock_source_img = MagicMock()
    mock_source_img.figure_number = "2.1"
    mock_source_img.id = uuid.uuid4()
    mock_source_img.storage_url = "https://cdn.example.com/fig2.1.png"
    mock_source_img.alt_text_fr = "Diagramme"
    mock_source_img.alt_text_en = "Diagram"
    mock_source_img.width = 800
    mock_source_img.format = "png"

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    with (
        patch.object(
            svc, "_extract_concept_and_tags", AsyncMock(return_value=("concept", "prompt", ["tag"]))
        ),
        patch.object(svc, "_find_source_image", AsyncMock(return_value=mock_source_img)),
        patch.object(svc, "_call_dalle") as mock_dalle,
    ):
        img = await svc.generate_for_lesson(
            lesson_id=lesson_id,
            module_id=uuid.uuid4(),
            unit_id="u1",
            lesson_content="Some content",
            session=mock_session,
        )

    mock_dalle.assert_not_called()
    assert img.status == "ready"
    assert img.image_url == mock_source_img.storage_url


@pytest.mark.asyncio
async def test_generate_for_lesson_calls_dalle_when_no_source_image():
    from app.domain.services.image_service import ImageGenerationService

    svc = ImageGenerationService()
    lesson_id = uuid.uuid4()

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    fake_bytes = b"PNG_BYTES"

    with (
        patch.object(
            svc, "_extract_concept_and_tags", AsyncMock(return_value=("concept", "prompt", ["tag"]))
        ),
        patch.object(svc, "_find_source_image", AsyncMock(return_value=None)),
        patch.object(svc, "_find_reusable_image", AsyncMock(return_value=None)),
        patch.object(
            svc, "_call_dalle", AsyncMock(return_value=(fake_bytes, "http://x.com/img.png"))
        ),
        patch("app.domain.services.image_service._resize_to_webp", return_value=(fake_bytes, 512)),
        patch.object(svc, "_generate_alt_text", AsyncMock(return_value=("Alt FR", "Alt EN"))),
    ):
        img = await svc.generate_for_lesson(
            lesson_id=lesson_id,
            module_id=uuid.uuid4(),
            unit_id="u1",
            lesson_content="Some content",
            session=mock_session,
        )

    assert img.status == "ready"
    assert img.format == "webp"
