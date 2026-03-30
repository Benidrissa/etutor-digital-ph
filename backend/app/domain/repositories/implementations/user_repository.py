"""SQLAlchemy implementation of UserRepositoryProtocol."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ...models.user import User

logger = get_logger(__name__)


class UserRepository:
    """SQLAlchemy implementation of user repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        try:
            stmt = select(User).where(User.id == user_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error("Failed to get user by ID", user_id=str(user_id), error=str(e))
            raise

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email address."""
        try:
            stmt = select(User).where(User.email == email)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error("Failed to get user by email", email=email, error=str(e))
            raise

    async def create(self, user: User) -> User:
        """Create new user."""
        try:
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
            return user
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to create user", user_id=str(user.id), error=str(e))
            raise

    async def update(self, user: User) -> User:
        """Update existing user."""
        try:
            await self.session.merge(user)
            await self.session.commit()
            await self.session.refresh(user)
            return user
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update user", user_id=str(user.id), error=str(e))
            raise

    async def delete(self, user: User) -> None:
        """Delete user and related data."""
        try:
            await self.session.delete(user)
            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete user", user_id=str(user.id), error=str(e))
            raise

    async def list_users(
        self, offset: int = 0, limit: int = 20, filters: dict[str, Any] | None = None
    ) -> list[User]:
        """List users with pagination."""
        try:
            stmt = select(User)

            # Apply filters
            if filters:
                if "country" in filters:
                    stmt = stmt.where(User.country == filters["country"])
                if "current_level" in filters:
                    stmt = stmt.where(User.current_level == filters["current_level"])
                if "preferred_language" in filters:
                    stmt = stmt.where(User.preferred_language == filters["preferred_language"])

            # Apply pagination
            stmt = stmt.offset(offset).limit(limit)
            stmt = stmt.order_by(User.created_at.desc())

            result = await self.session.execute(stmt)
            return list(result.scalars().all())

        except Exception as e:
            logger.error("Failed to list users", offset=offset, limit=limit, error=str(e))
            raise
