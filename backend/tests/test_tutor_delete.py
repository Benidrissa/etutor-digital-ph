"""Tests for tutor conversation delete functionality."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.conversation import TutorConversation
from app.domain.models.user import User
from app.domain.services.learner_memory_service import LearnerMemoryService
from app.domain.services.tutor_service import TutorService


@pytest.fixture
def mock_anthropic_client():
    return MagicMock()


@pytest.fixture
def mock_semantic_retriever():
    return AsyncMock(spec=SemanticRetriever)


@pytest.fixture
def mock_embedding_service():
    return AsyncMock(spec=EmbeddingService)


@pytest.fixture
def mock_learner_memory_service():
    service = AsyncMock(spec=LearnerMemoryService)
    service.format_for_prompt = AsyncMock(return_value="")
    return service


@pytest.fixture
def tutor_service(
    mock_anthropic_client,
    mock_semantic_retriever,
    mock_embedding_service,
    mock_learner_memory_service,
):
    return TutorService(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_semantic_retriever,
        embedding_service=mock_embedding_service,
        learner_memory_service=mock_learner_memory_service,
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
        messages=[{"role": "user", "content": "Hello", "timestamp": datetime.now(UTC).isoformat()}],
        created_at=datetime.now(UTC),
    )


async def test_delete_conversation_returns_true_when_found(
    tutor_service, sample_user, sample_conversation
):
    """delete_conversation returns True when the conversation exists for the user."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_conversation
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    result = await tutor_service.delete_conversation(
        user_id=sample_user.id,
        conversation_id=sample_conversation.id,
        session=mock_session,
    )

    assert result is True
    mock_session.delete.assert_called_once_with(sample_conversation)
    mock_session.commit.assert_called_once()


async def test_delete_conversation_returns_false_when_not_found(tutor_service, sample_user):
    """delete_conversation returns False when the conversation does not exist."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await tutor_service.delete_conversation(
        user_id=sample_user.id,
        conversation_id=uuid.uuid4(),
        session=mock_session,
    )

    assert result is False
    mock_session.delete.assert_not_called()


async def test_delete_conversation_enforces_user_ownership(tutor_service, sample_conversation):
    """delete_conversation cannot delete another user's conversation."""
    other_user_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await tutor_service.delete_conversation(
        user_id=other_user_id,
        conversation_id=sample_conversation.id,
        session=mock_session,
    )

    assert result is False
    mock_session.delete.assert_not_called()


async def test_delete_conversation_accepts_string_user_id(
    tutor_service, sample_user, sample_conversation
):
    """delete_conversation works with string user_id (auto-converts to UUID)."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_conversation
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    result = await tutor_service.delete_conversation(
        user_id=str(sample_user.id),
        conversation_id=sample_conversation.id,
        session=mock_session,
    )

    assert result is True


async def test_delete_all_conversations_returns_count(
    tutor_service, sample_user, sample_conversation
):
    """delete_all_conversations returns the number of deleted conversations."""
    conv2 = TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[],
        created_at=datetime.now(UTC),
    )
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sample_conversation, conv2]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    count = await tutor_service.delete_all_conversations(
        user_id=sample_user.id,
        session=mock_session,
    )

    assert count == 2
    assert mock_session.delete.call_count == 2
    mock_session.commit.assert_called_once()


async def test_delete_all_conversations_returns_zero_when_none(tutor_service, sample_user):
    """delete_all_conversations returns 0 when user has no conversations."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    count = await tutor_service.delete_all_conversations(
        user_id=sample_user.id,
        session=mock_session,
    )

    assert count == 0
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_called_once()


async def test_delete_all_only_deletes_user_conversations(tutor_service, sample_user):
    """delete_all_conversations only queries conversations for the given user."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    await tutor_service.delete_all_conversations(
        user_id=sample_user.id,
        session=mock_session,
    )

    call_args = mock_session.execute.call_args[0][0]
    compiled = call_args.compile()
    query_str = str(compiled)
    assert "user_id" in query_str
