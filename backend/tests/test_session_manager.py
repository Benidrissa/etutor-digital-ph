"""Tests for SessionManager — cross-session context with memory + compact history."""

import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.conversation import TutorConversation
from app.domain.models.user import User
from app.domain.services.learner_memory_service import LearnerMemoryService
from app.domain.services.tutor_service import (
    SESSION_CONTEXT_TOKEN_BUDGET,
    SessionContext,
    SessionManager,
    _build_progress_snapshot,
    _trim_to_budget,
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
        current_level=2,
        streak_days=5,
        last_active=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def new_conversation(sample_user):
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[],
        message_count=0,
        created_at=datetime.now(UTC),
        compacted_context=None,
        compacted_at=None,
    )


@pytest.fixture
def conversation_with_compact(sample_user):
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[{"role": "user", "content": "Hello", "timestamp": datetime.now(UTC).isoformat()}],
        message_count=1,
        created_at=datetime.now(UTC),
        compacted_context="Previous compact summary about malaria surveillance.",
        compacted_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_memory_service():
    svc = AsyncMock(spec=LearnerMemoryService)
    svc.format_for_prompt = AsyncMock(return_value="Style: analogies\nCountry: SN\nGoal: pass exam")
    return svc


@pytest.fixture
def session_manager(mock_memory_service):
    return SessionManager(learner_memory_service=mock_memory_service)


async def test_new_conversation_loads_learner_memory(
    session_manager, sample_user, new_conversation, mock_memory_service
):
    """New conversation: learner_memory is loaded from memory service."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = await session_manager.build_session_context(
        user=sample_user,
        conversation=new_conversation,
        is_new_conversation=True,
        session=mock_session,
    )

    assert ctx.learner_memory == "Style: analogies\nCountry: SN\nGoal: pass exam"
    mock_memory_service.format_for_prompt.assert_awaited_once_with(sample_user.id, mock_session)


async def test_new_conversation_loads_previous_compact(
    session_manager, sample_user, new_conversation
):
    """New conversation: previous conversation's compacted_context is loaded as previous_compact."""
    prior_conv = TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[],
        message_count=0,
        created_at=datetime.now(UTC),
        compacted_context="Summary of the last session about epidemiology.",
        compacted_at=datetime.now(UTC),
    )

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = prior_conv
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = await session_manager.build_session_context(
        user=sample_user,
        conversation=new_conversation,
        is_new_conversation=True,
        session=mock_session,
    )

    assert ctx.previous_compact == "Summary of the last session about epidemiology."
    assert ctx.current_compact == ""
    assert ctx.is_new_conversation is True


async def test_new_conversation_no_prior_compact_when_none_exists(
    session_manager, sample_user, new_conversation
):
    """New conversation: previous_compact is empty when no prior conversation exists."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = await session_manager.build_session_context(
        user=sample_user,
        conversation=new_conversation,
        is_new_conversation=True,
        session=mock_session,
    )

    assert ctx.previous_compact == ""


async def test_continuing_conversation_loads_current_compact(
    session_manager, sample_user, conversation_with_compact
):
    """Continuing conversation: loads current compacted_context, not previous."""
    mock_session = AsyncMock(spec=AsyncSession)

    ctx = await session_manager.build_session_context(
        user=sample_user,
        conversation=conversation_with_compact,
        is_new_conversation=False,
        session=mock_session,
    )

    assert ctx.current_compact == "Previous compact summary about malaria surveillance."
    assert ctx.previous_compact == ""
    assert ctx.is_new_conversation is False


async def test_continuing_conversation_without_compact(
    session_manager, sample_user, new_conversation
):
    """Continuing conversation with no compacted_context: current_compact is empty."""
    mock_session = AsyncMock(spec=AsyncSession)

    ctx = await session_manager.build_session_context(
        user=sample_user,
        conversation=new_conversation,
        is_new_conversation=False,
        session=mock_session,
    )

    assert ctx.current_compact == ""
    assert ctx.previous_compact == ""


async def test_progress_snapshot_included(session_manager, sample_user, new_conversation):
    """Session context always includes a progress_snapshot from the User model."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = await session_manager.build_session_context(
        user=sample_user,
        conversation=new_conversation,
        is_new_conversation=True,
        session=mock_session,
    )

    assert ctx.progress_snapshot != ""
    assert "L2" in ctx.progress_snapshot or "Intermediate" in ctx.progress_snapshot
    assert "SN" in ctx.progress_snapshot


def test_build_progress_snapshot_level_labels(sample_user):
    """_build_progress_snapshot renders correct level labels."""
    for level, label in [(1, "L1"), (2, "L2"), (3, "L3"), (4, "L4")]:
        sample_user.current_level = level
        snapshot = _build_progress_snapshot(sample_user)
        assert label in snapshot


