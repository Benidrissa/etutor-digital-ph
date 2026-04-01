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

    mock_event = MagicMock()
    mock_event.type = "content_block_delta"
    mock_event.delta = MagicMock()
    mock_event.delta.text = "Bonjour! "

    mock_event2 = MagicMock()
    mock_event2.type = "content_block_delta"
    mock_event2.delta = MagicMock()
    mock_event2.delta.text = "Comment puis-je vous aider?"

    async def mock_stream_iter():
        yield mock_event
        yield mock_event2

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    mock_stream.__aiter__ = lambda self: mock_stream_iter()

    tutor_service.anthropic.messages.stream = MagicMock(return_value=mock_stream)

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
            "_retrieve_relevant_context",
            new_callable=AsyncMock,
            return_value=[],
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
    assert len(content_chunks) == 2
    assert content_chunks[0]["data"]["text"] == "Bonjour! "
    assert content_chunks[1]["data"]["text"] == "Comment puis-je vous aider?"


async def test_send_message_yields_sources_cited_type(
    tutor_service, sample_user, sample_conversation
):
    """Verify send_message yields chunks with type='sources_cited'."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    async def mock_stream_iter():
        return
        yield  # make it an async generator

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    mock_stream.__aiter__ = lambda self: mock_stream_iter()

    tutor_service.anthropic.messages.stream = MagicMock(return_value=mock_stream)

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
            "_retrieve_relevant_context",
            new_callable=AsyncMock,
            return_value=[],
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


async def test_list_conversations_returns_summaries(tutor_service, sample_user, sample_conversation):
    """Verify list_conversations returns conversation summaries with required fields."""
    mock_session = AsyncMock(spec=AsyncSession)

    with patch.object(
        mock_session,
        "execute",
        new_callable=AsyncMock,
    ) as mock_execute:
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = [sample_conversation]
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        mock_execute.side_effect = [scalars_result, count_result]

        result = await tutor_service.list_conversations(
            user_id=sample_user.id,
            session=mock_session,
        )

    assert "conversations" in result
    assert "total" in result
    assert result["total"] == 1
    assert len(result["conversations"]) == 1
    summary = result["conversations"][0]
    assert "id" in summary
    assert "message_count" in summary
    assert "last_message_at" in summary
    assert "preview" in summary


async def test_get_conversation_returns_none_for_wrong_user(tutor_service, sample_user):
    """Verify get_conversation returns None when conversation belongs to a different user."""
    mock_session = AsyncMock(spec=AsyncSession)
    other_conv_id = uuid.uuid4()

    with patch.object(
        mock_session,
        "execute",
        new_callable=AsyncMock,
    ) as mock_execute:
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_execute.return_value = result_mock

        result = await tutor_service.get_conversation(
            user_id=sample_user.id,
            conversation_id=other_conv_id,
            session=mock_session,
        )

    assert result is None


async def test_get_conversation_returns_messages(tutor_service, sample_user, sample_conversation):
    """Verify get_conversation returns full conversation with messages."""
    sample_conversation.messages = [
        {"role": "user", "content": "Bonjour", "timestamp": datetime.now(UTC).isoformat()},
        {
            "role": "assistant",
            "content": "Bonjour! Comment puis-je vous aider?",
            "sources": [],
            "timestamp": datetime.now(UTC).isoformat(),
        },
    ]
    mock_session = AsyncMock(spec=AsyncSession)

    with patch.object(
        mock_session,
        "execute",
        new_callable=AsyncMock,
    ) as mock_execute:
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = sample_conversation
        mock_execute.return_value = result_mock

        result = await tutor_service.get_conversation(
            user_id=sample_user.id,
            conversation_id=sample_conversation.id,
            session=mock_session,
        )

    assert result is not None
    assert result["id"] == sample_conversation.id
    assert len(result["messages"]) == 2


async def test_send_message_never_yields_text_type(tutor_service, sample_user, sample_conversation):
    """Regression test: ensure type='text' is never yielded (was the bug in #213)."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    mock_event = MagicMock()
    mock_event.type = "content_block_delta"
    mock_event.delta = MagicMock()
    mock_event.delta.text = "Test response"

    async def mock_stream_iter():
        yield mock_event

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    mock_stream.__aiter__ = lambda self: mock_stream_iter()

    tutor_service.anthropic.messages.stream = MagicMock(return_value=mock_stream)

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
            "_retrieve_relevant_context",
            new_callable=AsyncMock,
            return_value=[],
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
