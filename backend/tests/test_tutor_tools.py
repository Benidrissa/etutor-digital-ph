"""Tests for agentic tutor tools (tool_use loop, each tool handler, max limit)."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.content import GeneratedContent
from app.domain.models.conversation import TutorConversation
from app.domain.models.learner_memory import LearnerMemory
from app.domain.models.user import User
from app.domain.services.learner_memory_service import LearnerMemoryService
from app.domain.services.tutor_service import (
    MAX_TOOL_CALLS,
    SessionContext,
    TutorService,
    _deduplicate_sources,
    _split_into_chunks,
)
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor


@pytest.fixture(autouse=True)
def _mock_subscription_service():
    with patch(
        "app.domain.services.tutor_service.SubscriptionService.get_active_subscription",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def collect_chunks(generator) -> list[dict]:
    chunks = []
    async for chunk in generator:
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_user():
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        name="Test User",
        preferred_language="fr",
        country="SN",
        professional_role="nurse",
        current_level=2,
        streak_days=0,
        last_active=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_conversation(sample_user):
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[],
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
def mock_anthropic():
    return MagicMock()


@pytest.fixture
def tool_executor(mock_retriever, mock_anthropic, sample_user):
    return TutorToolExecutor(
        retriever=mock_retriever,
        anthropic_client=mock_anthropic,
        user_id=sample_user.id,
        user_level=sample_user.current_level,
        user_language=sample_user.preferred_language,
    )


@pytest.fixture
def mock_learner_memory_service():
    service = AsyncMock(spec=LearnerMemoryService)
    service.format_for_prompt = AsyncMock(return_value="")
    return service


@pytest.fixture(autouse=True)
def mock_subscription_service():
    sub = MagicMock()
    sub.daily_message_limit = 20
    sub.message_credits = 0
    with patch("app.domain.services.tutor_service.SubscriptionService") as MockSubSvc:
        MockSubSvc.return_value.get_active_subscription = AsyncMock(return_value=sub)
        yield MockSubSvc


@pytest.fixture
def tutor_service(mock_retriever, mock_anthropic, mock_learner_memory_service):
    from app.ai.rag.embeddings import EmbeddingService

    embedding_service = AsyncMock(spec=EmbeddingService)
    svc = TutorService(
        anthropic_client=mock_anthropic,
        semantic_retriever=mock_retriever,
        embedding_service=embedding_service,
        learner_memory_service=mock_learner_memory_service,
    )
    svc.session_manager.build_session_context = AsyncMock(
        return_value=SessionContext(learner_memory="", is_new_conversation=True)
    )
    return svc


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def test_tool_definitions_count():
    assert len(TOOL_DEFINITIONS) == 6


def test_tool_names():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "search_source_images",
        "search_knowledge_base",
        "get_learner_progress",
        "generate_mini_quiz",
        "search_flashcards",
        "save_learner_preference",
    }


def test_each_tool_has_input_schema():
    for tool in TOOL_DEFINITIONS:
        assert "input_schema" in tool
        assert "properties" in tool["input_schema"]
        assert "required" in tool["input_schema"]


def test_search_knowledge_base_requires_query():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "search_knowledge_base")
    assert "query" in tool["input_schema"]["required"]


def test_get_learner_progress_requires_user_id():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_learner_progress")
    assert "user_id" in tool["input_schema"]["required"]


def test_generate_mini_quiz_required_fields():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "generate_mini_quiz")
    required = set(tool["input_schema"]["required"])
    assert {"topic", "num_questions", "difficulty"}.issubset(required)


def test_save_learner_preference_required_fields():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "save_learner_preference")
    required = set(tool["input_schema"]["required"])
    assert {"preference_type", "value"}.issubset(required)


# ---------------------------------------------------------------------------
# search_knowledge_base tool
# ---------------------------------------------------------------------------


async def test_search_knowledge_base_returns_results(tool_executor, mock_retriever):
    mock_chunk = MagicMock()
    mock_chunk.content = "Public health surveillance involves..."
    mock_chunk.source = "donaldson"
    mock_chunk.chapter = "4"
    mock_chunk.page = "89"

    mock_result = MagicMock()
    mock_result.chunk = mock_chunk
    mock_result.similarity_score = 0.85

    mock_retriever.search_for_module = AsyncMock(return_value=[mock_result])

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result_str = await tool_executor._search_knowledge_base({"query": "surveillance"}, mock_session)
    result = json.loads(result_str)

    assert result["query"] == "surveillance"
    assert result["count"] == 1
    assert result["results"][0]["source"] == "donaldson"
    assert result["results"][0]["similarity"] == 0.85


async def test_search_knowledge_base_empty_results(tool_executor, mock_retriever):
    mock_retriever.search_for_module = AsyncMock(return_value=[])
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result_str = await tool_executor._search_knowledge_base({"query": "xyz"}, mock_session)
    result = json.loads(result_str)

    assert result["count"] == 0
    assert result["results"] == []


# ---------------------------------------------------------------------------
# get_learner_progress tool
# ---------------------------------------------------------------------------


async def test_get_learner_progress_returns_structure(tool_executor):
    mock_session = AsyncMock(spec=AsyncSession)

    mock_progress_result = MagicMock()
    mock_progress_result.scalars.return_value.all.return_value = []

    mock_quiz_result = MagicMock()
    mock_quiz_result.scalars.return_value.all.return_value = []

    mock_placement_result = MagicMock()
    mock_placement_result.scalar_one_or_none.return_value = None

    mock_session.execute = AsyncMock(
        side_effect=[mock_progress_result, mock_quiz_result, mock_placement_result]
    )

    result_str = await tool_executor._get_learner_progress(
        {"user_id": str(tool_executor.user_id)}, mock_session
    )
    result = json.loads(result_str)

    assert "user_id" in result
    assert "current_level" in result
    assert "modules_progress" in result
    assert "completed_modules_count" in result
    assert "weak_domains" in result
    assert "recent_quiz_scores" in result
    assert result["current_level"] == 2


# ---------------------------------------------------------------------------
# generate_mini_quiz tool
# ---------------------------------------------------------------------------


async def test_generate_mini_quiz_returns_valid_json(tool_executor, mock_anthropic):
    quiz_json = json.dumps(
        {
            "topic": "surveillance",
            "questions": [
                {
                    "question": "What is epidemiological surveillance?",
                    "options": {"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"},
                    "correct_answer": "A",
                    "explanation": "Surveillance is systematic data collection.",
                }
            ],
        }
    )

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=quiz_json)]
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    result_str = await tool_executor._generate_mini_quiz(
        {"topic": "surveillance", "num_questions": 1, "difficulty": "medium"}
    )
    result = json.loads(result_str)

    assert result["topic"] == "surveillance"
    assert "questions" in result
    assert len(result["questions"]) == 1


async def test_generate_mini_quiz_handles_parse_error(tool_executor, mock_anthropic):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Not valid JSON here")]
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    result_str = await tool_executor._generate_mini_quiz(
        {"topic": "test", "num_questions": 2, "difficulty": "easy"}
    )
    result = json.loads(result_str)

    assert result["topic"] == "test"
    assert "parse_error" in result


# ---------------------------------------------------------------------------
# search_flashcards tool
# ---------------------------------------------------------------------------


async def test_search_flashcards_matches_concept(tool_executor):
    mock_session = AsyncMock(spec=AsyncSession)

    mock_card = MagicMock(spec=GeneratedContent)
    mock_card.id = uuid.uuid4()
    mock_card.module_id = uuid.uuid4()
    mock_card.content = {
        "term_fr": "surveillance épidémiologique",
        "term_en": "epidemiological surveillance",
        "definition_fr": "Collecte systématique de données sanitaires",
        "definition_en": "Systematic collection of health data",
    }

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_card]
    mock_session.execute = AsyncMock(return_value=mock_result)

    result_str = await tool_executor._search_flashcards({"concept": "surveillance"}, mock_session)
    result = json.loads(result_str)

    assert result["concept"] == "surveillance"
    assert result["count"] == 1
    assert result["flashcards"][0]["term_fr"] == "surveillance épidémiologique"


async def test_search_flashcards_no_match(tool_executor):
    mock_session = AsyncMock(spec=AsyncSession)

    mock_card = MagicMock(spec=GeneratedContent)
    mock_card.id = uuid.uuid4()
    mock_card.module_id = uuid.uuid4()
    mock_card.content = {
        "term_fr": "paludisme",
        "term_en": "malaria",
        "definition_fr": "Maladie parasitaire",
        "definition_en": "Parasitic disease",
    }

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_card]
    mock_session.execute = AsyncMock(return_value=mock_result)

    result_str = await tool_executor._search_flashcards({"concept": "vaccination"}, mock_session)
    result = json.loads(result_str)

    assert result["count"] == 0


# ---------------------------------------------------------------------------
# save_learner_preference tool
# ---------------------------------------------------------------------------


async def test_save_learner_preference_creates_new(tool_executor):
    mock_session = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    result_str = await tool_executor._save_learner_preference(
        {
            "preference_type": "preferred_explanation_style",
            "value": "analogies",
        },
        mock_session,
    )
    result = json.loads(result_str)

    assert result["saved"] is True
    assert result["preference_type"] == "preferred_explanation_style"
    assert result["updated"] is False


async def test_save_learner_preference_updates_existing(tool_executor):
    mock_session = AsyncMock(spec=AsyncSession)

    existing = MagicMock(spec=LearnerMemory)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    result_str = await tool_executor._save_learner_preference(
        {
            "preference_type": "preferred_explanation_style",
            "value": "examples",
        },
        mock_session,
    )
    result = json.loads(result_str)

    assert result["saved"] is True
    assert result["updated"] is True


# ---------------------------------------------------------------------------
# tool_use loop in TutorService
# ---------------------------------------------------------------------------


async def test_tool_use_loop_executes_tool_and_gets_final_response(
    tutor_service, sample_user, sample_conversation, mock_anthropic
):
    """Test that Claude returning tool_use blocks triggers tool execution and retry."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    tool_use_block = MagicMock()
    tool_use_block.__class__ = __import__("anthropic.types", fromlist=["ToolUseBlock"]).ToolUseBlock
    tool_use_block.name = "search_knowledge_base"
    tool_use_block.id = "tool_123"
    tool_use_block.input = {"query": "surveillance épidémiologique"}

    text_block = MagicMock()
    text_block.text = "Excellente réflexion! Que penses-tu..."
    del tool_use_block.__class__

    from anthropic.types import ToolUseBlock

    real_tool_use_block = MagicMock(spec=ToolUseBlock)
    real_tool_use_block.name = "search_knowledge_base"
    real_tool_use_block.id = "tool_123"
    real_tool_use_block.input = {"query": "surveillance"}

    first_response = MagicMock()
    first_response.content = [real_tool_use_block]

    second_response = MagicMock()
    final_text = MagicMock()
    final_text.text = "Excellente question!"
    del final_text.__class__

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    second_response.content = [FakeTextBlock("Excellente question! Penses-tu que...")]

    mock_anthropic.messages.create = AsyncMock(side_effect=[first_response, second_response])

    with (
        patch.object(
            tutor_service,
            "_check_daily_limit",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
        patch.object(
            tutor_service,
            "_get_previous_compact",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            tutor_service,
            "_resolve_course",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.domain.services.tutor_service.TutorToolExecutor") as mock_executor_cls,
    ):
        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(
            return_value=json.dumps({"query": "surveillance", "results": [], "count": 0})
        )
        mock_executor_cls.return_value = mock_executor

        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Qu'est-ce que la surveillance?",
                session=mock_session,
            )
        )

    chunk_types = [c["type"] for c in chunks]
    assert "tool_call" in chunk_types, f"Expected tool_call chunk, got: {chunk_types}"
    assert "content" in chunk_types, f"Expected content chunk, got: {chunk_types}"


