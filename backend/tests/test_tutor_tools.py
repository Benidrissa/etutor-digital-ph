"""Tests for the agentic tutor tools: tool definitions, executor, and tool_use loop."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retriever import SearchResult, SemanticRetriever
from app.domain.models.content import GeneratedContent
from app.domain.models.conversation import TutorConversation
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.learner_memory import LearnerMemory
from app.domain.models.quiz import QuizAttempt
from app.domain.models.user import User
from app.domain.services.tutor_service import MAX_TOOL_CALLS, TutorService
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_user_id():
    return uuid.uuid4()


@pytest.fixture
def sample_user(sample_user_id):
    return User(
        id=sample_user_id,
        email="tutor@example.com",
        name="Tutor Test",
        preferred_language="fr",
        country="SN",
        professional_role="nurse",
        current_level=2,
        streak_days=0,
        last_active=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_conversation(sample_user_id):
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user_id,
        module_id=None,
        messages=[],
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_anthropic_client():
    return MagicMock()


@pytest.fixture
def mock_retriever():
    r = AsyncMock(spec=SemanticRetriever)
    r.search_for_module = AsyncMock(return_value=[])
    return r


@pytest.fixture
def mock_session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    return s


@pytest.fixture
def tool_executor(mock_anthropic_client, mock_retriever, sample_user_id, mock_session):
    return TutorToolExecutor(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_retriever,
        user_id=sample_user_id,
        user_level=2,
        user_language="fr",
        module_id=None,
        session=mock_session,
    )


@pytest.fixture
def tutor_service(mock_anthropic_client, mock_retriever):
    from app.ai.rag.embeddings import EmbeddingService

    embedding_service = AsyncMock(spec=EmbeddingService)
    return TutorService(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_retriever,
        embedding_service=embedding_service,
    )


async def collect_chunks(generator) -> list[dict]:
    chunks = []
    async for chunk in generator:
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def test_tool_definitions_have_five_tools():
    assert len(TOOL_DEFINITIONS) == 5


def test_tool_definitions_names():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "search_knowledge_base",
        "get_learner_progress",
        "generate_mini_quiz",
        "search_flashcards",
        "save_learner_preference",
    }


def test_tool_definitions_have_required_fields():
    for tool in TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_search_knowledge_base_schema():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "search_knowledge_base")
    assert "query" in tool["input_schema"]["required"]
    assert "query" in tool["input_schema"]["properties"]


def test_generate_mini_quiz_schema():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "generate_mini_quiz")
    required = tool["input_schema"]["required"]
    assert "topic" in required
    assert "num_questions" in required
    assert "difficulty" in required
    diff_enum = tool["input_schema"]["properties"]["difficulty"]["enum"]
    assert set(diff_enum) == {"easy", "medium", "hard"}


# ---------------------------------------------------------------------------
# TutorToolExecutor.execute dispatch
# ---------------------------------------------------------------------------


async def test_execute_unknown_tool_returns_error(tool_executor):
    result_json = await tool_executor.execute("unknown_tool", {})
    result = json.loads(result_json)
    assert "error" in result


async def test_execute_dispatches_to_correct_handler(tool_executor):
    tool_executor._search_knowledge_base = AsyncMock(return_value={"results": []})
    result_json = await tool_executor.execute("search_knowledge_base", {"query": "malaria"})
    result = json.loads(result_json)
    tool_executor._search_knowledge_base.assert_called_once_with(query="malaria")
    assert "results" in result


# ---------------------------------------------------------------------------
# search_knowledge_base
# ---------------------------------------------------------------------------


async def test_search_knowledge_base_returns_results(tool_executor, mock_retriever):
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        content="Malaria is endemic in West Africa.",
        source="donaldson",
        chapter=5,
        page=120,
        level=2,
        language="en",
        token_count=10,
        chunk_index=0,
        created_at=datetime.now(UTC),
        embedding=None,
    )
    mock_retriever.search_for_module.return_value = [
        SearchResult(chunk=chunk, similarity_score=0.9)
    ]

    result_json = await tool_executor.execute("search_knowledge_base", {"query": "malaria"})
    result = json.loads(result_json)

    assert result["total"] == 1
    assert result["results"][0]["source"] == "donaldson"
    assert result["results"][0]["similarity"] == 0.9


async def test_search_knowledge_base_empty_results(tool_executor, mock_retriever):
    mock_retriever.search_for_module.return_value = []
    result_json = await tool_executor.execute("search_knowledge_base", {"query": "unknown topic"})
    result = json.loads(result_json)
    assert result["total"] == 0
    assert result["results"] == []


# ---------------------------------------------------------------------------
# get_learner_progress
# ---------------------------------------------------------------------------


async def test_get_learner_progress_with_no_data(tool_executor, mock_session, sample_user_id):
    mock_session.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result_json = await tool_executor.execute(
        "get_learner_progress", {"user_id": str(sample_user_id)}
    )
    result = json.loads(result_json)

    assert result["current_level"] == 2
    assert result["completed_modules"] == []
    assert result["recent_quiz_scores"] == []
    assert result["average_quiz_score"] is None


async def test_get_learner_progress_with_quiz_data(tool_executor, mock_session, sample_user_id):
    mock_execute_calls = []

    quiz_id = uuid.uuid4()
    quiz_attempt = QuizAttempt(
        id=uuid.uuid4(),
        user_id=sample_user_id,
        quiz_id=quiz_id,
        answers={},
        score=85.0,
        attempted_at=datetime.now(UTC),
    )

    progress_result = MagicMock()
    progress_result.scalars.return_value.all.return_value = []

    quiz_result = MagicMock()
    quiz_result.scalars.return_value.all.return_value = [quiz_attempt]

    placement_result = MagicMock()
    placement_result.scalar_one_or_none.return_value = None

    mock_execute_calls.extend([progress_result, quiz_result, placement_result])
    mock_session.execute = AsyncMock(side_effect=mock_execute_calls)

    result_json = await tool_executor.execute(
        "get_learner_progress", {"user_id": str(sample_user_id)}
    )
    result = json.loads(result_json)

    assert len(result["recent_quiz_scores"]) == 1
    assert result["recent_quiz_scores"][0]["score"] == 85.0
    assert result["average_quiz_score"] == 85.0


# ---------------------------------------------------------------------------
# generate_mini_quiz
# ---------------------------------------------------------------------------


async def test_generate_mini_quiz_calls_claude(tool_executor, mock_anthropic_client):
    quiz_json = json.dumps(
        {
            "questions": [
                {
                    "question": "What is public health?",
                    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
                    "correct": "A",
                    "explanation": "...",
                }
            ]
        }
    )

    mock_text_block = MagicMock()
    mock_text_block.text = quiz_json
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    result_json = await tool_executor.execute(
        "generate_mini_quiz",
        {"topic": "public health", "num_questions": 2, "difficulty": "easy"},
    )
    result = json.loads(result_json)

    assert result["topic"] == "public health"
    assert result["difficulty"] == "easy"
    assert len(result["questions"]) == 1
    mock_anthropic_client.messages.create.assert_called_once()


async def test_generate_mini_quiz_handles_invalid_json(tool_executor, mock_anthropic_client):
    mock_text_block = MagicMock()
    mock_text_block.text = "Invalid JSON response from Claude"
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    result_json = await tool_executor.execute(
        "generate_mini_quiz",
        {"topic": "epidemiology", "num_questions": 2, "difficulty": "medium"},
    )
    result = json.loads(result_json)

    assert result["questions"] == []


async def test_generate_mini_quiz_clamps_num_questions(tool_executor, mock_anthropic_client):
    mock_text_block = MagicMock()
    mock_text_block.text = '{"questions": []}'
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    call_args = {}

    async def capture_call(**kwargs):
        call_args.update(kwargs)
        return mock_response

    mock_anthropic_client.messages.create = AsyncMock(side_effect=capture_call)

    await tool_executor.execute(
        "generate_mini_quiz",
        {"topic": "test", "num_questions": 10, "difficulty": "hard"},
    )

    prompt_text = call_args["messages"][0]["content"]
    assert "3" in prompt_text


# ---------------------------------------------------------------------------
# search_flashcards
# ---------------------------------------------------------------------------


async def test_search_flashcards_matches_concept(tool_executor, mock_session):
    module_id = uuid.uuid4()
    fc = GeneratedContent(
        id=uuid.uuid4(),
        module_id=module_id,
        content_type="flashcard",
        language="fr",
        level=1,
        content={
            "term_fr": "paludisme",
            "definition_fr": "Maladie tropicale transmise par les moustiques",
        },
        sources_cited=[],
        generated_at=datetime.now(UTC),
        validated=False,
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [fc]
    mock_session.execute = AsyncMock(return_value=mock_result)

    result_json = await tool_executor.execute("search_flashcards", {"concept": "paludisme"})
    result = json.loads(result_json)

    assert result["total_found"] == 1
    assert result["flashcards"][0]["term"] == "paludisme"


async def test_search_flashcards_no_match(tool_executor, mock_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    result_json = await tool_executor.execute("search_flashcards", {"concept": "unknown concept"})
    result = json.loads(result_json)

    assert result["total_found"] == 0
    assert result["flashcards"] == []


# ---------------------------------------------------------------------------
# save_learner_preference
# ---------------------------------------------------------------------------


async def test_save_learner_preference_creates_new(tool_executor, mock_session, sample_user_id):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    result_json = await tool_executor.execute(
        "save_learner_preference",
        {"preference_type": "learning_style", "value": "analogies"},
    )
    result = json.loads(result_json)

    assert result["saved"] is True
    assert result["preference_type"] == "learning_style"
    assert result["value"] == "analogies"
    assert result["action"] == "created"
    mock_session.add.assert_called_once()


async def test_save_learner_preference_updates_existing(
    tool_executor, mock_session, sample_user_id
):
    existing = LearnerMemory(
        id=uuid.uuid4(),
        user_id=sample_user_id,
        preference_type="learning_style",
        value="formal",
        updated_at=datetime.now(UTC),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_session.execute = AsyncMock(return_value=mock_result)

    result_json = await tool_executor.execute(
        "save_learner_preference",
        {"preference_type": "learning_style", "value": "analogies"},
    )
    result = json.loads(result_json)

    assert result["action"] == "updated"
    assert existing.value == "analogies"


# ---------------------------------------------------------------------------
# TutorService tool_use loop
# ---------------------------------------------------------------------------


async def test_tool_use_loop_no_tools_returns_content(
    tutor_service, sample_user, sample_conversation, mock_anthropic_client
):
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    text_block = MagicMock()
    text_block.text = "Voici ma réponse socratique."
    del text_block.id

    mock_response = MagicMock()
    mock_response.content = [text_block]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
    ):
        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Qu'est-ce que la santé publique?",
                session=mock_session,
            )
        )

    content_chunks = [c for c in chunks if c["type"] == "content"]
    assert len(content_chunks) == 1
    assert content_chunks[0]["data"]["text"] == "Voici ma réponse socratique."
    mock_anthropic_client.messages.create.assert_called_once()


async def test_tool_use_loop_executes_tool_and_continues(
    tutor_service, sample_user, sample_conversation, mock_anthropic_client
):
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    tool_block = MagicMock(spec=["name", "id", "input", "__class__"])
    tool_block.__class__ = __import__("anthropic.types", fromlist=["ToolUseBlock"]).ToolUseBlock
    tool_block.name = "search_knowledge_base"
    tool_block.id = "toolu_01"
    tool_block.input = {"query": "malaria"}

    text_block = MagicMock()
    text_block.text = "Basé sur les sources..."
    del text_block.id

    first_response = MagicMock()
    first_response.content = [tool_block]

    second_response = MagicMock()
    second_response.content = [text_block]

    mock_anthropic_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
        patch(
            "app.domain.services.tutor_service.TutorToolExecutor.execute",
            new_callable=AsyncMock,
            return_value=json.dumps({"results": [], "total": 0}),
        ),
    ):
        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Tell me about malaria",
                session=mock_session,
            )
        )

    assert mock_anthropic_client.messages.create.call_count == 2

    tool_call_chunks = [c for c in chunks if c["type"] == "tool_call"]
    assert len(tool_call_chunks) == 1
    assert tool_call_chunks[0]["data"]["tool_name"] == "search_knowledge_base"

    content_chunks = [c for c in chunks if c["type"] == "content"]
    assert len(content_chunks) == 1


async def test_tool_use_loop_max_calls_enforced(
    tutor_service, sample_user, sample_conversation, mock_anthropic_client
):
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    from anthropic.types import ToolUseBlock

    def make_tool_response():
        tool_block = MagicMock(spec=ToolUseBlock)
        tool_block.__class__ = ToolUseBlock
        tool_block.name = "search_knowledge_base"
        tool_block.id = f"toolu_{uuid.uuid4().hex[:8]}"
        tool_block.input = {"query": "test"}
        mock_resp = MagicMock()
        mock_resp.content = [tool_block]
        return mock_resp

    responses = [make_tool_response() for _ in range(MAX_TOOL_CALLS + 2)]
    mock_anthropic_client.messages.create = AsyncMock(side_effect=responses)

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
        patch(
            "app.domain.services.tutor_service.TutorToolExecutor.execute",
            new_callable=AsyncMock,
            return_value=json.dumps({"results": []}),
        ),
    ):
        await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="test message",
                session=mock_session,
            )
        )

    assert mock_anthropic_client.messages.create.call_count <= MAX_TOOL_CALLS + 1


async def test_send_message_daily_limit_error(tutor_service, sample_user):
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    with patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=50):
        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="test",
                session=mock_session,
            )
        )

    error_chunks = [c for c in chunks if c["type"] == "error"]
    assert len(error_chunks) == 1
    assert error_chunks[0]["data"]["code"] == "limit_reached"


async def test_send_message_error_chunk_has_code(tutor_service, sample_user):
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ),
    ):
        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="test",
                session=mock_session,
            )
        )

    error_chunks = [c for c in chunks if c["type"] == "error"]
    assert len(error_chunks) == 1
    assert error_chunks[0]["data"]["code"] == "tutor_error"


async def test_finished_chunk_includes_tool_calls_used(
    tutor_service, sample_user, sample_conversation, mock_anthropic_client
):
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    text_block = MagicMock()
    text_block.text = "Réponse."
    del text_block.id

    mock_response = MagicMock()
    mock_response.content = [text_block]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
    ):
        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="test",
                session=mock_session,
            )
        )

    finished_chunks = [c for c in chunks if c["type"] == "finished"]
    assert len(finished_chunks) == 1
    assert "tool_calls_used" in finished_chunks[0]["data"]
    assert finished_chunks[0]["data"]["tool_calls_used"] == 0
