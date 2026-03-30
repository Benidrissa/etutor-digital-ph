from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config.settings import Settings
from app.infrastructure.persistence.database import get_db_session


@lru_cache
def get_settings() -> Settings:
    return Settings()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session
