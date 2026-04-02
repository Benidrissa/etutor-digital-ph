"""Tests for LearnerMemoryService."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.learner_memory import LearnerMemory
from app.domain.services.learner_memory_service import LearnerMemoryService


@pytest.fixture
def memory_service() -> LearnerMemoryService:
    return LearnerMemoryService()


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_mock_session(memory: LearnerMemory | None = None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=memory)
    session.execute = AsyncMock(return_value=scalar_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


async def test_get_memory_returns_defaults_for_new_user(memory_service, user_id):
    """get_memory returns empty defaults when no record exists."""
    session = _make_mock_session(memory=None)

    result = await memory_service.get_memory(user_id, session)

    assert result["difficulty_domains"] == {}
    assert result["preferred_explanation_style"] is None
    assert result["preferred_country_examples"] == []
    assert result["recurring_questions"] == {}
    assert result["declared_goals"] == {}
    assert result["learning_insights"] == {}


async def test_get_memory_returns_existing_record(memory_service, user_id):
    """get_memory returns stored data when a record exists."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={"épidémiologie": 3},
        preferred_explanation_style="analogies",
        preferred_country_examples=["SN", "BF"],
        recurring_questions={"paludisme": {"count": 2, "last_asked_at": "2026-04-01"}},
        declared_goals={"g1": {"goal": "Master biostatistics", "added_at": "2026-04-01"}},
        learning_insights={"i1": {"insight": "confuses incidence and prevalence"}},
    )
    session = _make_mock_session(memory=memory)

    result = await memory_service.get_memory(user_id, session)

    assert result["difficulty_domains"] == {"épidémiologie": 3}
    assert result["preferred_explanation_style"] == "analogies"
    assert result["preferred_country_examples"] == ["SN", "BF"]


async def test_update_preference_upserts_explanation_style(memory_service, user_id):
    """update_preference sets preferred_explanation_style correctly."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={},
        preferred_explanation_style=None,
        preferred_country_examples=[],
        recurring_questions={},
        declared_goals={},
        learning_insights={},
    )
    session = _make_mock_session(memory=memory)

    await memory_service.update_preference(
        user_id, "preferred_explanation_style", "analogies", session
    )

    assert memory.preferred_explanation_style == "analogies"
    session.add.assert_called_once_with(memory)
    session.flush.assert_called_once()


async def test_update_preference_appends_country_examples(memory_service, user_id):
    """update_preference appends to preferred_country_examples without duplicates."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={},
        preferred_explanation_style=None,
        preferred_country_examples=["SN"],
        recurring_questions={},
        declared_goals={},
        learning_insights={},
    )
    session = _make_mock_session(memory=memory)

    await memory_service.update_preference(user_id, "preferred_country_examples", "BF", session)

    assert "SN" in memory.preferred_country_examples
    assert "BF" in memory.preferred_country_examples
    assert len(memory.preferred_country_examples) == 2

    await memory_service.update_preference(user_id, "preferred_country_examples", "SN", session)
    assert memory.preferred_country_examples.count("SN") == 1


async def test_update_preference_creates_new_record_when_none(memory_service, user_id):
    """update_preference creates a new LearnerMemory row if none exists."""
    session = _make_mock_session(memory=None)
    new_memory_holder: list[LearnerMemory] = []

    original_add = session.add

    def capture_add(obj):
        if isinstance(obj, LearnerMemory):
            new_memory_holder.append(obj)
        original_add(obj)

    session.add = MagicMock(side_effect=capture_add)

    await memory_service.update_preference(
        user_id, "preferred_explanation_style", "formal", session
    )

    assert len(new_memory_holder) >= 1
    created = new_memory_holder[-1]
    assert created.preferred_explanation_style == "formal"


