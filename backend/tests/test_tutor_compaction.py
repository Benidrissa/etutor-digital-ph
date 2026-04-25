"""Tests for conversation auto-compacting feature."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.prompts.tutor import get_compaction_prompt
from app.domain.models.conversation import TutorConversation
from app.domain.models.user import User
from app.domain.services.tutor_service import (
    COMPACT_KEEP_RECENT,
    COMPACT_SUMMARIZE_UP_TO,
    COMPACT_TRIGGER,
    SessionContext,
    TutorService,
)


@pytest.fixture(autouse=True)
def _mock_subscription_service():
    with patch(
        "app.domain.services.tutor_service.SubscriptionService.get_active_subscription",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield


@pytest.fixture
def mock_anthropic_client():
    client = MagicMock()
    return client


@pytest.fixture
def mock_semantic_retriever():
    from app.ai.rag.retriever import SemanticRetriever

    retriever = AsyncMock(spec=SemanticRetriever)
    retriever.search_for_module = AsyncMock(return_value=[])
    return retriever


@pytest.fixture
def mock_embedding_service():
    from app.ai.rag.embeddings import EmbeddingService

    return AsyncMock(spec=EmbeddingService)


@pytest.fixture(autouse=True)
def mock_subscription_service():
    sub = MagicMock()
    sub.daily_message_limit = 20
    sub.message_credits = 0
    with patch("app.domain.services.tutor_service.SubscriptionService") as MockSubSvc:
        MockSubSvc.return_value.get_active_subscription = AsyncMock(return_value=sub)
        yield MockSubSvc


@pytest.fixture
def tutor_service(mock_anthropic_client, mock_semantic_retriever, mock_embedding_service):
    svc = TutorService(
        anthropic_client=mock_anthropic_client,
        semantic_retriever=mock_semantic_retriever,
        embedding_service=mock_embedding_service,
    )
    svc.session_manager.build_session_context = AsyncMock(
        return_value=SessionContext(learner_memory="", is_new_conversation=True)
    )
    return svc


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


def _make_conversation(user_id, n_messages: int, compacted_context: str | None = None):
    messages = []
    for i in range(n_messages):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(
            {"role": role, "content": f"Message {i}", "timestamp": datetime.now(UTC).isoformat()}
        )
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=user_id,
        module_id=None,
        messages=messages,
        message_count=n_messages,
        created_at=datetime.now(UTC),
        compacted_context=compacted_context,
        compacted_at=None,
    )


async def test_compact_trigger_constant():
    """COMPACT_TRIGGER relaxed to 50 (#1978) — trigger ~5x further out."""
    assert COMPACT_TRIGGER == 50


async def test_compact_keep_recent_constant():
    """COMPACT_KEEP_RECENT bumped to 20 (#1978)."""
    assert COMPACT_KEEP_RECENT == 20


async def test_compact_summarize_up_to_constant():
    """COMPACT_SUMMARIZE_UP_TO bumped to 30 (#1978)."""
    assert COMPACT_SUMMARIZE_UP_TO == 30


async def test_prepare_history_no_compact_returns_all_when_short(tutor_service, sample_user):
    """With no compacted_context and a conversation under the cap, all messages are returned."""
    conv = _make_conversation(sample_user.id, n_messages=15)
    history = await tutor_service._prepare_conversation_history(conv)
    assert len(history) == 15


async def test_prepare_history_no_compact_caps_long_conversation(tutor_service, sample_user):
    """With no compacted_context but a very long conversation, history is capped to keep prompts bounded."""
    conv = _make_conversation(sample_user.id, n_messages=100)
    history = await tutor_service._prepare_conversation_history(conv)
    cap = max(10, COMPACT_KEEP_RECENT * 2)
    assert len(history) == cap


async def test_prepare_history_with_compact_includes_context_note(tutor_service, sample_user):
    """When compacted_context is set, history starts with user/assistant pair."""
    compact_text = "Summary of previous discussion"
    conv = _make_conversation(sample_user.id, n_messages=6, compacted_context=compact_text)
    history = await tutor_service._prepare_conversation_history(conv)
    assert history[0]["role"] == "user"
    assert history[0]["content"] == compact_text
    assert history[1]["role"] == "assistant"


async def test_prepare_history_with_compact_slices_from_high_water_mark(tutor_service, sample_user):
    """Non-destructive compaction (#1978): the summary covers messages
    [0:compacted_through_position]; the rest of the messages array is sent
    verbatim. Counts the messages past the high-water mark.
    """
    conv = _make_conversation(sample_user.id, n_messages=40, compacted_context="summary")
    conv.compacted_through_position = 30
    history = await tutor_service._prepare_conversation_history(conv)
    non_system = [m for m in history if m["content"] != "summary" and "Compris" not in m["content"]]
    assert len(non_system) == 40 - 30


async def test_compaction_prompt_fr_contains_key_fields():
    """FR prompt must instruct to preserve all required fields."""
    messages = [
        {"role": "user", "content": "Question?"},
        {"role": "assistant", "content": "Réponse"},
    ]
    prompt = get_compaction_prompt(messages, existing_compact=None, language="fr")
    assert "sujets" in prompt.lower()
    assert "difficultés" in prompt.lower() or "difficultes" in prompt.lower()
    assert "500" in prompt


async def test_compaction_prompt_en_contains_key_fields():
    """EN prompt must instruct to preserve all required fields."""
    messages = [
        {"role": "user", "content": "Question?"},
        {"role": "assistant", "content": "Answer"},
    ]
    prompt = get_compaction_prompt(messages, existing_compact=None, language="en")
    assert "topics" in prompt.lower()
    assert "difficulties" in prompt.lower()
    assert "500" in prompt


async def test_compaction_prompt_includes_existing_compact_fr():
    """When existing_compact provided, FR prompt includes it."""
    messages = [{"role": "user", "content": "Hi"}]
    existing = "Résumé précédent"
    prompt = get_compaction_prompt(messages, existing_compact=existing, language="fr")
    assert existing in prompt


async def test_compaction_prompt_includes_existing_compact_en():
    """When existing_compact provided, EN prompt includes it."""
    messages = [{"role": "user", "content": "Hi"}]
    existing = "Previous summary"
    prompt = get_compaction_prompt(messages, existing_compact=existing, language="en")
    assert existing in prompt


async def test_compact_conversation_async_is_non_destructive(tutor_service, sample_user):
    """Non-destructive compaction (#1978): ``compacted_context`` and
    ``compacted_at`` are populated, ``compacted_through_position`` advances
    by ``COMPACT_SUMMARIZE_UP_TO``, and the original messages array is left
    intact so users can still scroll back.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    n = COMPACT_SUMMARIZE_UP_TO + 10
    conv = _make_conversation(sample_user.id, n_messages=n)
    conv.compacted_through_position = 0
    conversation_id = conv.id

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    mock_compact_response = MagicMock()
    mock_compact_response.content = [FakeTextBlock("Résumé compact généré")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_compact_response)

    mock_session = AsyncMock(spec=AsyncSession)

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none = MagicMock(return_value=conv)
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value = mock_session

    with (
        patch("app.domain.services.tutor_service.create_async_engine", return_value=mock_engine),
        patch(
            "app.domain.services.tutor_service.async_sessionmaker",
            return_value=mock_session_factory,
        ),
    ):
        await tutor_service._compact_conversation_async(
            conversation_id=conversation_id,
            user_language="fr",
        )

    assert conv.compacted_context == "Résumé compact généré"
    assert conv.compacted_at is not None
    assert conv.compacted_through_position == COMPACT_SUMMARIZE_UP_TO
    # Originals are NOT deleted — that's the whole point of #1978.
    assert len(conv.messages) == n


async def test_compaction_does_not_decrement_counters(tutor_service, sample_user):
    """Compaction must never reduce ``user_messages_sent`` or ``total_messages``
    — those are the source of truth for the daily limit and the sidebar count
    respectively. Regression guard for the original bug where compaction
    appeared to "refund" budget.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    n = COMPACT_SUMMARIZE_UP_TO + 10
    conv = _make_conversation(sample_user.id, n_messages=n)
    conv.compacted_through_position = 0
    # Simulate the live counters as they'd be after n messages.
    conv.user_messages_sent = n // 2
    conv.total_messages = n
    pre_user = conv.user_messages_sent
    pre_total = conv.total_messages
    pre_messages = list(conv.messages)
    conversation_id = conv.id

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    mock_compact_response = MagicMock()
    mock_compact_response.content = [FakeTextBlock("Résumé")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_compact_response)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none = MagicMock(return_value=conv)
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value = mock_session

    with (
        patch("app.domain.services.tutor_service.create_async_engine", return_value=mock_engine),
        patch(
            "app.domain.services.tutor_service.async_sessionmaker",
            return_value=mock_session_factory,
        ),
    ):
        await tutor_service._compact_conversation_async(
            conversation_id=conversation_id,
            user_language="fr",
        )

    assert conv.user_messages_sent == pre_user, "compaction must not touch the daily counter"
    assert conv.total_messages == pre_total, "compaction must not touch the sidebar counter"
    assert conv.messages == pre_messages, "compaction must not mutate the messages array"


async def test_compaction_advances_position_by_actual_slice_length(tutor_service, sample_user):
    """When the slice is shorter than ``COMPACT_SUMMARIZE_UP_TO`` (boundary
    case), ``compacted_through_position`` advances by the actual count, not the
    constant — otherwise the next pass would skip messages that arrive later.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    # 5 messages past the existing high-water mark — fewer than COMPACT_SUMMARIZE_UP_TO.
    start = 30
    extra = 5
    conv = _make_conversation(sample_user.id, n_messages=start + extra)
    conv.compacted_through_position = start
    conversation_id = conv.id

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    mock_compact_response = MagicMock()
    mock_compact_response.content = [FakeTextBlock("Résumé partiel")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_compact_response)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none = MagicMock(return_value=conv)
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value = mock_session

    with (
        patch("app.domain.services.tutor_service.create_async_engine", return_value=mock_engine),
        patch(
            "app.domain.services.tutor_service.async_sessionmaker",
            return_value=mock_session_factory,
        ),
    ):
        await tutor_service._compact_conversation_async(
            conversation_id=conversation_id,
            user_language="fr",
        )

    assert conv.compacted_through_position == start + extra


async def test_message_count_updated_on_send(tutor_service, sample_user):
    """message_count is set to len(messages) after each send_message call."""
    from sqlalchemy.ext.asyncio import AsyncSession

    conv = _make_conversation(sample_user.id, n_messages=4)

    class FakeTextBlock:
        def __init__(self, text):
            self.text = text

    mock_response = MagicMock()
    mock_response.content = [FakeTextBlock("Test")]
    tutor_service.anthropic.messages.create = AsyncMock(return_value=mock_response)

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.get = AsyncMock(return_value=sample_user)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    with (
        patch.object(tutor_service, "_check_daily_limit", new_callable=AsyncMock, return_value=0),
        patch.object(
            tutor_service, "_get_or_create_conversation", new_callable=AsyncMock, return_value=conv
        ),
        patch.object(
            tutor_service, "_get_previous_compact", new_callable=AsyncMock, return_value=None
        ),
        patch.object(tutor_service, "_resolve_course", new_callable=AsyncMock, return_value=None),
    ):
        chunks = []
        async for chunk in tutor_service.send_message(
            user_id=sample_user.id,
            message="Hello",
            session=mock_session,
        ):
            chunks.append(chunk)

    assert conv.message_count >= 2  # At least user + assistant messages
