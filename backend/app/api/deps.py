from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repositories.implementations.user_repository import UserRepository
from app.domain.services.auth_service import AuthService
from app.domain.services.placement_service import PlacementService
from app.infrastructure.config.settings import Settings
from app.infrastructure.persistence.database import get_db_session as get_database_session


@lru_cache
def get_settings() -> Settings:
    return Settings()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_database_session():
        yield session


# Alias for compatibility with local auth service
get_db_session = get_db


async def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    """Get user repository instance."""
    return UserRepository(db)


async def get_auth_service(user_repo: UserRepository = Depends(get_user_repository)) -> AuthService:
    """Get auth service instance."""
    return AuthService(user_repo)


async def get_placement_service(
    user_repo: UserRepository = Depends(get_user_repository),
) -> PlacementService:
    """Get placement service instance."""
    return PlacementService(user_repo)
