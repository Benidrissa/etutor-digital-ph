"""Service for managing persistent learner memory across tutor sessions."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.learner_memory import LearnerMemory

logger = structlog.get_logger()

_EMPTY_DEFAULTS: dict[str, Any] = {
    "difficulty_domains": {},
    "preferred_explanation_style": None,
    "preferred_country_examples": [],
    "recurring_questions": {},
    "declared_goals": {},
    "learning_insights": {},
}


class LearnerMemoryService:
    """Service for reading and updating persistent learner memory."""

    async def get_memory(self, user_id: str | uuid.UUID, session: AsyncSession) -> dict[str, Any]:
        """Return learner memory for user, or empty defaults if none exists."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        result = await session.execute(
            select(LearnerMemory).where(LearnerMemory.user_id == user_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
            return dict(_EMPTY_DEFAULTS)

        return {
            "difficulty_domains": memory.difficulty_domains or {},
            "preferred_explanation_style": memory.preferred_explanation_style,
            "preferred_country_examples": memory.preferred_country_examples or [],
            "recurring_questions": memory.recurring_questions or {},
            "declared_goals": memory.declared_goals or {},
            "learning_insights": memory.learning_insights or {},
        }

    async def update_preference(
        self,
        user_id: str | uuid.UUID,
        preference_type: str,
        value: Any,
        session: AsyncSession,
    ) -> None:
        """Upsert a learner preference by type."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        memory = await self._get_or_create(user_id, session)

        if preference_type == "preferred_explanation_style":
            memory.preferred_explanation_style = str(value)
        elif preference_type == "preferred_country_examples":
            existing = list(memory.preferred_country_examples or [])
            if isinstance(value, list):
                for v in value:
                    if v not in existing:
                        existing.append(v)
            elif value not in existing:
                existing.append(str(value))
            memory.preferred_country_examples = existing
        elif preference_type == "difficulty_domains":
            domains = dict(memory.difficulty_domains or {})
            if isinstance(value, dict):
                domains.update(value)
            else:
                domains[str(value)] = domains.get(str(value), 0) + 1
            memory.difficulty_domains = domains
        elif preference_type == "declared_goals":
            goals = dict(memory.declared_goals or {})
            if isinstance(value, dict):
                goals.update(value)
            else:
                goals[str(uuid.uuid4())] = {"goal": str(value), "added_at": _now_iso()}
            memory.declared_goals = goals
        else:
            logger.warning("Unknown preference_type", preference_type=preference_type)
            return

        session.add(memory)
        await session.flush()

    async def add_insight(
        self,
        user_id: str | uuid.UUID,
        insight: str,
        conversation_id: str | uuid.UUID | None,
        session: AsyncSession,
    ) -> None:
        """Append a learning insight to the learner memory."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        memory = await self._get_or_create(user_id, session)

        insights = dict(memory.learning_insights or {})
        key = str(uuid.uuid4())
        insights[key] = {
            "insight": insight,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "added_at": _now_iso(),
        }
        memory.learning_insights = insights

        session.add(memory)
        await session.flush()

    async def add_recurring_question(
        self,
        user_id: str | uuid.UUID,
        topic: str,
        session: AsyncSession,
    ) -> None:
        """Increment the question count for a topic in recurring_questions."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        memory = await self._get_or_create(user_id, session)

        questions = dict(memory.recurring_questions or {})
        entry = questions.get(topic, {"count": 0, "last_asked_at": None})
        entry["count"] = entry["count"] + 1
        entry["last_asked_at"] = _now_iso()
        questions[topic] = entry
        memory.recurring_questions = questions

        session.add(memory)
        await session.flush()

    async def format_for_prompt(self, user_id: str | uuid.UUID, session: AsyncSession) -> str:
        """Return memory as a concise text summary (≤200 tokens) for Claude's system prompt."""
        memory = await self.get_memory(user_id, session)

        lines: list[str] = []

        difficulty = memory["difficulty_domains"]
        if difficulty:
            top = sorted(difficulty.items(), key=lambda x: x[1], reverse=True)[:3]
            topics = ", ".join(t for t, _ in top)
            lines.append(f"Difficulty domains: {topics}")

        style = memory["preferred_explanation_style"]
        if style:
            lines.append(f"Preferred explanation style: {style}")

        countries = memory["preferred_country_examples"]
        if countries:
            lines.append(f"Preferred country examples: {', '.join(countries[:3])}")

        recurring = memory["recurring_questions"]
        if recurring:
            top_q = sorted(recurring.items(), key=lambda x: x[1].get("count", 0), reverse=True)[:3]
            topics_q = ", ".join(t for t, _ in top_q)
            lines.append(f"Recurring questions on: {topics_q}")

        goals = memory["declared_goals"]
        if goals:
            goal_texts = [v.get("goal", str(v)) for v in goals.values()][:2]
            lines.append(f"Declared goals: {'; '.join(goal_texts)}")

        insights = memory["learning_insights"]
        if insights:
            recent = sorted(insights.values(), key=lambda x: x.get("added_at", ""), reverse=True)[
                :2
            ]
            insight_texts = [i["insight"] for i in recent]
            lines.append(f"Learning insights: {'; '.join(insight_texts)}")

        if not lines:
            return ""

        return "## LEARNER MEMORY\n" + "\n".join(f"- {line}" for line in lines)

    async def _get_or_create(self, user_id: uuid.UUID, session: AsyncSession) -> LearnerMemory:
        result = await session.execute(
            select(LearnerMemory).where(LearnerMemory.user_id == user_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
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
            session.add(memory)
            await session.flush()

        return memory


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
