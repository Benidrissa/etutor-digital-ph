"""Tests for AI tutor service — updated for tool_use API (messages.create)."""

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
    return MagicMock()


@pytest.fixture
def mock_semantic_retriever():
    retriever = AsyncMock(spec=SemanticRetriever)
    retriever.search_for_module = AsyncMock(return_value=[])
    return retriever


@pytest.fixture
def mock_embedding_service():
    return AsyncMock(spec=EmbeddingService)


@pytest.fixture
def tutor_service(mock_anthropic_client, mock_semantic_retriever, mock_embedding_service):
    return TutorService(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_semantic_retriever,
        embedding_service=mock_embedding_service,
    )


@pytest.fixture
def sample_user():
    return User(
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


@pytest.fixture
def sample_conversation(sample_user):
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[],
        created_at=datetime.now(UTC),
    )


async def collect_chunks(generator) -> list[dict]:
    chunks = []
    async for chunk in generator:
        chunks.append(chunk)
    return chunks


async def test_send_message_yields_content_type_chunks(
    tutor_service, sample_user, sample_conversation, mock_anthropic_client
):
    """Verify send_message yields chunks with type='content' for text tokens."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    text_block1 = MagicMock()
    text_block1.text = "Bonjour! "
    del text_block1.id

    text_block2 = MagicMock()
    text_block2.text = "Comment puis-je vous aider?"
    del text_block2.id

    mock_response = MagicMock()
    mock_response.content = [text_block1, text_block2]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

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
    tutor_service, sample_user, sample_conversation, mock_anthropic_client
):
    """Verify send_message yields chunks with type='sources_cited'."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    mock_response = MagicMock()
    mock_response.content = []
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

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


async def test_send_message_never_yields_text_type(
    tutor_service, sample_user, sample_conversation, mock_anthropic_client
):
    """Regression test: ensure type='text' is never yielded (was the bug in #213)."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    text_block = MagicMock()
    text_block.text = "Test response"
    del text_block.id

    mock_response = MagicMock()
    mock_response.content = [text_block]
    mock_anthropic_client.messages.create = AsyncMock(return_value=mock_response)

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
