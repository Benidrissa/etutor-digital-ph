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
from app.domain.services.learner_memory_service import LearnerMemoryService
from app.domain.services.subscription_service import SubscriptionService
from app.domain.services.tutor_service import SessionContext, TutorService


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
def mock_learner_memory_service():
    """Mock LearnerMemoryService."""
    service = AsyncMock(spec=LearnerMemoryService)
    service.format_for_prompt = AsyncMock(return_value="")
    return service


@pytest.fixture(autouse=True)
def mock_subscription_service():
    """Auto-mock SubscriptionService for all tutor tests."""
    sub = MagicMock()
    sub.daily_message_limit = 20
    sub.message_credits = 0
    with patch("app.domain.services.tutor_service.SubscriptionService") as MockSubSvc:
        MockSubSvc.return_value.get_active_subscription = AsyncMock(return_value=sub)
        yield MockSubSvc


@pytest.fixture
def tutor_service(
    mock_anthropic_client,
    mock_semantic_retriever,
    mock_embedding_service,
    mock_learner_memory_service,
):
    """TutorService with mocked dependencies."""
    svc = TutorService(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_semantic_retriever,
        embedding_service=mock_embedding_service,
        learner_memory_service=mock_learner_memory_service,
    )
    svc.session_manager.build_session_context = AsyncMock(
        return_value=SessionContext(learner_memory="", is_new_conversation=True)
    )
    return svc


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
            SubscriptionService,
            "get_active_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
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
            SubscriptionService,
            "get_active_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
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
    assert "sources_cited" in chunk_types, (
        f"Expected 'sources_cited' type in chunks but got: {chunk_types}"
    )


async def test_send_message_error_chunk_has_code(tutor_service, sample_user):
    """Verify error chunks include a 'code' field for i18n."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    with (
        patch.object(
            SubscriptionService,
            "get_active_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
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

    with (
        patch.object(
            SubscriptionService,
            "get_active_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            tutor_service,
            "_check_daily_limit",
            new_callable=AsyncMock,
            return_value=50,
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
            SubscriptionService,
            "get_active_subscription",
            new_callable=AsyncMock,
            return_value=None,
        ),
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
                message="Test",
                session=mock_session,
            )
        )

    text_type_chunks = [c for c in chunks if c["type"] == "text"]
    assert len(text_type_chunks) == 0, (
        "Bug #213 regression: type='text' chunks were yielded but frontend expects type='content'"
    )


async def test_list_conversations_returns_required_fields(
    tutor_service, sample_user, sample_conversation
):
    """list_conversations must return id, message_count, last_message_at, preview."""
    mock_session = AsyncMock(spec=AsyncSession)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sample_conversation]
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 1
    mock_session.execute = AsyncMock(side_effect=[mock_result, mock_count_result])

    result = await tutor_service.list_conversations(
        user_id=sample_user.id,
        session=mock_session,
    )

    assert "conversations" in result
    assert "total" in result
    assert result["total"] == 1
    conv = result["conversations"][0]
    assert "id" in conv
    assert "message_count" in conv
    assert "last_message_at" in conv
    assert "preview" in conv


async def test_get_conversation_returns_none_for_wrong_user(tutor_service, sample_user):
    """get_conversation must return None when the conversation belongs to another user."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    other_user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    result = await tutor_service.get_conversation(
        user_id=other_user_id,
        conversation_id=conversation_id,
        session=mock_session,
    )

    assert result is None


