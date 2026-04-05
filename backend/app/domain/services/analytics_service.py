"""Analytics service — event ingestion and summary aggregation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.usage_event import UsageEvent

logger = structlog.get_logger()


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ingest_event(
        self,
        event_name: str,
        properties: dict[str, Any] | None,
        user_id: uuid.UUID | None,
        session_id: str | None,
    ) -> UsageEvent:
        event = UsageEvent(
            id=uuid.uuid4(),
            user_id=user_id,
            event_name=event_name,
            properties=properties,
            session_id=session_id,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        logger.info(
            "Analytics event ingested",
            event_name=event_name,
            user_id=str(user_id) if user_id else None,
            event_id=str(event.id),
        )
        return event

    async def ingest_batch(
        self,
        events: list[dict[str, Any]],
        user_id: uuid.UUID | None,
    ) -> int:
        objects = []
        for raw in events:
            objects.append(
                UsageEvent(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    event_name=raw["event_name"],
                    properties=raw.get("properties"),
                    session_id=raw.get("session_id"),
                )
            )
        self.db.add_all(objects)
        await self.db.commit()
        logger.info(
            "Analytics batch ingested",
            count=len(objects),
            user_id=str(user_id) if user_id else None,
        )
        return len(objects)

    async def get_summary(self, period_days: int) -> dict[str, Any]:
        since = datetime.now(tz=UTC) - timedelta(days=period_days)

        total_events_result = await self.db.execute(
            select(func.count(UsageEvent.id)).where(UsageEvent.created_at >= since)
        )
        total_events: int = total_events_result.scalar_one() or 0

        unique_users_result = await self.db.execute(
            select(func.count(func.distinct(UsageEvent.user_id))).where(
                UsageEvent.created_at >= since,
                UsageEvent.user_id.is_not(None),
            )
        )
        unique_users: int = unique_users_result.scalar_one() or 0

        events_by_type_result = await self.db.execute(
            select(UsageEvent.event_name, func.count(UsageEvent.id).label("cnt"))
            .where(UsageEvent.created_at >= since)
            .group_by(UsageEvent.event_name)
            .order_by(func.count(UsageEvent.id).desc())
        )
        events_by_type: dict[str, int] = {row.event_name: row.cnt for row in events_by_type_result}

        dau_result = await self.db.execute(
            text(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       COUNT(DISTINCT user_id) AS cnt
                FROM usage_events
                WHERE created_at >= :since
                  AND user_id IS NOT NULL
                GROUP BY day
                ORDER BY day
                """
            ).bindparams(since=since)
        )
        daily_active_users = [{"date": str(row.day), "count": row.cnt} for row in dau_result]

        top_modules_result = await self.db.execute(
            text(
                """
                SELECT properties->>'module_id' AS module_id,
                       COUNT(*) AS event_count
                FROM usage_events
                WHERE created_at >= :since
                  AND properties->>'module_id' IS NOT NULL
                GROUP BY properties->>'module_id'
                ORDER BY event_count DESC
                LIMIT 10
                """
            ).bindparams(since=since)
        )
        top_modules = [
            {"module_id": row.module_id, "event_count": row.event_count}
            for row in top_modules_result
        ]

        quiz_started_result = await self.db.execute(
            select(func.count(UsageEvent.id)).where(
                UsageEvent.created_at >= since,
                UsageEvent.event_name == "quiz_started",
            )
        )
        quiz_started: int = quiz_started_result.scalar_one() or 0

        quiz_completed_result = await self.db.execute(
            select(func.count(UsageEvent.id)).where(
                UsageEvent.created_at >= since,
                UsageEvent.event_name == "quiz_completed",
            )
        )
        quiz_completed: int = quiz_completed_result.scalar_one() or 0

        quiz_completion_rate = round(quiz_completed / quiz_started, 4) if quiz_started > 0 else 0.0

        return {
            "period": f"{period_days}d",
            "total_events": total_events,
            "unique_users": unique_users,
            "events_by_type": events_by_type,
            "daily_active_users": daily_active_users,
            "top_modules": top_modules,
            "quiz_completion_rate": quiz_completion_rate,
        }
