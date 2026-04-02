"""Tests for AI tutor service SSE streaming and error handling."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.conversation import TutorConversation
from app.domain.models.user import User
from app.domain.services.tutor_service import TutorService


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic async client."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_semantic_retriever():
    """Mock semantic retriever that returns empty results."""
    retriever = AsyncMock(spec=SemanticRetriever)
    retriever.search_for_module = AsyncMock(return_value=[])
    return retriever


@pytest.fixture
def mock_embedding_service():
    """Mock embedding service."""
    service = AsyncMock(spec=EmbeddingService)
    return service


@pytest.fixture
def tutor_service(mock_anthropic_client, mock_semantic_retriever, mock_embedding_service):
    """TutorService with mocked dependencies."""
    return TutorService(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_semantic_retriever,
        embedding_service=mock_embedding_service,
    )


@pytest.fixture
def sample_user():
    """Sample user for testing."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        name="Test User",
        preferred_language="fr",
        country="SN",
        professional_role="nurse",
        current_level=1,
        streak_days=0,
        last_active=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    return user


@pytest.fixture
def sample_conversation(sample_user):
    """Sample conversation for testing."""
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[],
        created_at=datetime.now(UTC),
    )


async def collect_chunks(generator) -> list[dict]:
    """Collect all chunks from an async generator."""
    chunks = []
    async for chunk in generator:
        chunks.append(chunk)
    return chunks


async def test_send_message_yields_content_type_chunks(
    tutor_service, sample_user, sample_conversation
):
    """Verify send_message yields chunks with type='content' for text tokens."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    mock_response = MagicMock()
    mock_response.content = [FakeTextBlock("Bonjour! Comment puis-je vous aider?")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_response)

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
    ):
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Expliquer la santé publique",
                session=mock_session,
            )
        )

    chunk_types = [c["type"] for c in chunks]
    assert "content" in chunk_types, f"Expected 'content' type in chunks but got: {chunk_types}"

    content_chunks = [c for c in chunks if c["type"] == "content"]
    full_text = "".join(c["data"]["text"] for c in content_chunks)
    assert "Bonjour!" in full_text


async def test_send_message_yields_sources_cited_type(
    tutor_service, sample_user, sample_conversation
):
    """Verify send_message yields chunks with type='sources_cited'."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    mock_response = MagicMock()
    mock_response.content = [FakeTextBlock("Test response")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_response)

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
    assert "sources_cited" in chunk_types, (
        f"Expected 'sources_cited' type in chunks but got: {chunk_types}"
    )


async def test_send_message_error_chunk_has_code(tutor_service, sample_user):
    """Verify error chunks include a 'code' field for i18n."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

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
            side_effect=RuntimeError("DB connection error"),
        ),
    ):
        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Test message",
                session=mock_session,
            )
        )

    error_chunks = [c for c in chunks if c["type"] == "error"]
    assert len(error_chunks) == 1, f"Expected 1 error chunk, got: {chunks}"
    assert "code" in error_chunks[0]["data"], (
        "Error chunk must include 'code' for frontend i18n translation"
    )
    assert error_chunks[0]["data"]["code"] == "tutor_error"


async def test_send_message_daily_limit_error_has_code(tutor_service, sample_user):
    """Verify daily limit error includes code='limit_reached'."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    with patch.object(
        tutor_service,
        "_check_daily_limit",
        new_callable=AsyncMock,
        return_value=50,
    ):
        chunks = await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Test message",
                session=mock_session,
            )
        )

    error_chunks = [c for c in chunks if c["type"] == "error"]
    assert len(error_chunks) == 1
    assert error_chunks[0]["data"]["code"] == "limit_reached"
    assert error_chunks[0]["data"]["limit_reached"] is True


async def test_send_message_never_yields_text_type(tutor_service, sample_user, sample_conversation):
    """Regression test: ensure type='text' is never yielded (was the bug in #213)."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    mock_response = MagicMock()
    mock_response.content = [FakeTextBlock("Test response")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_response)

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

    text_type_chunks = [c for c in chunks if c["type"] == "text"]
    assert len(text_type_chunks) == 0, (
        "Bug #213 regression: type='text' chunks were yielded but frontend expects type='content'"
    )


async def test_list_conversations_returns_expected_fields(
    tutor_service, sample_user, sample_conversation
):
    """list_conversations returns dicts with required fields for the sidebar."""
    mock_session = AsyncMock(spec=AsyncSession)

    from unittest.mock import MagicMock

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [sample_conversation]

    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 1

    execute_results = [MagicMock(), MagicMock()]
    execute_results[0].scalars.return_value = mock_scalars
    execute_results[1].scalar.return_value = 1

    call_count = 0

    async def fake_execute(_query):
        nonlocal call_count
        result = execute_results[call_count]
        call_count += 1
        return result

    mock_session.execute = fake_execute

    result = await tutor_service.list_conversations(
        user_id=sample_user.id,
        session=mock_session,
    )

    assert "conversations" in result
    assert "total" in result
    assert result["total"] == 1
    assert len(result["conversations"]) == 1
    conv = result["conversations"][0]
    for field in ("id", "message_count", "last_message_at", "preview"):
        assert field in conv, f"Missing field '{field}' in conversation summary"


async def test_get_conversation_returns_none_for_wrong_user(
    tutor_service, sample_user, sample_conversation
):
    """get_conversation returns None when conversation belongs to a different user."""
    other_user_id = uuid.uuid4()
    mock_session = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await tutor_service.get_conversation(
        user_id=other_user_id,
        conversation_id=sample_conversation.id,
        session=mock_session,
    )

    assert result is None


async def test_get_conversation_returns_messages(
    tutor_service, sample_user, sample_conversation
):
    """get_conversation returns full conversation with messages list."""
    from datetime import UTC, datetime

    sample_conversation.messages = [
        {"role": "user", "content": "Hello", "timestamp": datetime.now(UTC).isoformat()},
        {"role": "assistant", "content": "Hi!", "timestamp": datetime.now(UTC).isoformat()},
    ]

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_conversation
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await tutor_service.get_conversation(
        user_id=sample_user.id,
        conversation_id=sample_conversation.id,
        session=mock_session,
    )

    assert result is not None
    assert result["id"] == sample_conversation.id
    assert "messages" in result
    assert len(result["messages"]) == 2
