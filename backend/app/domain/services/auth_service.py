"""Authentication service for SantePublique AOF.

Handles user profile management and auth-related business logic.
Works with local FastAPI auth (pyotp + python-jose).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from structlog import get_logger

from ..models.user import User
from ..repositories.protocols import UserRepositoryProtocol

logger = get_logger(__name__)


class AuthService:
    """Service for authentication and user management operations."""

    def __init__(self, user_repo: UserRepositoryProtocol):
        self.user_repo = user_repo

    async def get_user_profile(self, user_id: UUID) -> dict[str, Any] | None:
        """Get user profile by ID.

        Args:
            user_id: User UUID from JWT claims

        Returns:
            User profile dictionary or None if not found
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return None

        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "preferred_language": user.preferred_language,
            "country": user.country,
            "professional_role": user.professional_role,
            "current_level": user.current_level,
            "streak_days": user.streak_days,
            "created_at": user.created_at.isoformat(),
            "last_active": user.last_active.isoformat(),
        }

    async def create_user_profile(
        self,
        user_id: UUID,
        email: str,
        name: str,
        preferred_language: str = "fr",
        country: str | None = None,
        professional_role: str | None = None,
    ) -> dict[str, Any]:
        """Create new user profile.

        Args:
            user_id: User UUID
            email: User email address
            name: Display name
            preferred_language: "fr" or "en"
            country: ECOWAS country code
            professional_role: Professional role description

        Returns:
            Created user profile

        Raises:
            ValueError: If user already exists or invalid data
        """
        # Check if user already exists
        existing = await self.user_repo.get_by_id(user_id)
        if existing:
            raise ValueError(f"User {user_id} already exists")

        # Validate language
        if preferred_language not in ["fr", "en"]:
            preferred_language = "fr"  # Default to French

        # Create user
        user = User(
            id=user_id,
            email=email,
            name=name,
            preferred_language=preferred_language,
            country=country,
            professional_role=professional_role,
            current_level=1,  # Start at beginner level
            streak_days=0,
            last_active=datetime.utcnow(),
        )

        created_user = await self.user_repo.create(user)

        logger.info(
            "Created user profile",
            user_id=str(user_id),
            email=email,
            language=preferred_language,
            country=country,
        )

        return await self.get_user_profile(created_user.id)

    async def update_user_profile(self, user_id: UUID, updates: dict[str, Any]) -> dict[str, Any]:
        """Update user profile.

        Args:
            user_id: User UUID
            updates: Fields to update (partial update)

        Returns:
            Updated user profile

        Raises:
            ValueError: If user not found or invalid updates
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Validate updates
        allowed_fields = {
            "name",
            "preferred_language",
            "country",
            "professional_role",
            "current_level",
        }
        invalid_fields = set(updates.keys()) - allowed_fields
        if invalid_fields:
            raise ValueError(f"Cannot update fields: {invalid_fields}")

        if "preferred_language" in updates and updates["preferred_language"] not in ["fr", "en"]:
            raise ValueError("preferred_language must be 'fr' or 'en'")

        if "current_level" in updates and not (1 <= updates["current_level"] <= 4):
            raise ValueError("current_level must be between 1 and 4")

        # Apply updates
        for field, value in updates.items():
            if hasattr(user, field):
                setattr(user, field, value)

        # Update last_active timestamp
        user.last_active = datetime.utcnow()

        updated_user = await self.user_repo.update(user)

        logger.info("Updated user profile", user_id=str(user_id), updates=list(updates.keys()))

        return await self.get_user_profile(updated_user.id)

    async def update_streak(self, user_id: UUID) -> int:
        """Update user's daily learning streak.

        Increments streak if user has been active today, resets if missed days.

        Args:
            user_id: User UUID

        Returns:
            Updated streak count

        Raises:
            ValueError: If user not found
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        now = datetime.utcnow()
        last_active = user.last_active

        # Calculate days since last activity
        days_diff = (now.date() - last_active.date()).days

        if days_diff == 0:
            # Same day - no change to streak
            new_streak = user.streak_days
        elif days_diff == 1:
            # Consecutive day - increment streak
            new_streak = user.streak_days + 1
        else:
            # Missed days - reset streak
            new_streak = 1

        # Update user
        user.streak_days = new_streak
        user.last_active = now
        await self.user_repo.update(user)

        logger.info(
            "Updated user streak",
            user_id=str(user_id),
            old_streak=user.streak_days,
            new_streak=new_streak,
            days_diff=days_diff,
        )

        return new_streak

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Get user profile by email address.

        Args:
            email: User email address

        Returns:
            User profile or None if not found
        """
        user = await self.user_repo.get_by_email(email)
        if not user:
            return None

        return await self.get_user_profile(user.id)

    async def delete_user_data(self, user_id: UUID) -> None:
        """Delete all user data (GDPR compliance).

        Args:
            user_id: User UUID to delete

        Note:
            Deletes all user data from the database (GDPR right to erasure).
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            logger.warning("User not found for deletion", user_id=str(user_id))
            return

        # TODO: Delete related data in correct order:
        # 1. tutor_conversations
        # 2. flashcard_reviews
        # 3. quiz_attempts
        # 4. user_module_progress
        # 5. users (cascade will handle some relations)

        await self.user_repo.delete(user)

        logger.info("Deleted user data", user_id=str(user_id), email=user.email)