async def test_max_tool_calls_enforced(
    tutor_service, sample_user, sample_conversation, mock_anthropic
):
    """Test that tool call loop stops at MAX_TOOL_CALLS."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    from anthropic.types import ToolUseBlock

    def make_tool_response():
        tool_block = MagicMock(spec=ToolUseBlock)
        tool_block.name = "search_knowledge_base"
        tool_block.id = f"tool_{uuid.uuid4().hex[:8]}"
        tool_block.input = {"query": "test"}
        resp = MagicMock()
        resp.content = [tool_block]
        return resp

    responses = [make_tool_response() for _ in range(MAX_TOOL_CALLS + 2)]
    mock_anthropic.messages.create = AsyncMock(side_effect=responses)

    with (
        patch.object(
            tutor_service,
            "_check_daily_limit",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
        patch.object(
            tutor_service,
            "_get_previous_compact",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            tutor_service,
            "_resolve_course",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.domain.services.tutor_service.TutorToolExecutor") as mock_executor_cls,
    ):
        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(
            return_value=json.dumps({"results": [], "count": 0, "query": "test"})
        )
        mock_executor_cls.return_value = mock_executor

        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Test",
                session=mock_session,
            )
        )

    tool_call_chunks = [c for c in chunks if c["type"] == "tool_call"]
    assert len(tool_call_chunks) <= MAX_TOOL_CALLS, (
        f"Expected at most {MAX_TOOL_CALLS} tool calls, got {len(tool_call_chunks)}"
    )
    assert mock_anthropic.messages.create.call_count <= MAX_TOOL_CALLS + 1


async def test_no_tool_use_yields_content_chunks(
    tutor_service, sample_user, sample_conversation, mock_anthropic
):
    """Test that when Claude returns no tool_use blocks, content is streamed."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    response = MagicMock()
    response.content = [FakeTextBlock("Excellente question! Penses-tu que la surveillance...")]
    mock_anthropic.messages.create = AsyncMock(return_value=response)

    with (
        patch.object(
            tutor_service,
            "_check_daily_limit",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
        patch.object(
            tutor_service,
            "_get_previous_compact",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            tutor_service,
            "_resolve_course",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Test message",
                session=mock_session,
            )
        )

    chunk_types = [c["type"] for c in chunks]
    assert "content" in chunk_types
    assert "text" not in chunk_types

    content_chunks = [c for c in chunks if c["type"] == "content"]
    full_text = "".join(c["data"]["text"] for c in content_chunks)
    assert "Excellente question!" in full_text


async def test_finished_chunk_includes_tool_calls_made(
    tutor_service, sample_user, sample_conversation, mock_anthropic
):
    """Test that finished chunk includes tool_calls_made count."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    response = MagicMock()
    response.content = [FakeTextBlock("Test response")]
    mock_anthropic.messages.create = AsyncMock(return_value=response)

    with (
        patch.object(
            tutor_service,
            "_check_daily_limit",
            new_callable=AsyncMock,
            return_value=5,
        ),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
        patch.object(
            tutor_service,
            "_get_previous_compact",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            tutor_service,
            "_resolve_course",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Test",
                session=mock_session,
            )
        )

    finished_chunks = [c for c in chunks if c["type"] == "finished"]
    assert len(finished_chunks) == 1
    assert "tool_calls_made" in finished_chunks[0]["data"]
    assert finished_chunks[0]["data"]["remaining_messages"] == 14


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def test_split_into_chunks_empty():
    assert _split_into_chunks("") == []


def test_split_into_chunks_small_text():
    result = _split_into_chunks("Hello", chunk_size=50)
    assert result == ["Hello"]
    assert "".join(result) == "Hello"


def test_split_into_chunks_large_text():
    text = "A" * 120
    chunks = _split_into_chunks(text, chunk_size=50)
    assert len(chunks) == 3
    assert "".join(chunks) == text


def test_deduplicate_sources_removes_duplicates():
    sources = [
        {"source": "donaldson", "chapter": "4", "page": "89"},
        {"source": "donaldson", "chapter": "4", "page": "89"},
        {"source": "triola", "chapter": "2", "page": "45"},
    ]
    unique = _deduplicate_sources(sources)
    assert len(unique) == 2


def test_deduplicate_sources_respects_limit():
    sources = [{"source": f"book_{i}", "chapter": str(i), "page": str(i)} for i in range(10)]
    unique = _deduplicate_sources(sources)
    assert len(unique) == 5


# ---------------------------------------------------------------------------
# Tool executor error handling
# ---------------------------------------------------------------------------


async def test_tool_executor_unknown_tool(tool_executor):
    mock_session = AsyncMock(spec=AsyncSession)
    result_str = await tool_executor.execute("unknown_tool", {}, mock_session)
    result = json.loads(result_str)
    assert "error" in result
    assert "Unknown tool" in result["error"]


async def test_tool_executor_handles_exception(tool_executor, mock_retriever):
    mock_retriever.search_for_module = AsyncMock(side_effect=RuntimeError("DB error"))
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=None)

    result_str = await tool_executor.execute(
        "search_knowledge_base", {"query": "test"}, mock_session
    )
    result = json.loads(result_str)
    assert "error" in result
