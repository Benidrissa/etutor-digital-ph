"""Tests for tutor source image tool and gpt-image-1 fallback optimization (issue #743)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.generated_image import GeneratedImage
from app.domain.models.source_image import SourceImage
from app.domain.services.image_service import ImageGenerationService
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source_image(
    image_type: str = "diagram",
    figure_number: str = "3.2",
    caption: str = "Disease transmission cycle",
    storage_url: str = "https://cdn.example.com/fig3.2.webp",
) -> SourceImage:
    img_id = uuid.uuid4()
    return SourceImage(
        id=img_id,
        source="donaldson",
        figure_number=figure_number,
        caption=caption,
        image_type=image_type,
        page_number=42,
        chapter="3",
        storage_url=storage_url,
        format="webp",
        width=512,
        height=400,
    )


def _make_generated_image(tags: list[str], status: str = "ready") -> GeneratedImage:
    img_id = uuid.uuid4()
    return GeneratedImage(
        id=img_id,
        status=status,
        semantic_tags=tags,
        image_url=f"/api/v1/images/{img_id}/data",
        image_data=b"fake-webp-data",
        alt_text_fr="Image FR",
        alt_text_en="Image EN",
        width=512,
        format="webp",
        file_size_bytes=14,
        reuse_count=0,
    )


# ---------------------------------------------------------------------------
# TOOL_DEFINITIONS — search_source_images is registered
# ---------------------------------------------------------------------------


def test_tool_definitions_include_search_source_images():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "search_source_images" in names


def test_search_source_images_tool_has_required_fields():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "search_source_images")
    assert "query" in tool["input_schema"]["required"]
    props = tool["input_schema"]["properties"]
    assert "query" in props
    assert "image_type" in props
    enum_vals = props["image_type"]["enum"]
    assert set(enum_vals) == {"diagram", "photo", "chart", "any"}


def test_tool_count_increased_to_six():
    assert len(TOOL_DEFINITIONS) == 6


# ---------------------------------------------------------------------------
# TutorToolExecutor._search_source_images
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_retriever():
    retriever = AsyncMock(spec=SemanticRetriever)
    retriever.search_for_module = AsyncMock(return_value=[])
    retriever.search_source_images = AsyncMock(return_value=[])
    retriever.get_linked_images = AsyncMock(return_value={})
    return retriever


@pytest.fixture
def tool_executor(mock_retriever):
    user_id = uuid.uuid4()
    return TutorToolExecutor(
        retriever=mock_retriever,
        anthropic_client=MagicMock(),
        user_id=user_id,
        user_level=2,
        user_language="fr",
    )


async def test_search_source_images_returns_figures(tool_executor, mock_retriever):
    img_id = str(uuid.uuid4())
    mock_retriever.search_source_images = AsyncMock(
        return_value=[
            {
                "id": img_id,
                "figure_number": "3.2",
                "caption": "Disease transmission cycle",
                "image_type": "diagram",
                "source": "donaldson",
                "chapter": "3",
                "page_number": 42,
                "similarity": 0.87,
            }
        ]
    )
    mock_session = AsyncMock(spec=AsyncSession)

    result_str = await tool_executor._search_source_images({"query": "transmission"}, mock_session)
    result = json.loads(result_str)

    assert result["query"] == "transmission"
    assert result["count"] == 1
    fig = result["figures"][0]
    assert fig["figure_number"] == "3.2"
    assert fig["caption"] == "Disease transmission cycle"
    assert fig["image_type"] == "diagram"
    assert f"{{{{source_image:{img_id}}}}}" in fig["ref"]


async def test_search_source_images_empty_query_returns_empty(tool_executor, mock_retriever):
    mock_retriever.search_source_images = AsyncMock(return_value=[])
    mock_session = AsyncMock(spec=AsyncSession)

    result_str = await tool_executor._search_source_images(
        {"query": "unknown concept xyz"}, mock_session
    )
    result = json.loads(result_str)

    assert result["count"] == 0
    assert result["figures"] == []


async def test_search_source_images_filters_by_image_type(tool_executor, mock_retriever):
    img_id = str(uuid.uuid4())
    mock_retriever.search_source_images = AsyncMock(
        return_value=[
            {
                "id": img_id,
                "figure_number": "1.1",
                "caption": "Epidemiology photo",
                "image_type": "photo",
                "source": "donaldson",
                "chapter": "1",
                "page_number": 10,
                "similarity": 0.75,
            }
        ]
    )
    mock_session = AsyncMock(spec=AsyncSession)

    result_str = await tool_executor._search_source_images(
        {"query": "surveillance", "image_type": "diagram"}, mock_session
    )
    result = json.loads(result_str)

    assert result["count"] == 0, "Photo should be filtered out when diagram requested"


async def test_search_source_images_any_type_returns_all(tool_executor, mock_retriever):
    img_id1 = str(uuid.uuid4())
    img_id2 = str(uuid.uuid4())
    mock_retriever.search_source_images = AsyncMock(
        return_value=[
            {
                "id": img_id1,
                "figure_number": "1.1",
                "caption": "Photo",
                "image_type": "photo",
                "source": "donaldson",
                "chapter": "1",
                "page_number": 10,
                "similarity": 0.8,
            },
            {
                "id": img_id2,
                "figure_number": "2.1",
                "caption": "Diagram",
                "image_type": "diagram",
                "source": "donaldson",
                "chapter": "2",
                "page_number": 20,
                "similarity": 0.75,
            },
        ]
    )
    mock_session = AsyncMock(spec=AsyncSession)

    result_str = await tool_executor._search_source_images(
        {"query": "health", "image_type": "any"}, mock_session
    )
    result = json.loads(result_str)

    assert result["count"] == 2


async def test_search_source_images_ref_format(tool_executor, mock_retriever):
    img_id = str(uuid.uuid4())
    mock_retriever.search_source_images = AsyncMock(
        return_value=[
            {
                "id": img_id,
                "figure_number": "5.3",
                "caption": "Chart",
                "image_type": "chart",
                "source": "triola",
                "chapter": "5",
                "page_number": 100,
                "similarity": 0.9,
            }
        ]
    )
    mock_session = AsyncMock(spec=AsyncSession)

    result_str = await tool_executor._search_source_images({"query": "statistics"}, mock_session)
    result = json.loads(result_str)

    fig = result["figures"][0]
    assert fig["ref"] == f"{{{{source_image:{img_id}}}}}"


async def test_execute_dispatches_search_source_images(tool_executor, mock_retriever):
    mock_retriever.search_source_images = AsyncMock(return_value=[])
    mock_session = AsyncMock(spec=AsyncSession)

    result_str = await tool_executor.execute(
        "search_source_images", {"query": "diagram"}, mock_session
    )
    result = json.loads(result_str)

    mock_retriever.search_source_images.assert_called_once()
    assert "figures" in result


# ---------------------------------------------------------------------------
# search_knowledge_base — available_figures in result
# ---------------------------------------------------------------------------


async def test_search_knowledge_base_includes_available_figures(tool_executor, mock_retriever):
    chunk_id = uuid.uuid4()
    img_id = str(uuid.uuid4())

    mock_chunk = MagicMock()
    mock_chunk.content = "Public health surveillance..."
    mock_chunk.source = "donaldson"
    mock_chunk.chapter = "4"
    mock_chunk.page = 89
    mock_chunk.id = chunk_id

    mock_result = MagicMock()
    mock_result.chunk = mock_chunk
    mock_result.similarity_score = 0.85

    mock_retriever.search_for_module = AsyncMock(return_value=[mock_result])
    mock_retriever.get_linked_images = AsyncMock(
        return_value={
            chunk_id: [
                {
                    "id": img_id,
                    "figure_number": "4.1",
                    "caption": "Surveillance network diagram",
                    "image_type": "diagram",
                }
            ]
        }
    )

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result_str = await tool_executor._search_knowledge_base({"query": "surveillance"}, mock_session)
    result = json.loads(result_str)

    assert "available_figures" in result
    assert len(result["available_figures"]) == 1
    fig = result["available_figures"][0]
    assert fig["figure_number"] == "4.1"
    assert fig["caption"] == "Surveillance network diagram"
    assert f"{{{{source_image:{img_id}}}}}" in fig["ref"]


async def test_search_knowledge_base_no_figures_when_none_linked(tool_executor, mock_retriever):
    chunk_id = uuid.uuid4()

    mock_chunk = MagicMock()
    mock_chunk.content = "Epidemiology basics..."
    mock_chunk.source = "donaldson"
    mock_chunk.chapter = "1"
    mock_chunk.page = 5
    mock_chunk.id = chunk_id

    mock_result = MagicMock()
    mock_result.chunk = mock_chunk
    mock_result.similarity_score = 0.72

    mock_retriever.search_for_module = AsyncMock(return_value=[mock_result])
    mock_retriever.get_linked_images = AsyncMock(return_value={chunk_id: []})

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result_str = await tool_executor._search_knowledge_base({"query": "epidemiology"}, mock_session)
    result = json.loads(result_str)

    assert result["available_figures"] == []


async def test_search_knowledge_base_deduplicates_figures(tool_executor, mock_retriever):
    chunk_id1 = uuid.uuid4()
    chunk_id2 = uuid.uuid4()
    img_id = str(uuid.uuid4())

    def make_chunk_result(chunk_id):
        mock_chunk = MagicMock()
        mock_chunk.content = "Content..."
        mock_chunk.source = "donaldson"
        mock_chunk.chapter = "4"
        mock_chunk.page = 89
        mock_chunk.id = chunk_id
        r = MagicMock()
        r.chunk = mock_chunk
        r.similarity_score = 0.8
        return r

    mock_retriever.search_for_module = AsyncMock(
        return_value=[make_chunk_result(chunk_id1), make_chunk_result(chunk_id2)]
    )
    mock_retriever.get_linked_images = AsyncMock(
        return_value={
            chunk_id1: [
                {"id": img_id, "figure_number": "4.1", "caption": "Fig", "image_type": "diagram"}
            ],
            chunk_id2: [
                {"id": img_id, "figure_number": "4.1", "caption": "Fig", "image_type": "diagram"}
            ],
        }
    )

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result_str = await tool_executor._search_knowledge_base({"query": "test"}, mock_session)
    result = json.loads(result_str)

    assert len(result["available_figures"]) == 1, "Same image should not appear twice"


# ---------------------------------------------------------------------------
# ImageGenerationService._find_source_image & DALL-E fallback
# ---------------------------------------------------------------------------


class TestFindSourceImage:
    @pytest.fixture
    def service(self):
        return ImageGenerationService()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        session.get = AsyncMock(return_value=None)
        return session

    async def test_returns_none_when_lesson_not_found(self, service, mock_session):
        mock_session.get = AsyncMock(return_value=None)
        result = await service._find_source_image(uuid.uuid4(), mock_session)
        assert result is None

    async def test_returns_none_when_no_sources_cited(self, service, mock_session):
        from app.domain.models.content import GeneratedContent

        lesson = MagicMock(spec=GeneratedContent)
        lesson.sources_cited = None
        mock_session.get = AsyncMock(return_value=lesson)

        result = await service._find_source_image(uuid.uuid4(), mock_session)
        assert result is None

    async def test_returns_none_when_sources_cited_empty(self, service, mock_session):
        from app.domain.models.content import GeneratedContent

        lesson = MagicMock(spec=GeneratedContent)
        lesson.sources_cited = []
        mock_session.get = AsyncMock(return_value=lesson)

        result = await service._find_source_image(uuid.uuid4(), mock_session)
        assert result is None

    async def test_returns_source_image_when_explicit_link_exists(self, service, mock_session):
        from app.domain.models.content import GeneratedContent

        lesson = MagicMock(spec=GeneratedContent)
        lesson.sources_cited = [{"source": "donaldson", "chapter": "3", "page": 42}]
        mock_session.get = AsyncMock(return_value=lesson)

        source_img = _make_source_image(image_type="diagram")
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none = MagicMock(return_value=source_img)
        mock_session.execute = AsyncMock(return_value=mock_execute_result)

        result = await service._find_source_image(uuid.uuid4(), mock_session)
        assert result is source_img

    async def test_returns_none_when_no_explicit_source_image(self, service, mock_session):
        from app.domain.models.content import GeneratedContent

        lesson = MagicMock(spec=GeneratedContent)
        lesson.sources_cited = [{"source": "triola", "chapter": "1", "page": 5}]
        mock_session.get = AsyncMock(return_value=lesson)

        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_execute_result)

        result = await service._find_source_image(uuid.uuid4(), mock_session)
        assert result is None


class TestDallEFallbackOptimization:
    @pytest.fixture
    def service(self):
        return ImageGenerationService()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        session.get = AsyncMock(return_value=None)
        return session

    @pytest.fixture
    def mock_claude_response(self):
        msg = MagicMock()
        content_block = MagicMock()
        content_block.text = (
            "CONCEPT: surveillance\n"
            "PROMPT: Disease surveillance network in West Africa\n"
            'TAGS: ["surveillance", "epidemiology", "aof"]'
        )
        msg.content = [content_block]
        return msg

    async def test_dalle_skipped_when_source_image_found(
        self, service, mock_session, mock_claude_response
    ):
        """When an explicit source image exists, DALL-E must NOT be called."""
        from app.domain.models.content import GeneratedContent

        source_img = _make_source_image(image_type="diagram", figure_number="3.2")

        lesson = MagicMock(spec=GeneratedContent)
        lesson.sources_cited = [{"source": "donaldson", "chapter": "3", "page": 42}]
        mock_session.get = AsyncMock(return_value=lesson)

        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = []

        source_result = MagicMock()
        source_result.scalar_one_or_none = MagicMock(return_value=source_img)

        mock_session.execute = AsyncMock(side_effect=[reuse_result, source_result])

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "anthropic.AsyncAnthropic"
        ) as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_claude_response)

            with __import__("unittest.mock", fromlist=["patch"]).patch(
                "openai.AsyncOpenAI"
            ) as mock_openai_cls:
                result = await service.generate_for_lesson(
                    lesson_id=uuid.uuid4(),
                    module_id=uuid.uuid4(),
                    unit_id="u01",
                    lesson_content="Lesson about disease surveillance in West Africa.",
                    session=mock_session,
                )

                mock_openai_cls.assert_not_called()

        assert result.status == "ready"
        assert source_img.storage_url in (result.image_url or "")

    async def test_dalle_called_when_no_source_image(
        self, service, mock_session, mock_claude_response
    ):
        """When no source image found, gpt-image-1 should proceed normally."""
        import base64
        from unittest.mock import patch

        mock_session.get = AsyncMock(return_value=None)

        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = []

        alt_text_msg = MagicMock()
        alt_text_msg.content = [MagicMock(text="FR: Illustration\nEN: Illustration")]

        fake_b64 = base64.b64encode(b"FAKE_PNG_DATA").decode()
        image_api_response = MagicMock()
        image_api_response.data = [MagicMock(b64_json=fake_b64)]

        mock_session.execute = AsyncMock(return_value=reuse_result)

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_claude_response, alt_text_msg]
            )

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                mock_openai = AsyncMock()
                mock_openai_cls.return_value = mock_openai
                mock_openai.images.generate = AsyncMock(return_value=image_api_response)

                result = await service.generate_for_lesson(
                    lesson_id=uuid.uuid4(),
                    module_id=uuid.uuid4(),
                    unit_id="u01",
                    lesson_content="Lesson about cholera outbreak.",
                    session=mock_session,
                )

            mock_openai.images.generate.assert_called_once()

        assert result.status == "ready"

    async def test_source_image_url_used_when_available(
        self, service, mock_session, mock_claude_response
    ):
        """Source image's storage_url must be used as image_url."""
        from app.domain.models.content import GeneratedContent

        source_img = _make_source_image(
            image_type="chart",
            storage_url="https://cdn.example.com/figures/fig1.webp",
        )

        lesson = MagicMock(spec=GeneratedContent)
        lesson.sources_cited = [{"source": "triola", "chapter": "5", "page": 90}]
        mock_session.get = AsyncMock(return_value=lesson)

        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = []

        source_result = MagicMock()
        source_result.scalar_one_or_none = MagicMock(return_value=source_img)

        mock_session.execute = AsyncMock(side_effect=[reuse_result, source_result])

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "anthropic.AsyncAnthropic"
        ) as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_claude_response)

            with __import__("unittest.mock", fromlist=["patch"]).patch("openai.AsyncOpenAI"):
                result = await service.generate_for_lesson(
                    lesson_id=uuid.uuid4(),
                    module_id=uuid.uuid4(),
                    unit_id="u01",
                    lesson_content="Statistics lesson with charts.",
                    session=mock_session,
                )

        assert result.image_url == "https://cdn.example.com/figures/fig1.webp"
        assert result.format == "webp"


# ---------------------------------------------------------------------------
# Tutor system prompt — source_image instructions
# ---------------------------------------------------------------------------


def test_tutor_prompt_mentions_search_source_images():
    from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt

    context = TutorContext(
        user_level=2,
        user_language="fr",
        user_country="SN",
    )
    prompt = get_socratic_system_prompt(context, [])
    assert "search_source_images" in prompt


def test_tutor_prompt_explains_source_image_marker():
    from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt

    context = TutorContext(
        user_level=2,
        user_language="fr",
        user_country="SN",
    )
    prompt = get_socratic_system_prompt(context, [])
    assert "source_image" in prompt
    assert "UUID" in prompt


def test_tutor_prompt_warns_against_inventing_uuid():
    from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt

    context = TutorContext(
        user_level=2,
        user_language="fr",
        user_country="SN",
    )
    prompt = get_socratic_system_prompt(context, [])
    assert "N'invente JAMAIS" in prompt or "Never invent" in prompt.lower() or "JAMAIS" in prompt
