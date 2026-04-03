"""Tests for admin syllabus agent service and API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.syllabus_agent import (
    get_syllabus_agent_system_prompt,
    get_tool_definitions,
)
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.services.syllabus_agent_service import SyllabusAgentService
from app.main import app


@pytest.fixture
def mock_anthropic_client():
    return MagicMock()


@pytest.fixture
def mock_semantic_retriever():
    retriever = AsyncMock(spec=SemanticRetriever)
    retriever.retrieve = AsyncMock(return_value=[])
    return retriever


@pytest.fixture
def mock_embedding_service():
    return MagicMock(spec=EmbeddingService)


@pytest.fixture
def syllabus_service(mock_anthropic_client, mock_semantic_retriever, mock_embedding_service):
    return SyllabusAgentService(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_semantic_retriever,
        embedding_service=mock_embedding_service,
    )


class TestSyllabusAgentSystemPrompt:
    """Test the system prompt generator."""

    def test_prompt_includes_pedagogical_rules(self):
        prompt = get_syllabus_agent_system_prompt()
        assert "Bloom" in prompt or "bloom" in prompt
        assert "AOF" in prompt or "aof" in prompt.lower()
        assert "module" in prompt.lower()

    def test_prompt_includes_bilingual_requirement(self):
        prompt = get_syllabus_agent_system_prompt()
        assert "FR" in prompt or "français" in prompt.lower() or "french" in prompt.lower()
        assert "EN" in prompt or "english" in prompt.lower() or "anglais" in prompt.lower()

    def test_prompt_includes_activity_types(self):
        prompt = get_syllabus_agent_system_prompt()
        assert "quiz" in prompt.lower()
        assert "flashcard" in prompt.lower()
        assert "case_study" in prompt.lower() or "étude de cas" in prompt.lower()

    def test_prompt_includes_source_references(self):
        prompt = get_syllabus_agent_system_prompt()
        assert "donaldson" in prompt.lower() or "gordis" in prompt.lower()

    def test_prompt_is_non_empty(self):
        prompt = get_syllabus_agent_system_prompt()
        assert len(prompt) > 500


class TestSyllabusAgentToolDefinitions:
    """Test tool definitions for the syllabus agent."""

    def test_all_four_tools_defined(self):
        tools = get_tool_definitions()
        names = {t["name"] for t in tools}
        assert "get_existing_modules" in names
        assert "get_book_chapters" in names
        assert "search_knowledge_base" in names
        assert "save_module_draft" in names

    def test_get_existing_modules_has_no_required_params(self):
        tools = get_tool_definitions()
        tool = next(t for t in tools if t["name"] == "get_existing_modules")
        assert tool["input_schema"]["required"] == []

    def test_get_book_chapters_requires_book_name(self):
        tools = get_tool_definitions()
        tool = next(t for t in tools if t["name"] == "get_book_chapters")
        assert "book_name" in tool["input_schema"]["required"]

    def test_save_module_draft_requires_module_data(self):
        tools = get_tool_definitions()
        tool = next(t for t in tools if t["name"] == "save_module_draft")
        assert "module_data" in tool["input_schema"]["required"]


class TestSyllabusAgentService:
    """Test the syllabus agent service methods."""

    @pytest.mark.asyncio
    async def test_get_existing_modules_returns_list(self, syllabus_service):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(module_number=1, level=1, title_fr="Module 1 FR", title_en="Module 1 EN"),
            MagicMock(module_number=2, level=1, title_fr="Module 2 FR", title_en="Module 2 EN"),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await syllabus_service._tool_get_existing_modules(session=mock_session)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["module_number"] == 1
        assert result[0]["title_fr"] == "Module 1 FR"

    @pytest.mark.asyncio
    async def test_get_book_chapters_donaldson(self, syllabus_service):
        result = await syllabus_service._tool_get_book_chapters({"book_name": "donaldson"})
        assert isinstance(result, list)
        assert len(result) > 0
        assert all("chapter" in c and "title" in c for c in result)

    @pytest.mark.asyncio
    async def test_get_book_chapters_gordis(self, syllabus_service):
        result = await syllabus_service._tool_get_book_chapters({"book_name": "gordis"})
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_book_chapters_triola(self, syllabus_service):
        result = await syllabus_service._tool_get_book_chapters({"book_name": "triola"})
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_book_chapters_unknown_book(self, syllabus_service):
        result = await syllabus_service._tool_get_book_chapters({"book_name": "unknown_book"})
        assert result == []

    @pytest.mark.asyncio
    async def test_search_knowledge_base_empty_query(
        self, syllabus_service, mock_semantic_retriever
    ):
        mock_session = AsyncMock(spec=AsyncSession)
        result = await syllabus_service._tool_search_knowledge_base(
            {"query": ""}, session=mock_session
        )
        assert result == []
        mock_semantic_retriever.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_knowledge_base_with_query(
        self, syllabus_service, mock_semantic_retriever
    ):
        mock_session = AsyncMock(spec=AsyncSession)

        mock_chunk = MagicMock()
        mock_chunk.content = "Epidemiology is the study of disease distribution."
        mock_chunk.source = "gordis"
        mock_chunk.chapter = "1"
        mock_chunk.page = 10

        mock_result = MagicMock()
        mock_result.chunk = mock_chunk
        mock_result.score = 0.9

        mock_semantic_retriever.retrieve = AsyncMock(return_value=[mock_result])

        result = await syllabus_service._tool_search_knowledge_base(
            {"query": "epidemiology"}, session=mock_session
        )

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_save_module_draft_creates_new_module(self, syllabus_service):
        mock_session = AsyncMock(spec=AsyncSession)

        mock_num_result = MagicMock()
        mock_num_result.scalar.return_value = 16

        mock_session.execute = AsyncMock(return_value=mock_num_result)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        module_data = {
            "level": 2,
            "title_fr": "Épidémiologie avancée",
            "title_en": "Advanced Epidemiology",
            "description_fr": "Description FR",
            "description_en": "Description EN",
            "objectives_fr": ["Obj 1 FR", "Obj 2 FR"],
            "objectives_en": ["Obj 1 EN", "Obj 2 EN"],
            "estimated_hours": 20,
            "bloom_level": "analyze",
        }

        result = await syllabus_service._tool_save_module_draft(
            {"module_data": module_data},
            admin_id="admin-uuid",
            admin_email="admin@test.com",
            session=mock_session,
            existing_module_id=None,
        )

        assert "id" in result
        assert result["created"] is True
        assert "successfully" in result["message"].lower()
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_module_returns_markdown(self, syllabus_service):
        mock_session = AsyncMock(spec=AsyncSession)

        mock_module = MagicMock()
        mock_module.id = uuid.uuid4()
        mock_module.module_number = 5
        mock_module.level = 2
        mock_module.title_fr = "Surveillance épidémiologique"
        mock_module.title_en = "Epidemiological Surveillance"
        mock_module.description_fr = "Desc FR"
        mock_module.description_en = "Desc EN"
        mock_module.estimated_hours = 20
        mock_module.bloom_level = "analyze"
        mock_module.books_sources = {
            "objectives_fr": ["Obj 1"],
            "objectives_en": ["Obj 1 EN"],
            "key_contents_fr": ["Content 1"],
            "key_contents_en": ["Content 1 EN"],
            "aof_context_fr": "Contexte AOF",
            "aof_context_en": "AOF Context",
            "activities": {
                "quiz_topics": ["Topic 1"],
                "flashcard_count": 20,
                "case_study_scenario": "Ebola in Guinea",
            },
            "source_references": ["Gordis Ch.1"],
        }

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_module
        mock_session.execute = AsyncMock(return_value=mock_result)

        markdown = await syllabus_service.export_module_as_markdown(mock_module.id, mock_session)

        assert "M05" in markdown
        assert "Surveillance épidémiologique" in markdown
        assert "Epidemiological Surveillance" in markdown
        assert "Gordis Ch.1" in markdown

    @pytest.mark.asyncio
    async def test_export_module_not_found_returns_empty(self, syllabus_service):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await syllabus_service.export_module_as_markdown(uuid.uuid4(), mock_session)
        assert result == ""


class TestSyllabusAdminEndpoints:
    """Test admin endpoint access control."""

    @pytest.mark.asyncio
    async def test_list_modules_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/admin/syllabus")
            assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_agent_endpoint_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/admin/syllabus/agent",
                json={"message": "Create a new module"},
            )
            assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_agent_endpoint_rejects_non_admin_role(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/admin/syllabus/agent",
                json={"message": "Create a new module"},
                headers=auth_headers,
            )
            assert response.status_code == 403