async def test_get_conversation_returns_messages(tutor_service, sample_user, sample_conversation):
    """get_conversation returns the durable per-message history (#1978).

    First the conversation row is loaded, then ``tutor_messages`` is queried
    for the ordered history. When that table has no rows (e.g. a legacy
    conversation predating the backfill) the implementation falls back to the
    JSON array on the conversation.
    """
    sample_conversation.messages = [
        {
            "role": "user",
            "content": "Hello",
            "timestamp": datetime.now(UTC).isoformat(),
        },
        {
            "role": "assistant",
            "content": "Bonjour!",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    ]

    mock_session = AsyncMock(spec=AsyncSession)
    conv_result = MagicMock()
    conv_result.scalar_one_or_none.return_value = sample_conversation
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = []  # legacy fallback path
    mock_session.execute = AsyncMock(side_effect=[conv_result, rows_result])

    result = await tutor_service.get_conversation(
        user_id=sample_user.id,
        conversation_id=sample_conversation.id,
        session=mock_session,
    )

    assert result is not None
    assert result["id"] == sample_conversation.id
    assert result["messages"] == sample_conversation.messages
    assert "created_at" in result


# Regression tests for #1975 — split user/assistant commits so a stream
# interruption between message receipt and end-of-stream doesn't lose both
# sides of the exchange.


async def test_persist_user_message_appends_and_commits(tutor_service, sample_conversation):
    """User message gets appended to the JSON working set, written as a
    durable ``TutorMessage`` row, and the increment-only counters move
    forward — all in one commit (#1975, #1978).
    """
    from app.domain.models.conversation import TutorMessage

    sample_conversation.messages = []
    sample_conversation.message_count = 0
    sample_conversation.user_messages_sent = 0
    sample_conversation.total_messages = 0
    mock_session = AsyncMock(spec=AsyncSession)

    user_msg = {
        "role": "user",
        "content": "What is hypertension?",
        "timestamp": datetime.now(UTC).isoformat(),
        "has_files": False,
    }

    await tutor_service._persist_user_message(sample_conversation, user_msg, mock_session)

    assert sample_conversation.messages == [user_msg]
    assert sample_conversation.message_count == 1
    assert sample_conversation.user_messages_sent == 1
    assert sample_conversation.total_messages == 1
    added = [call.args[0] for call in mock_session.add.call_args_list]
    assert sample_conversation in added
    tutor_message_rows = [obj for obj in added if isinstance(obj, TutorMessage)]
    assert len(tutor_message_rows) == 1
    assert tutor_message_rows[0].role == "user"
    assert tutor_message_rows[0].content == "What is hypertension?"
    assert tutor_message_rows[0].position == 0
    assert mock_session.commit.await_count == 1


async def test_persist_user_message_preserves_existing_messages(tutor_service, sample_conversation):
    """Helper must not clobber prior turns — appending only."""
    prior_user = {"role": "user", "content": "earlier", "timestamp": "t0"}
    prior_assistant = {"role": "assistant", "content": "earlier reply", "timestamp": "t1"}
    sample_conversation.messages = [prior_user, prior_assistant]
    sample_conversation.message_count = 2
    sample_conversation.user_messages_sent = 1
    sample_conversation.total_messages = 2
    mock_session = AsyncMock(spec=AsyncSession)

    new_user = {"role": "user", "content": "follow-up", "timestamp": "t2"}
    await tutor_service._persist_user_message(sample_conversation, new_user, mock_session)

    assert sample_conversation.messages == [prior_user, prior_assistant, new_user]
    assert sample_conversation.message_count == 3
    assert sample_conversation.user_messages_sent == 2
    assert sample_conversation.total_messages == 3
    assert mock_session.commit.await_count == 1


async def test_persist_user_message_commit_durability_invariant(tutor_service, sample_conversation):
    """The contract is: when this returns, the new message is durable.

    A bare flush() would have left the row visible only inside the request's
    session — a follow-up GET on a different connection would 404 (#1625
    pattern). This test guards against accidentally regressing to flush.
    """
    sample_conversation.messages = []
    sample_conversation.message_count = 0
    sample_conversation.user_messages_sent = 0
    sample_conversation.total_messages = 0
    mock_session = AsyncMock(spec=AsyncSession)

    await tutor_service._persist_user_message(
        sample_conversation,
        {"role": "user", "content": "x", "timestamp": "t"},
        mock_session,
    )

    # commit() — not just flush() — is required for cross-session visibility.
    assert mock_session.commit.await_count >= 1
