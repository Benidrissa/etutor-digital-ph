"""Backfill last_interacted_at on user_course_enrollment from historical data.

Run once after migration 055:
    cd backend && python scripts/backfill_last_interacted.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def backfill() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique",
    )
    # Ensure async driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            text("""
                UPDATE user_course_enrollment uce
                SET last_interacted_at = sub.max_ts
                FROM (
                    SELECT ump.user_id, m.course_id,
                           MAX(ump.last_accessed) AS max_ts
                    FROM user_module_progress ump
                    JOIN modules m ON m.id = ump.module_id
                    WHERE ump.last_accessed IS NOT NULL
                    GROUP BY ump.user_id, m.course_id
                ) sub
                WHERE uce.user_id = sub.user_id
                  AND uce.course_id = sub.course_id
                  AND (uce.last_interacted_at IS NULL
                       OR uce.last_interacted_at < sub.max_ts)
            """)
        )
        await session.commit()
        print(f"Backfilled {result.rowcount} enrollment rows.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(backfill())
