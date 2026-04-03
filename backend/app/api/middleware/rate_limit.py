"""Rate limiting middleware using Redis."""

import time

import structlog
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)


class RateLimitMiddleware:
    """Rate limiting middleware using sliding window algorithm.

    Implements:
    - 100 requests per minute per IP (global limit)
    - 50 tutor messages per day per user (endpoint-specific)
    """

    def __init__(self, app: ASGIApp, global_rate_limit: int = 100) -> None:
        self.app = app
        self.global_rate_limit = global_rate_limit
        self.window_size = 60

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(scope)

        try:
            rate_limit_exceeded = await self._check_global_rate_limit(client_ip)
            if rate_limit_exceeded:
                response = JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit exceeded",
                        "limit": self.global_rate_limit,
                        "window_minutes": 1,
                        "retry_after": 60,
                    },
                )
                await response(scope, receive, send)
                return

            path = scope.get("path", "")
            method = scope.get("method", "")
            if path.startswith("/api/v1/tutor") and method == "POST":
                tutor_exceeded = await self._check_tutor_rate_limit(client_ip)
                if tutor_exceeded:
                    current_time = int(time.time())
                    response = JSONResponse(
                        status_code=429,
                        content={
                            "error": "Daily tutor message limit exceeded",
                            "limit": 200,
                            "window_hours": 24,
                            "retry_after": 86400 - (current_time % 86400),
                        },
                    )
                    await response(scope, receive, send)
                    return

        except Exception as exc:
            logger.error(
                "Rate limiting error",
                client_ip=client_ip,
                exception=str(exc),
            )

        await self.app(scope, receive, send)

    def _get_client_ip(self, scope: Scope) -> str:
        headers = dict(scope.get("headers", []))
        forwarded_for = headers.get(b"x-forwarded-for", b"").decode()
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            if ips:
                return ips[-1]

        real_ip = headers.get(b"x-real-ip", b"").decode()
        if real_ip:
            return real_ip.strip()

        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    async def _check_global_rate_limit(self, client_ip: str) -> bool:
        """Return True if rate limit exceeded, False otherwise."""
        cache_key = f"rate_limit:global:{client_ip}"
        current_time = int(time.time())

        try:
            pipe = redis_client.pipeline()
            window_start = current_time - self.window_size
            pipe.zremrangebyscore(cache_key, 0, window_start)
            pipe.zcard(cache_key)
            pipe.zadd(cache_key, {str(current_time): current_time})
            pipe.expire(cache_key, self.window_size)

            results = await pipe.execute()
            request_count = results[1]

            if request_count >= self.global_rate_limit:
                logger.warning(
                    "Global rate limit exceeded",
                    client_ip=client_ip,
                    request_count=request_count,
                    limit=self.global_rate_limit,
                )
                return True

        except Exception as exc:
            logger.error(
                "Global rate limit check failed",
                client_ip=client_ip,
                exception=str(exc),
            )

        return False

    async def _check_tutor_rate_limit(self, client_ip: str) -> bool:
        """Return True if tutor rate limit exceeded, False otherwise."""
        user_identifier = client_ip
        cache_key = f"rate_limit:tutor:{user_identifier}"
        current_time = int(time.time())
        day_start = current_time - (current_time % 86400)

        try:
            message_count = await redis_client.zcount(cache_key, day_start, current_time)

            if message_count >= 200:
                logger.warning(
                    "Tutor rate limit exceeded",
                    user_identifier=user_identifier,
                    message_count=message_count,
                )
                return True

            await redis_client.zadd(cache_key, {str(current_time): current_time})
            await redis_client.expire(cache_key, 86400)

        except Exception as exc:
            logger.error(
                "Tutor rate limit check failed",
                user_identifier=user_identifier,
                exception=str(exc),
            )

        return False


async def get_rate_limit_status(client_ip: str, user_id: str | None = None) -> dict:
    """Get current rate limit status for debugging/monitoring."""
    current_time = int(time.time())
    status: dict = {}

    try:
        global_key = f"rate_limit:global:{client_ip}"
        window_start = current_time - 60
        global_count = await redis_client.zcount(global_key, window_start, current_time)

        status["global"] = {
            "requests_in_window": global_count,
            "limit": 100,
            "window_minutes": 1,
            "remaining": max(0, 100 - global_count),
        }

        if user_id:
            tutor_key = f"rate_limit:tutor:{user_id}"
            day_start = current_time - (current_time % 86400)
            tutor_count = await redis_client.zcount(tutor_key, day_start, current_time)

            status["tutor"] = {
                "messages_today": tutor_count,
                "limit": 200,
                "window_hours": 24,
                "remaining": max(0, 50 - tutor_count),
            }

        return status

    except Exception as exc:
        logger.error(
            "Failed to get rate limit status",
            client_ip=client_ip,
            user_id=user_id,
            exception=str(exc),
        )
        return {"error": "Unable to fetch rate limit status"}