async def test_add_insight_appends_to_list(memory_service, user_id):
    """add_insight appends a new entry to learning_insights."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={},
        preferred_explanation_style=None,
        preferred_country_examples=[],
        recurring_questions={},
        declared_goals={},
        learning_insights={},
    )
    session = _make_mock_session(memory=memory)
    conv_id = uuid.uuid4()

    await memory_service.add_insight(
        user_id, "learner confuses incidence and prevalence", conv_id, session
    )

    assert len(memory.learning_insights) == 1
    entry = list(memory.learning_insights.values())[0]
    assert entry["insight"] == "learner confuses incidence and prevalence"
    assert entry["conversation_id"] == str(conv_id)
    assert "added_at" in entry


async def test_add_insight_appends_multiple(memory_service, user_id):
    """add_insight accumulates multiple insights."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={},
        preferred_explanation_style=None,
        preferred_country_examples=[],
        recurring_questions={},
        declared_goals={},
        learning_insights={"existing": {"insight": "first insight", "added_at": "2026-04-01"}},
    )
    session = _make_mock_session(memory=memory)

    await memory_service.add_insight(user_id, "second insight", None, session)

    assert len(memory.learning_insights) == 2


async def test_add_recurring_question_increments_count(memory_service, user_id):
    """add_recurring_question increments count for the same topic."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={},
        preferred_explanation_style=None,
        preferred_country_examples=[],
        recurring_questions={},
        declared_goals={},
        learning_insights={},
    )
    session = _make_mock_session(memory=memory)

    await memory_service.add_recurring_question(user_id, "paludisme", session)
    assert memory.recurring_questions["paludisme"]["count"] == 1

    await memory_service.add_recurring_question(user_id, "paludisme", session)
    assert memory.recurring_questions["paludisme"]["count"] == 2


async def test_format_for_prompt_returns_empty_for_new_user(memory_service, user_id):
    """format_for_prompt returns empty string when no memory exists."""
    session = _make_mock_session(memory=None)

    result = await memory_service.format_for_prompt(user_id, session)

    assert result == ""


async def test_format_for_prompt_within_200_tokens(memory_service, user_id):
    """format_for_prompt produces a summary of ≤200 tokens (approx words*1.3)."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={"épidémiologie": 5, "biostatistiques": 3, "surveillance": 2},
        preferred_explanation_style="analogies",
        preferred_country_examples=["SN", "BF", "CI"],
        recurring_questions={
            "paludisme": {"count": 4, "last_asked_at": "2026-04-01"},
            "méningite": {"count": 2, "last_asked_at": "2026-04-01"},
        },
        declared_goals={
            "g1": {"goal": "Master biostatistics for thesis", "added_at": "2026-04-01"}
        },
        learning_insights={
            "i1": {
                "insight": "confuses incidence and prevalence",
                "added_at": "2026-04-02",
                "conversation_id": None,
            }
        },
    )
    session = _make_mock_session(memory=memory)

    result = await memory_service.format_for_prompt(user_id, session)

    assert result != ""
    assert "LEARNER MEMORY" in result
    word_count = len(result.split())
    estimated_tokens = int(word_count * 1.3)
    assert estimated_tokens <= 200, f"Summary too long: ~{estimated_tokens} tokens"


async def test_format_for_prompt_includes_key_sections(memory_service, user_id):
    """format_for_prompt includes difficulty, style, and insights when present."""
    memory = LearnerMemory(
        id=uuid.uuid4(),
        user_id=user_id,
        difficulty_domains={"biostatistiques": 3},
        preferred_explanation_style="formal",
        preferred_country_examples=[],
        recurring_questions={},
        declared_goals={},
        learning_insights={},
    )
    session = _make_mock_session(memory=memory)

    result = await memory_service.format_for_prompt(user_id, session)

    assert "biostatistiques" in result
    assert "formal" in result


async def test_memory_injected_in_tutor_system_prompt():
    """Test that memory is included in the tutor system prompt via TutorContext."""
    from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt

    memory_text = "## LEARNER MEMORY\n- Difficulty domains: biostatistiques"
    context = TutorContext(
        user_level=1,
        user_language="fr",
        user_country="SN",
        learner_memory=memory_text,
    )

    prompt = get_socratic_system_prompt(context, [])

    assert "LEARNER MEMORY" in prompt
    assert "biostatistiques" in prompt


async def test_memory_not_in_prompt_when_empty():
    """Test that no memory section appears when learner_memory is None."""
    from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt

    context = TutorContext(
        user_level=1,
        user_language="fr",
        user_country="SN",
        learner_memory=None,
    )

    prompt = get_socratic_system_prompt(context, [])

    assert "LEARNER MEMORY" not in prompt