def test_build_progress_snapshot_includes_country(sample_user):
    """_build_progress_snapshot includes country code."""
    sample_user.country = "BF"
    snapshot = _build_progress_snapshot(sample_user)
    assert "BF" in snapshot


def test_build_progress_snapshot_includes_streak(sample_user):
    """_build_progress_snapshot includes streak days when present."""
    sample_user.streak_days = 10
    snapshot = _build_progress_snapshot(sample_user)
    assert "10" in snapshot


async def test_total_context_stays_within_budget(session_manager, sample_user, new_conversation):
    """Session context estimated_tokens() stays ≤ SESSION_CONTEXT_TOKEN_BUDGET."""
    big_compact = "A" * (SESSION_CONTEXT_TOKEN_BUDGET * 8)
    prior_conv = TutorConversation(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        module_id=None,
        messages=[],
        message_count=0,
        created_at=datetime.now(UTC),
        compacted_context=big_compact,
        compacted_at=datetime.now(UTC),
    )

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = prior_conv
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = await session_manager.build_session_context(
        user=sample_user,
        conversation=new_conversation,
        is_new_conversation=True,
        session=mock_session,
    )

    assert ctx.estimated_tokens() <= SESSION_CONTEXT_TOKEN_BUDGET


def test_trim_to_budget_no_op_when_under_budget():
    """_trim_to_budget returns context unchanged when already within budget."""
    ctx = SessionContext(
        learner_memory="short memory",
        previous_compact="short compact",
        progress_snapshot="Level 2",
    )
    original_memory = ctx.learner_memory
    original_compact = ctx.previous_compact
    result = _trim_to_budget(ctx)
    assert result.learner_memory == original_memory
    assert result.previous_compact == original_compact


def test_trim_to_budget_trims_oversize_compact():
    """_trim_to_budget trims previous_compact when it exceeds budget."""
    oversized = "X" * (SESSION_CONTEXT_TOKEN_BUDGET * 6)
    ctx = SessionContext(
        learner_memory="memory",
        previous_compact=oversized,
        progress_snapshot="Level 2",
    )
    result = _trim_to_budget(ctx)
    assert result.estimated_tokens() <= SESSION_CONTEXT_TOKEN_BUDGET


def test_session_context_has_prior_context_true():
    """has_prior_context is True when any context field is set."""
    ctx = SessionContext(previous_compact="some summary")
    assert ctx.has_prior_context is True


def test_session_context_has_prior_context_false():
    """has_prior_context is False when all context fields are empty."""
    ctx = SessionContext()
    assert ctx.has_prior_context is False


async def test_session_init_latency_under_200ms(session_manager, sample_user, new_conversation):
    """Session context initialization must complete in < 200ms with mocked DB."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    start = time.perf_counter()
    await session_manager.build_session_context(
        user=sample_user,
        conversation=new_conversation,
        is_new_conversation=True,
        session=mock_session,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 200, f"Session init took {elapsed_ms:.1f}ms, must be < 200ms"


async def test_list_conversations_has_context_field():
    """list_conversations result includes has_context for each conversation."""

    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.tutor_service import TutorService

    mock_anthropic = MagicMock()
    mock_retriever = AsyncMock(spec=SemanticRetriever)
    mock_embedding = AsyncMock(spec=EmbeddingService)
    mock_memory_svc = AsyncMock(spec=LearnerMemoryService)
    mock_memory_svc.format_for_prompt = AsyncMock(return_value="")

    service = TutorService(
        anthropic_client=mock_anthropic,
        semantic_retriever=mock_retriever,
        embedding_service=mock_embedding,
        learner_memory_service=mock_memory_svc,
    )

    user_id = uuid.uuid4()
    conv_with_context = TutorConversation(
        id=uuid.uuid4(),
        user_id=user_id,
        module_id=None,
        messages=[{"role": "user", "content": "Hi", "timestamp": datetime.now(UTC).isoformat()}],
        message_count=1,
        created_at=datetime.now(UTC),
        compacted_context="Some prior context",
        compacted_at=datetime.now(UTC),
    )
    conv_without_context = TutorConversation(
        id=uuid.uuid4(),
        user_id=user_id,
        module_id=None,
        messages=[],
        message_count=0,
        created_at=datetime.now(UTC),
        compacted_context=None,
        compacted_at=None,
    )

    mock_session = AsyncMock(spec=AsyncSession)
    mock_list_result = MagicMock()
    mock_list_result.scalars.return_value.all.return_value = [
        conv_with_context,
        conv_without_context,
    ]
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 2
    mock_session.execute = AsyncMock(side_effect=[mock_list_result, mock_count_result])

    result = await service.list_conversations(user_id=user_id, session=mock_session)

    convs = result["conversations"]
    assert len(convs) == 2
    assert convs[0]["has_context"] is True
    assert convs[1]["has_context"] is False
