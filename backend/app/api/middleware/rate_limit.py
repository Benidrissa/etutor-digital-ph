"""Rate limiting middleware using Redis."""

import time
from collections.abc import Callable

import structlog
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.domain.services.rate_limit_config_service import (
    RateLimitConfigService,
)
from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)

_rate_limit_config_service = RateLimitConfigService()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using sliding window algorithm.

    Implements:
    - 100 requests per minute per IP (global limit)
    - Configurable tutor messages per day per user (stored in Redis, default 200)
    """

    def __init__(self, app, global_rate_limit: int = 100):
        """Initialize rate limiter.

        Args:
            app: FastAPI application
            global_rate_limit: Requests per minute per IP
        """
        super().__init__(app)
        self.global_rate_limit = global_rate_limit
        self.window_size = 60  # 1 minute window

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Apply rate limiting to requests."""
        client_ip = self._get_client_ip(request)

        try:
            # Check global rate limit (100 req/min/IP)
            await self._check_global_rate_limit(client_ip)

            # Check endpoint-specific limits if applicable
            await self._check_endpoint_specific_limits(request, client_ip)

            response = await call_next(request)
            return response

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Rate limiting error",
                client_ip=client_ip,
                exception=str(exc),
                path=request.url.path,
            )
            # Continue request on rate limiter failure
            response = await call_next(request)
            return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request headers."""
        # Check for forwarded headers (behind proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"

    async def _check_global_rate_limit(self, client_ip: str) -> None:
        """Check global rate limit using sliding window."""
        cache_key = f"rate_limit:global:{client_ip}"
        current_time = int(time.time())

        try:
            # Use Redis pipeline for atomic operations
            pipe = redis_client.pipeline()

            # Remove expired entries (older than window)
            window_start = current_time - self.window_size
            pipe.zremrangebyscore(cache_key, 0, window_start)

            # Count requests in current window
            pipe.zcard(cache_key)

            # Add current request
            pipe.zadd(cache_key, {str(current_time): current_time})

            # Set expiry for cleanup
            pipe.expire(cache_key, self.window_size)

            results = await pipe.execute()
            request_count = results[1]  # zcard result

            if request_count >= self.global_rate_limit:
                logger.warning(
                    "Global rate limit exceeded",
                    client_ip=client_ip,
                    request_count=request_count,
                    limit=self.global_rate_limit,
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "limit": self.global_rate_limit,
                        "window_minutes": 1,
                        "retry_after": 60,
                    },
                )

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Global rate limit check failed",
                client_ip=client_ip,
                exception=str(exc),
            )
            # Continue on Redis error

    async def _check_endpoint_specific_limits(self, request: Request, client_ip: str) -> None:
        """Check endpoint-specific rate limits."""
        path = request.url.path
        method = request.method

        # Tutor endpoint: configurable messages per day per user
        if path.startswith("/api/v1/tutor") and method == "POST":
            await self._check_tutor_rate_limit(request, client_ip)

    async def _check_tutor_rate_limit(self, request: Request, client_ip: str) -> None:
        """Check tutor message rate limit (configurable/day/user from Redis)."""
        user_identifier = _extract_user_id_from_request(request) or client_ip

        cache_key = f"rate_limit:tutor:{user_identifier}"
        current_time = int(time.time())
        day_start = current_time - (current_time % 86400)  # Start of current day

        try:
            # Fetch effective limit (per-user override or global config)
            daily_limit = await _rate_limit_config_service.get_effective_limit(user_identifier)

            # Count tutor messages today
            message_count = await redis_client.zcount(cache_key, day_start, current_time)

            if message_count >= daily_limit:
                logger.warning(
                    "Tutor rate limit exceeded",
                    user_identifier=user_identifier,
                    message_count=message_count,
                    limit=daily_limit,
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Daily tutor message limit exceeded",
                        "limit": daily_limit,
                        "window_hours": 24,
                        "retry_after": 86400 - (current_time % 86400),
                    },
                )

            # Add current message to count
            await redis_client.zadd(cache_key, {str(current_time): current_time})
            await redis_client.expire(cache_key, 86400)  # Expire after 24 hours

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Tutor rate limit check failed",
                user_identifier=user_identifier,
                exception=str(exc),
            )
            # Continue on Redis error


def _extract_user_id_from_request(request: Request) -> str | None:
    """Attempt to extract user_id from JWT Authorization header without full verification."""
    import base64
    import json

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padding = 4 - len(parts[1]) % 4
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "=" * padding)
        payload = json.loads(payload_bytes)
        return payload.get("sub")
    except Exception:
        return None


async def get_rate_limit_status(client_ip: str, user_id: str | None = None) -> dict:
    """Get current rate limit status for debugging/monitoring.

    Args:
        client_ip: Client IP address
        user_id: User ID (optional)

    Returns:
        dict: Rate limit status information
    """
    current_time = int(time.time())
    status: dict = {}

    try:
        # Global rate limit status
        global_key = f"rate_limit:global:{client_ip}"
        window_start = current_time - 60  # 1 minute window
        global_count = await redis_client.zcount(global_key, window_start, current_time)

        status["global"] = {
            "requests_in_window": global_count,
            "limit": 100,
            "window_minutes": 1,
            "remaining": max(0, 100 - global_count),
        }

        # Tutor rate limit status
        if user_id:
            tutor_key = f"rate_limit:tutor:{user_id}"
            day_start = current_time - (current_time % 86400)
            tutor_count = await redis_client.zcount(tutor_key, day_start, current_time)
            daily_limit = await _rate_limit_config_service.get_effective_limit(user_id)

            status["tutor"] = {
                "messages_today": tutor_count,
                "limit": daily_limit,
                "window_hours": 24,
                "remaining": max(0, daily_limit - tutor_count),
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
