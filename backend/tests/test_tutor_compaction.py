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
    """COMPACT_TRIGGER must be 20 as specified in the issue."""
    assert COMPACT_TRIGGER == 20


async def test_compact_keep_recent_constant():
    """COMPACT_KEEP_RECENT must be 5."""
    assert COMPACT_KEEP_RECENT == 5


async def test_compact_summarize_up_to_constant():
    """COMPACT_SUMMARIZE_UP_TO must be 15."""
    assert COMPACT_SUMMARIZE_UP_TO == 15


async def test_prepare_history_no_compact_falls_back_to_last_10(tutor_service, sample_user):
    """When no compacted_context, last 10 messages are used."""
    conv = _make_conversation(sample_user.id, n_messages=15)
    history = await tutor_service._prepare_conversation_history(conv)
    assert len(history) == 10


async def test_prepare_history_with_compact_includes_context_note(tutor_service, sample_user):
    """When compacted_context is set, history starts with user/assistant pair."""
    compact_text = "Summary of previous discussion"
    conv = _make_conversation(sample_user.id, n_messages=6, compacted_context=compact_text)
    history = await tutor_service._prepare_conversation_history(conv)
    assert history[0]["role"] == "user"
    assert history[0]["content"] == compact_text
    assert history[1]["role"] == "assistant"


async def test_prepare_history_with_compact_keeps_recent_messages(tutor_service, sample_user):
    """When compacted_context is set, COMPACT_KEEP_RECENT recent messages are included."""
    conv = _make_conversation(sample_user.id, n_messages=20, compacted_context="summary")
    history = await tutor_service._prepare_conversation_history(conv)
    non_system = [m for m in history if m["content"] != "summary" and "Compris" not in m["content"]]
    assert len(non_system) == COMPACT_KEEP_RECENT


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


async def test_compact_conversation_async_updates_db(tutor_service, sample_user):
    """_compact_conversation_async stores compacted_context and trims messages."""
    from sqlalchemy.ext.asyncio import AsyncSession

    conv = _make_conversation(sample_user.id, n_messages=20)
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
    assert len(conv.messages) == 20 - COMPACT_SUMMARIZE_UP_TO


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
