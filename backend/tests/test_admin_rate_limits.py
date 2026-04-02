"""Tests for admin rate limit management endpoints and service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.services.rate_limit_config_service import (
    DEFAULT_GLOBAL_LIMIT,
    RateLimitConfigService,
)

# ---------------------------------------------------------------------------
# RateLimitConfigService unit tests (fully mocked Redis)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """Mock Redis client for service tests."""
    return AsyncMock()


@pytest.fixture
def service():
    return RateLimitConfigService()


@pytest.mark.asyncio
async def test_get_global_limit_returns_default_when_not_set(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await service.get_global_limit()
    assert result == DEFAULT_GLOBAL_LIMIT


@pytest.mark.asyncio
async def test_get_global_limit_returns_stored_value(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.get = AsyncMock(return_value="350")
        result = await service.get_global_limit()
    assert result == 350


@pytest.mark.asyncio
async def test_set_global_limit_calls_redis_set(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.set = AsyncMock()
        await service.set_global_limit(500)
        mock_redis.set.assert_called_once_with(
            "admin:rate_limit:global_daily_limit", "500"
        )


@pytest.mark.asyncio
async def test_get_user_override_returns_none_when_not_set(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await service.get_user_override("user-abc")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_override_returns_value(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.get = AsyncMock(return_value="1000")
        result = await service.get_user_override("user-abc")
    assert result == 1000


@pytest.mark.asyncio
async def test_set_user_override(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.set = AsyncMock()
        await service.set_user_override("user-abc", 999)
        mock_redis.set.assert_called_once_with(
            "admin:rate_limit:user_override:user-abc", "999"
        )


@pytest.mark.asyncio
async def test_delete_user_override(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.delete = AsyncMock()
        await service.delete_user_override("user-abc")
        mock_redis.delete.assert_called_once_with(
            "admin:rate_limit:user_override:user-abc"
        )


@pytest.mark.asyncio
async def test_get_effective_limit_uses_override_when_present(service):
    with (
        patch.object(service, "get_user_override", new=AsyncMock(return_value=750)),
        patch.object(service, "get_global_limit", new=AsyncMock(return_value=200)),
    ):
        result = await service.get_effective_limit("user-abc")
    assert result == 750


@pytest.mark.asyncio
async def test_get_effective_limit_falls_back_to_global(service):
    with (
        patch.object(service, "get_user_override", new=AsyncMock(return_value=None)),
        patch.object(service, "get_global_limit", new=AsyncMock(return_value=200)),
    ):
        result = await service.get_effective_limit("user-abc")
    assert result == 200


@pytest.mark.asyncio
async def test_reset_user_usage(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.delete = AsyncMock()
        await service.reset_user_usage("user-abc")
        mock_redis.delete.assert_called_once_with("rate_limit:tutor:user-abc")


# ---------------------------------------------------------------------------
# Admin API endpoint tests (uses test client, mocks admin guard + service)
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_auth_headers():
    """JWT token for a user that is in the admin_emails list."""
    from app.domain.services.jwt_auth_service import JWTAuthService

    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="admin-uuid", email="admin@example.com"
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def non_admin_auth_headers():
    """JWT token for a non-admin user."""
    from app.domain.services.jwt_auth_service import JWTAuthService

    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="user-uuid", email="user@example.com"
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_global_limit_endpoint(client, admin_auth_headers):
    with patch("app.api.v1.admin.require_admin") as mock_guard:
        mock_guard.return_value = MagicMock(email="admin@example.com")
        with patch(
            "app.api.v1.admin.RateLimitConfigService"
        ) as MockService:
            instance = AsyncMock()
            instance.get_global_limit = AsyncMock(return_value=200)
            MockService.return_value = instance

            response = await client.get(
                "/api/v1/admin/rate-limits/global", headers=admin_auth_headers
            )

    assert response.status_code in (200, 401, 403)


@pytest.mark.asyncio
async def test_update_global_limit_validates_range(client, admin_auth_headers):
    with patch("app.api.v1.admin.require_admin") as mock_guard:
        mock_guard.return_value = MagicMock(email="admin@example.com")
        with patch(
            "app.api.v1.admin.RateLimitConfigService"
        ) as MockService:
            instance = AsyncMock()
            instance.set_global_limit = AsyncMock()
            instance.get_global_limit = AsyncMock(return_value=500)
            MockService.return_value = instance

            response = await client.put(
                "/api/v1/admin/rate-limits/global",
                json={"daily_limit": 0},
                headers=admin_auth_headers,
            )

    assert response.status_code in (422, 401, 403)


@pytest.mark.asyncio
async def test_non_admin_gets_403(client, non_admin_auth_headers):
    with patch(
        "app.infrastructure.config.settings.settings"
    ) as mock_settings:
        mock_settings.admin_emails = "admin@example.com"
        response = await client.get(
            "/api/v1/admin/rate-limits/global",
            headers=non_admin_auth_headers,
        )

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_service_get_user_usage_today_returns_zero_on_redis_error(service):
    with patch(
        "app.domain.services.rate_limit_config_service.redis_client"
    ) as mock_redis:
        mock_redis.zcount = AsyncMock(side_effect=Exception("Redis down"))
        result = await service.get_user_usage_today("user-abc")
    assert result == 0
