"""Tests for AI tutor service SSE streaming and error handling."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.tutor import get_compaction_prompt
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.conversation import TutorConversation
from app.domain.models.user import User
from app.domain.services.tutor_service import COMPACT_TRIGGER_COUNT, TutorService


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
        message_count=0,
        created_at=datetime.now(UTC),
    )


def _make_messages(count: int) -> list[dict]:
    """Create alternating user/assistant messages."""
    messages = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(
            {
                "role": role,
                "content": f"Message {i + 1}",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    return messages


@pytest.fixture
def long_conversation(sample_user):
    """Conversation with more than COMPACT_TRIGGER_COUNT messages."""
    messages = _make_messages(COMPACT_TRIGGER_COUNT + 2)
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=messages,
        message_count=len(messages),
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


async def test_message_count_updated_after_send(tutor_service, sample_user, sample_conversation):
    """Verify message_count is incremented after sending a message."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    async def mock_stream_iter():
        return
        yield

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    mock_stream.__aiter__ = lambda self: mock_stream_iter()
    tutor_service.anthropic.messages.stream = MagicMock(return_value=mock_stream)

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=sample_conversation,
        ),
        patch.object(
            tutor_service, "_retrieve_relevant_context", new_callable=AsyncMock, return_value=[]
        ),
    ):
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Hello",
                session=mock_session,
            )
        )

    assert sample_conversation.message_count == 2


async def test_compact_triggers_when_message_count_exceeds_threshold(
    tutor_service, sample_user, long_conversation
):
    """Verify compacting is triggered when message_count > COMPACT_TRIGGER_COUNT."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)

    async def mock_stream_iter():
        return
        yield

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    mock_stream.__aiter__ = lambda self: mock_stream_iter()
    tutor_service.anthropic.messages.stream = MagicMock(return_value=mock_stream)

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service,
            "_get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=long_conversation,
        ),
        patch.object(
            tutor_service, "_retrieve_relevant_context", new_callable=AsyncMock, return_value=[]
        ),
        patch.object(
            tutor_service,
            "_compact_conversation_async",
            new_callable=AsyncMock,
        ),
        patch("asyncio.ensure_future") as mock_ensure_future,
    ):
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()

        await collect_chunks(
            tutor_service.send_message(
                user_id=sample_user.id,
                message="Another message",
                session=mock_session,
            )
        )

        assert mock_ensure_future.called, (
            "ensure_future should be called to trigger async compaction"
        )


async def test_prepare_conversation_history_includes_compact_context(tutor_service, sample_user):
    """Verify compacted_context is prepended to conversation history."""
    messages = _make_messages(3)
    conversation = TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=messages,
        message_count=3,
        compacted_context="L'apprenant a discuté de l'épidémiologie de base.",
        created_at=datetime.now(UTC),
    )

    history = await tutor_service._prepare_conversation_history(conversation)

    assert len(history) >= 2
    assert "[Context from earlier" in history[0]["content"]
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


async def test_prepare_conversation_history_no_compact(tutor_service, sample_conversation):
    """Verify history without compacted_context returns only recent messages."""
    sample_conversation.messages = _make_messages(3)
    sample_conversation.compacted_context = None

    history = await tutor_service._prepare_conversation_history(sample_conversation)

    assert len(history) == 3
    assert all("[Context from earlier" not in m["content"] for m in history)


async def test_compact_conversation_summarizes_old_messages(tutor_service, sample_user):
    """Verify _compact_conversation calls Claude and stores summary."""
    messages = _make_messages(COMPACT_TRIGGER_COUNT + 2)
    conversation = TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=messages,
        message_count=len(messages),
        compacted_context=None,
        created_at=datetime.now(UTC),
    )

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Summary of the conversation.")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_response)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conversation))
    )
    mock_session.add = MagicMock()

    await tutor_service._compact_conversation(
        conversation_id=conversation.id,
        user_language="fr",
        session=mock_session,
    )

    assert conversation.compacted_context == "Summary of the conversation."
    assert conversation.compacted_at is not None
    assert len(conversation.messages) < COMPACT_TRIGGER_COUNT + 2


async def test_compact_conversation_compacted_context_under_500_tokens(tutor_service, sample_user):
    """Verify compact summary respects ≤500 token limit (max_tokens=600 forces this)."""
    messages = _make_messages(COMPACT_TRIGGER_COUNT + 2)
    conversation = TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=messages,
        message_count=len(messages),
        compacted_context=None,
        created_at=datetime.now(UTC),
    )

    short_summary = "A" * 100
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=short_summary)]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_response)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conversation))
    )
    mock_session.add = MagicMock()

    await tutor_service._compact_conversation(
        conversation_id=conversation.id,
        user_language="en",
        session=mock_session,
    )

    word_count = len(conversation.compacted_context.split())
    assert word_count <= 500, f"Summary too long: {word_count} words"


async def test_compact_keeps_recent_messages_verbatim(tutor_service, sample_user):
    """Verify recent messages are preserved after compaction."""
    from app.domain.services.tutor_service import COMPACT_MESSAGES_TO_SUMMARIZE

    messages = _make_messages(COMPACT_TRIGGER_COUNT + 2)
    expected_kept = messages[COMPACT_MESSAGES_TO_SUMMARIZE:]
    conversation = TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=messages,
        message_count=len(messages),
        compacted_context=None,
        created_at=datetime.now(UTC),
    )

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Summary")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_response)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conversation))
    )
    mock_session.add = MagicMock()

    await tutor_service._compact_conversation(
        conversation_id=conversation.id,
        user_language="fr",
        session=mock_session,
    )

    assert conversation.messages == expected_kept


def test_compaction_prompt_fr_contains_instructions():
    """Verify FR compaction prompt includes expected content."""
    messages = [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Salut"}]
    prompt = get_compaction_prompt("fr", messages, existing_compact=None)

    assert "500 tokens" in prompt
    assert "MESSAGES À RÉSUMER" in prompt
    assert "[USER]" in prompt
    assert "[ASSISTANT]" in prompt


def test_compaction_prompt_en_contains_instructions():
    """Verify EN compaction prompt includes expected content."""
    messages = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    prompt = get_compaction_prompt("en", messages, existing_compact=None)

    assert "500 tokens" in prompt
    assert "MESSAGES TO SUMMARIZE" in prompt
    assert "[USER]" in prompt


def test_compaction_prompt_includes_existing_compact():
    """Verify existing compacted_context is included in new prompt."""
    messages = [{"role": "user", "content": "New question"}]
    prior = "Previous summary content here."
    prompt = get_compaction_prompt("fr", messages, existing_compact=prior)

    assert prior in prompt
    assert "RÉSUMÉ PRÉCÉDENT" in prompt


def test_compaction_prompt_en_includes_existing_compact():
    """Verify existing compact in EN prompt."""
    messages = [{"role": "user", "content": "New question"}]
    prior = "Previous summary."
    prompt = get_compaction_prompt("en", messages, existing_compact=prior)

    assert prior in prompt
    assert "PREVIOUS SUMMARY" in prompt
