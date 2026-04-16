"""Session cache implementation using Redis."""

import json
from datetime import datetime
from uuid import uuid4

import structlog

from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)


class SessionCache:
    """Redis-based session cache for user sessions and temporary data."""

    def __init__(self, default_ttl: int = 3600):
        """Initialize session cache.

        Args:
            default_ttl: Default time-to-live in seconds (1 hour)
        """
        self.default_ttl = default_ttl
        self.key_prefix = "session:"

    async def create_session(self, user_id: str, data: dict, ttl: int | None = None) -> str:
        """Create a new user session.

        Args:
            user_id: User identifier
            data: Session data to store
            ttl: Time-to-live in seconds

        Returns:
            str: Session ID
        """
        session_id = str(uuid4())
        cache_key = f"{self.key_prefix}{session_id}"
        ttl = ttl or self.default_ttl

        session_data = {
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_accessed": datetime.utcnow().isoformat(),
            "data": data,
        }

        try:
            await redis_client.setex(cache_key, ttl, json.dumps(session_data, default=str))

            logger.info(
                "Session created",
                session_id=session_id,
                user_id=user_id,
                ttl=ttl,
            )

            return session_id

        except Exception as exc:
            logger.error(
                "Failed to create session",
                session_id=session_id,
                user_id=user_id,
                exception=str(exc),
            )
            raise

    async def get_session(self, session_id: str) -> dict | None:
        """Get session data by session ID.

        Args:
            session_id: Session identifier

        Returns:
            dict: Session data or None if not found
        """
        cache_key = f"{self.key_prefix}{session_id}"

        try:
            data = await redis_client.get(cache_key)
            if not data:
                return None

            session_data = json.loads(data)

            # Update last accessed time
            session_data["last_accessed"] = datetime.utcnow().isoformat()
            await redis_client.setex(
                cache_key, self.default_ttl, json.dumps(session_data, default=str)
            )

            return session_data

        except Exception as exc:
            logger.error(
                "Failed to get session",
                session_id=session_id,
                exception=str(exc),
            )
            return None

    async def update_session(self, session_id: str, data: dict, ttl: int | None = None) -> bool:
        """Update session data.

        Args:
            session_id: Session identifier
            data: New session data
            ttl: Time-to-live in seconds

        Returns:
            bool: True if updated successfully
        """
        cache_key = f"{self.key_prefix}{session_id}"
        ttl = ttl or self.default_ttl

        try:
            # Get existing session
            existing_data = await self.get_session(session_id)
            if not existing_data:
                return False

            # Merge with new data
            existing_data["data"].update(data)
            existing_data["last_accessed"] = datetime.utcnow().isoformat()

            await redis_client.setex(cache_key, ttl, json.dumps(existing_data, default=str))

            logger.info(
                "Session updated",
                session_id=session_id,
                user_id=existing_data.get("user_id"),
            )

            return True

        except Exception as exc:
            logger.error(
                "Failed to update session",
                session_id=session_id,
                exception=str(exc),
            )
            return False

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            bool: True if deleted successfully
        """
        cache_key = f"{self.key_prefix}{session_id}"

        try:
            result = await redis_client.delete(cache_key)

            logger.info(
                "Session deleted",
                session_id=session_id,
                existed=bool(result),
            )

            return bool(result)

        except Exception as exc:
            logger.error(
                "Failed to delete session",
                session_id=session_id,
                exception=str(exc),
            )
            return False

    async def get_user_sessions(self, user_id: str) -> list[dict]:
        """Get all sessions for a user.

        Args:
            user_id: User identifier

        Returns:
            list: List of session data
        """
        try:
            # Scan for session keys (this is for debugging/admin use)
            pattern = f"{self.key_prefix}*"
            sessions = []

            async for key in redis_client.scan_iter(match=pattern):
                data = await redis_client.get(key)
                if data:
                    session_data = json.loads(data)
                    if session_data.get("user_id") == user_id:
                        session_data["session_id"] = key.replace(self.key_prefix, "")
                        sessions.append(session_data)

            return sessions

        except Exception as exc:
            logger.error(
                "Failed to get user sessions",
                user_id=user_id,
                exception=str(exc),
            )
            return []

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions (for maintenance).

        Returns:
            int: Number of sessions cleaned up
        """
        try:
            # Redis handles TTL expiration automatically
            # This method is for manual cleanup if needed
            pattern = f"{self.key_prefix}*"
            cleaned_count = 0

            async for key in redis_client.scan_iter(match=pattern):
                ttl = await redis_client.ttl(key)
                if ttl == -1:  # No expiry set
                    # Set default expiry
                    await redis_client.expire(key, self.default_ttl)
                elif ttl == -2:  # Key doesn't exist
                    cleaned_count += 1

            logger.info("Session cleanup completed", cleaned_count=cleaned_count)
            return cleaned_count

        except Exception as exc:
            logger.error("Session cleanup failed", exception=str(exc))
            return 0


# Global session cache instance
session_cache = SessionCache()


class GeneratedContentCache:
    """Cache for AI-generated content to reduce API calls."""

    def __init__(self):
        self.key_prefix = "content:"
        self.default_ttl = 3600 * 24 * 7  # 7 days

    async def get_cached_content(
        self, content_type: str, module_id: str, language: str, country: str = "CI"
    ) -> dict | None:
        """Get cached generated content.

        Args:
            content_type: Type of content (lesson, quiz, flashcard)
            module_id: Module identifier
            language: Language code
            country: Country code for contextualization

        Returns:
            dict: Cached content or None
        """
        cache_key = f"{self.key_prefix}{content_type}:{module_id}:{language}:{country}"

        try:
            data = await redis_client.get(cache_key)
            if data:
                content = json.loads(data)
                logger.info(
                    "Content cache hit",
                    content_type=content_type,
                    module_id=module_id,
                    language=language,
                )
                return content

            logger.debug(
                "Content cache miss",
                content_type=content_type,
                module_id=module_id,
                language=language,
            )
            return None

        except Exception as exc:
            logger.error(
                "Failed to get cached content",
                content_type=content_type,
                module_id=module_id,
                exception=str(exc),
            )
            return None

    async def cache_content(
        self,
        content_type: str,
        module_id: str,
        language: str,
        country: str,
        content: dict,
        ttl: int | None = None,
    ) -> bool:
        """Cache generated content.

        Args:
            content_type: Type of content
            module_id: Module identifier
            language: Language code
            country: Country code
            content: Content to cache
            ttl: Time-to-live in seconds

        Returns:
            bool: True if cached successfully
        """
        cache_key = f"{self.key_prefix}{content_type}:{module_id}:{language}:{country}"
        ttl = ttl or self.default_ttl

        try:
            await redis_client.setex(cache_key, ttl, json.dumps(content, default=str))

            logger.info(
                "Content cached",
                content_type=content_type,
                module_id=module_id,
                language=language,
                ttl=ttl,
            )

            return True

        except Exception as exc:
            logger.error(
                "Failed to cache content",
                content_type=content_type,
                module_id=module_id,
                exception=str(exc),
            )
            return False


# Global content cache instance
content_cache = GeneratedContentCache()
