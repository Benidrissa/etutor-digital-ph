"""Tests for LearnerMemoryService — persistent learner preferences and learning insights."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.learner_memory import LearnerMemory
from app.domain.services.learner_memory_service import LearnerMemoryService


def _make_memory(user_id: uuid.UUID, **kwargs) -> LearnerMemory:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "difficulty_domains": {},
        "preferred_explanation_style": None,
        "preferred_country_examples": [],
        "recurring_questions": {},
        "declared_goals": {},
        "learning_insights": [],
    }
    defaults.update(kwargs)
    return LearnerMemory(**defaults)


@pytest.fixture
def service() -> LearnerMemoryService:
    return LearnerMemoryService()


@pytest.fixture
def mock_session() -> AsyncSession:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


class TestGetMemory:
    async def test_returns_defaults_for_new_user(self, service, mock_session):
        user_id = uuid.uuid4()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        result = await service.get_memory(user_id, mock_session)

        assert result["difficulty_domains"] == {}
        assert result["preferred_explanation_style"] is None
        assert result["preferred_country_examples"] == []
        assert result["recurring_questions"] == {}
        assert result["declared_goals"] == {}
        assert result["learning_insights"] == []

    async def test_returns_stored_memory_for_existing_user(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(
            user_id,
            difficulty_domains={"biostatistics": 3},
            preferred_explanation_style="analogies",
            preferred_country_examples=["SN", "ML"],
        )
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        result = await service.get_memory(user_id, mock_session)

        assert result["difficulty_domains"] == {"biostatistics": 3}
        assert result["preferred_explanation_style"] == "analogies"
        assert result["preferred_country_examples"] == ["SN", "ML"]


class TestUpdatePreference:
    async def test_upserts_explanation_style(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(user_id)
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        await service.update_preference(
            user_id, "preferred_explanation_style", "formal", mock_session
        )

        assert memory.preferred_explanation_style == "formal"
        mock_session.add.assert_called_once_with(memory)
        mock_session.flush.assert_called_once()

    async def test_creates_new_record_on_upsert_if_missing(self, service, mock_session):
        user_id = uuid.uuid4()
        created_memories: list[LearnerMemory] = []

        async def execute_side_effect(stmt):
            if not created_memories:
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            return MagicMock(scalar_one_or_none=MagicMock(return_value=created_memories[0]))

        def add_side_effect(obj):
            if isinstance(obj, LearnerMemory):
                created_memories.append(obj)

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
        mock_session.add = MagicMock(side_effect=add_side_effect)

        await service.update_preference(
            user_id, "preferred_explanation_style", "visual", mock_session
        )

        assert len(created_memories) > 0
        assert created_memories[-1].preferred_explanation_style == "visual"

    async def test_ignores_unknown_preference_type(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(user_id)
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        await service.update_preference(user_id, "unknown_field", "value", mock_session)

        mock_session.add.assert_not_called()


class TestAddInsight:
    async def test_appends_insight_to_list(self, service, mock_session):
        user_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        memory = _make_memory(user_id, learning_insights=[])
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        await service.add_insight(
            user_id, "confuses incidence and prevalence", conv_id, mock_session
        )

        assert len(memory.learning_insights) == 1
        assert memory.learning_insights[0]["insight"] == "confuses incidence and prevalence"
        assert memory.learning_insights[0]["conversation_id"] == str(conv_id)

    async def test_appends_to_existing_insights(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(
            user_id,
            learning_insights=[{"insight": "first insight", "conversation_id": None}],
        )
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        await service.add_insight(user_id, "second insight", None, mock_session)

        assert len(memory.learning_insights) == 2
        assert memory.learning_insights[1]["insight"] == "second insight"


class TestAddRecurringQuestion:
    async def test_increments_topic_count(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(user_id, recurring_questions={"epidemiology": 2})
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        await service.add_recurring_question(user_id, "epidemiology", mock_session)

        assert memory.recurring_questions["epidemiology"] == 3

    async def test_initializes_new_topic_at_one(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(user_id, recurring_questions={})
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        await service.add_recurring_question(user_id, "biostatistics", mock_session)

        assert memory.recurring_questions["biostatistics"] == 1


class TestFormatForPrompt:
    async def test_returns_empty_string_for_new_user(self, service, mock_session):
        user_id = uuid.uuid4()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        result = await service.format_for_prompt(user_id, mock_session)

        assert result == ""

    async def test_produces_summary_within_200_tokens(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(
            user_id,
            difficulty_domains={"biostatistics": 5, "epidemiology": 3, "surveillance": 2},
            preferred_explanation_style="analogies",
            preferred_country_examples=["SN", "ML", "BF"],
            recurring_questions={"incidence": 4, "prevalence": 3},
            declared_goals={"primary": "master biostatistics for thesis"},
            learning_insights=[
                {"insight": "confuses incidence and prevalence", "conversation_id": None},
                {"insight": "struggles with odds ratio calculations", "conversation_id": None},
            ],
        )
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        result = await service.format_for_prompt(user_id, mock_session)

        assert result != ""
        token_estimate = len(result.split())
        assert token_estimate <= 200, f"Summary too long: {token_estimate} words"

    async def test_includes_key_fields_in_summary(self, service, mock_session):
        user_id = uuid.uuid4()
        memory = _make_memory(
            user_id,
            preferred_explanation_style="analogies",
            difficulty_domains={"biostatistics": 5},
            recurring_questions={"incidence": 3},
        )
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=memory))
        )

        result = await service.format_for_prompt(user_id, mock_session)

        assert "analogies" in result
        assert "biostatistics" in result
        assert "incidence" in result


class TestMemoryInSystemPrompt:
    def test_memory_included_in_tutor_system_prompt(self):
        from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt

        context = TutorContext(
            user_level=1,
            user_language="fr",
            user_country="SN",
            learner_memory="Style: analogies\nStruggles with: biostatistics",
        )

        prompt = get_socratic_system_prompt(context, [])

        assert "Style: analogies" in prompt
        assert "biostatistics" in prompt
        assert "MÉMOIRE DE L'APPRENANT" in prompt

    def test_no_memory_section_when_memory_empty(self):
        from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt

        context = TutorContext(
            user_level=1,
            user_language="fr",
            user_country="SN",
            learner_memory=None,
        )

        prompt = get_socratic_system_prompt(context, [])

        assert "MÉMOIRE DE L'APPRENANT" not in prompt
