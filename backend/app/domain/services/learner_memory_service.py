"""Service for managing persistent learner memory — preferences and learning insights per user."""

from __future__ import annotations

import uuid
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
    "learning_insights": [],
}


class LearnerMemoryService:
    """Manages persistent learner memory across tutor sessions."""

    async def get_memory(self, user_id: uuid.UUID, session: AsyncSession) -> dict[str, Any]:
        """Return learner memory dict or empty defaults for a new user."""
        memory = await self._fetch(user_id, session)
        if memory is None:
            return dict(_EMPTY_DEFAULTS)
        return {
            "difficulty_domains": memory.difficulty_domains or {},
            "preferred_explanation_style": memory.preferred_explanation_style,
            "preferred_country_examples": memory.preferred_country_examples or [],
            "recurring_questions": memory.recurring_questions or {},
            "declared_goals": memory.declared_goals or {},
            "learning_insights": memory.learning_insights or [],
        }

    async def update_preference(
        self,
        user_id: uuid.UUID,
        preference_type: str,
        value: Any,
        session: AsyncSession,
    ) -> None:
        """Upsert a preference field for the learner."""
        allowed = {
            "difficulty_domains",
            "preferred_explanation_style",
            "preferred_country_examples",
            "recurring_questions",
            "declared_goals",
        }
        if preference_type not in allowed:
            logger.warning(
                "Unknown preference_type for learner memory",
                preference_type=preference_type,
                user_id=str(user_id),
            )
            return

        memory = await self._get_or_create(user_id, session)
        setattr(memory, preference_type, value)
        session.add(memory)
        await session.flush()

    async def add_insight(
        self,
        user_id: uuid.UUID,
        insight: str,
        conversation_id: uuid.UUID | None,
        session: AsyncSession,
    ) -> None:
        """Append a learning insight observed by the tutor."""
        memory = await self._get_or_create(user_id, session)
        current: list[dict[str, Any]] = list(memory.learning_insights or [])
        current.append(
            {
                "insight": insight,
                "conversation_id": str(conversation_id) if conversation_id else None,
            }
        )
        memory.learning_insights = current
        session.add(memory)
        await session.flush()

    async def add_recurring_question(
        self,
        user_id: uuid.UUID,
        topic: str,
        session: AsyncSession,
    ) -> None:
        """Increment the question count for a given topic."""
        memory = await self._get_or_create(user_id, session)
        counts: dict[str, Any] = dict(memory.recurring_questions or {})
        counts[topic] = counts.get(topic, 0) + 1
        memory.recurring_questions = counts
        session.add(memory)
        await session.flush()

    async def format_for_prompt(self, user_id: uuid.UUID, session: AsyncSession) -> str:
        """Return memory as ≤200-token text for inclusion in Claude's system prompt."""
        data = await self.get_memory(user_id, session)

        lines: list[str] = []

        if data["preferred_explanation_style"]:
            lines.append(f"Style: {data['preferred_explanation_style']}")

        if data["preferred_country_examples"]:
            countries = ", ".join(data["preferred_country_examples"][:3])
            lines.append(f"Countries: {countries}")

        if data["difficulty_domains"]:
            top = sorted(data["difficulty_domains"].items(), key=lambda x: x[1], reverse=True)[:3]
            domains = ", ".join(d for d, _ in top)
            lines.append(f"Struggles with: {domains}")

        if data["recurring_questions"]:
            top_q = sorted(data["recurring_questions"].items(), key=lambda x: x[1], reverse=True)[
                :3
            ]
            topics = ", ".join(t for t, _ in top_q)
            lines.append(f"Asks often about: {topics}")

        if data["declared_goals"]:
            goal_vals = list(data["declared_goals"].values())[:1]
            if goal_vals:
                lines.append(f"Goal: {str(goal_vals[0])[:80]}")

        if data["learning_insights"]:
            recent = data["learning_insights"][-2:]
            for item in recent:
                if isinstance(item, dict) and item.get("insight"):
                    lines.append(f"Note: {str(item['insight'])[:60]}")

        if not lines:
            return ""

        return "\n".join(lines)

    async def _fetch(self, user_id: uuid.UUID, session: AsyncSession) -> LearnerMemory | None:
        result = await session.execute(
            select(LearnerMemory).where(LearnerMemory.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_or_create(self, user_id: uuid.UUID, session: AsyncSession) -> LearnerMemory:
        memory = await self._fetch(user_id, session)
        if memory is None:
            memory = LearnerMemory(
                id=uuid.uuid4(),
                user_id=user_id,
                difficulty_domains={},
                preferred_explanation_style=None,
                preferred_country_examples=[],
                recurring_questions={},
                declared_goals={},
                learning_insights=[],
            )
            session.add(memory)
            await session.flush()
        return memory
