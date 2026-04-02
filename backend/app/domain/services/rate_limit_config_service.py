"""Service for managing tutor rate limit configuration via Redis."""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)

REDIS_KEY_GLOBAL_LIMIT = "admin:rate_limit:global_daily_limit"
REDIS_KEY_USER_OVERRIDE_PREFIX = "admin:rate_limit:user_override:"
REDIS_KEY_TUTOR_USAGE_PREFIX = "rate_limit:tutor:"

DEFAULT_GLOBAL_LIMIT = 200


class RateLimitConfigService:
    """Manages tutor message rate limit configuration stored in Redis."""

    async def get_global_limit(self) -> int:
        """Return the current global daily tutor message limit."""
        try:
            value = await redis_client.get(REDIS_KEY_GLOBAL_LIMIT)
            if value is not None:
                return int(value)
        except Exception as exc:
            logger.error("Failed to fetch global rate limit from Redis", exception=str(exc))
        return DEFAULT_GLOBAL_LIMIT

    async def set_global_limit(self, limit: int) -> None:
        """Persist a new global daily tutor message limit."""
        await redis_client.set(REDIS_KEY_GLOBAL_LIMIT, str(limit))
        logger.info("Global tutor rate limit updated", new_limit=limit)

    async def get_user_override(self, user_id: str) -> int | None:
        """Return per-user override limit, or None if not set."""
        try:
            value = await redis_client.get(f"{REDIS_KEY_USER_OVERRIDE_PREFIX}{user_id}")
            if value is not None:
                return int(value)
        except Exception as exc:
            logger.error("Failed to fetch user override", user_id=user_id, exception=str(exc))
        return None

    async def set_user_override(self, user_id: str, limit: int) -> None:
        """Set a per-user daily limit override."""
        await redis_client.set(f"{REDIS_KEY_USER_OVERRIDE_PREFIX}{user_id}", str(limit))
        logger.info("Per-user rate limit override set", user_id=user_id, limit=limit)

    async def delete_user_override(self, user_id: str) -> None:
        """Remove per-user override (user falls back to global limit)."""
        await redis_client.delete(f"{REDIS_KEY_USER_OVERRIDE_PREFIX}{user_id}")
        logger.info("Per-user rate limit override removed", user_id=user_id)

    async def get_effective_limit(self, user_id: str) -> int:
        """Return the effective limit for a user (override or global)."""
        override = await self.get_user_override(user_id)
        if override is not None:
            return override
        return await self.get_global_limit()

    async def get_user_usage_today(self, user_id: str) -> int:
        """Return the number of tutor messages sent by a user today."""
        try:
            current_time = int(time.time())
            day_start = current_time - (current_time % 86400)
            cache_key = f"{REDIS_KEY_TUTOR_USAGE_PREFIX}{user_id}"
            count = await redis_client.zcount(cache_key, day_start, current_time)
            return int(count)
        except Exception as exc:
            logger.error("Failed to fetch user usage", user_id=user_id, exception=str(exc))
            return 0

    async def reset_user_usage(self, user_id: str) -> None:
        """Reset (delete) the daily usage counter for a user."""
        cache_key = f"{REDIS_KEY_TUTOR_USAGE_PREFIX}{user_id}"
        await redis_client.delete(cache_key)
        logger.info("Tutor rate limit counter reset", user_id=user_id)

    async def list_user_overrides(self) -> list[dict[str, Any]]:
        """List all users with per-user overrides."""
        try:
            pattern = f"{REDIS_KEY_USER_OVERRIDE_PREFIX}*"
            keys: list[str] = []
            async for key in redis_client.scan_iter(match=pattern):
                keys.append(key)

            result = []
            for key in keys:
                user_id = key.removeprefix(REDIS_KEY_USER_OVERRIDE_PREFIX)
                limit_value = await redis_client.get(key)
                usage = await self.get_user_usage_today(user_id)
                result.append(
                    {
                        "user_id": user_id,
                        "override_limit": int(limit_value) if limit_value else None,
                        "usage_today": usage,
                    }
                )
            return result
        except Exception as exc:
            logger.error("Failed to list user overrides", exception=str(exc))
            return []

    async def get_all_active_users_usage(self) -> list[dict[str, Any]]:
        """Return usage today for all users who have a Redis counter key."""
        try:
            pattern = f"{REDIS_KEY_TUTOR_USAGE_PREFIX}*"
            keys: list[str] = []
            async for key in redis_client.scan_iter(match=pattern):
                keys.append(key)

            current_time = int(time.time())
            day_start = current_time - (current_time % 86400)

            result = []
            for key in keys:
                user_id = key.removeprefix(REDIS_KEY_TUTOR_USAGE_PREFIX)
                usage = await redis_client.zcount(key, day_start, current_time)
                override = await self.get_user_override(user_id)
                global_limit = await self.get_global_limit()
                effective_limit = override if override is not None else global_limit
                result.append(
                    {
                        "user_id": user_id,
                        "usage_today": int(usage),
                        "effective_limit": effective_limit,
                        "override_limit": override,
                    }
                )
            return result
        except Exception as exc:
            logger.error("Failed to list all user usages", exception=str(exc))
            return []
