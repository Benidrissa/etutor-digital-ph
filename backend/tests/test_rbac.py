"""Tests for RBAC: require_role dependency, JWT role claim, and admin endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.user import UserRole
from app.domain.services.jwt_auth_service import JWTAuthService
from app.main import app

# ---------------------------------------------------------------------------
# JWT role claim tests
# ---------------------------------------------------------------------------


def test_jwt_includes_role_claim():
    """Access token payload must contain a 'role' claim."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="test-uuid",
        email="test@example.com",
        role=UserRole.admin.value,
    )
    payload = jwt_service.verify_access_token(token)
    assert payload["role"] == "admin"


def test_jwt_role_claim_defaults_to_user():
    """When no role is passed, AuthenticatedUser defaults to 'user'."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="test-uuid",
        email="test@example.com",
    )
    payload = jwt_service.verify_access_token(token)
    user = AuthenticatedUser(payload)
    assert user.role == UserRole.user.value


# ---------------------------------------------------------------------------
# require_role dependency tests (unit)
# ---------------------------------------------------------------------------


def _make_user(role: str) -> AuthenticatedUser:
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="test-uuid",
        email="test@example.com",
        role=role,
    )
    payload = jwt_service.verify_access_token(token)
    return AuthenticatedUser(payload)


@pytest.mark.asyncio
async def test_require_role_admin_blocks_user_role():
    """require_role(admin) must raise 403 for a 'user' role."""
    from fastapi import HTTPException

    checker = require_role(UserRole.admin)
    user = _make_user(UserRole.user.value)

    with pytest.raises(HTTPException) as exc_info:
        await checker(user=user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_admin_allows_admin_role():
    """require_role(admin) must pass for an 'admin' role."""
    checker = require_role(UserRole.admin)
    user = _make_user(UserRole.admin.value)
    result = await checker(user=user)
    assert result.role == UserRole.admin.value


@pytest.mark.asyncio
async def test_require_role_expert_allows_expert():
    """require_role(expert) must pass for an 'expert' role."""
    checker = require_role(UserRole.expert)
    user = _make_user(UserRole.expert.value)
    result = await checker(user=user)
    assert result.role == UserRole.expert.value


@pytest.mark.asyncio
async def test_require_role_expert_blocks_user():
    """require_role(expert) must raise 403 for a 'user' role."""
    from fastapi import HTTPException

    checker = require_role(UserRole.expert)
    user = _make_user(UserRole.user.value)

    with pytest.raises(HTTPException) as exc_info:
        await checker(user=user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_expert_or_admin_allows_admin():
    """require_role(expert, admin) must pass for an 'admin' role."""
    checker = require_role(UserRole.expert, UserRole.admin)
    user = _make_user(UserRole.admin.value)
    result = await checker(user=user)
    assert result.role == UserRole.admin.value


@pytest.mark.asyncio
async def test_require_role_admin_sub_admin_allows_sub_admin():
    """require_role(admin, sub_admin) must pass for a 'sub_admin' role."""
    checker = require_role(UserRole.admin, UserRole.sub_admin)
    user = _make_user(UserRole.sub_admin.value)
    result = await checker(user=user)
    assert result.role == UserRole.sub_admin.value


@pytest.mark.asyncio
async def test_require_role_admin_blocks_sub_admin():
    """require_role(admin) must raise 403 for a 'sub_admin' role (settings routes)."""
    from fastapi import HTTPException

    checker = require_role(UserRole.admin)
    user = _make_user(UserRole.sub_admin.value)

    with pytest.raises(HTTPException) as exc_info:
        await checker(user=user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_sub_admin_jwt_includes_role_claim():
    """Access token with sub_admin role must contain correct 'role' claim."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="test-uuid",
        email="subadmin@example.com",
        role=UserRole.sub_admin.value,
    )
    payload = jwt_service.verify_access_token(token)
    assert payload["role"] == "sub_admin"


# ---------------------------------------------------------------------------
# Admin endpoint integration tests (no DB required — auth layer only)
# ---------------------------------------------------------------------------


@pytest.fixture
def user_auth_headers():
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="user-uuid",
        email="user@example.com",
        role=UserRole.user.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers():
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="admin-uuid",
        email="admin@example.com",
        role=UserRole.admin.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sub_admin_auth_headers():
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="subadmin-uuid",
        email="subadmin@example.com",
        role=UserRole.sub_admin.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_users_endpoint_blocks_user_role(user_auth_headers):
    """GET /api/v1/admin/users must return 403 for user role."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/admin/users", headers=user_auth_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_users_endpoint_requires_auth():
    """GET /api/v1/admin/users must return 403 without auth header."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/admin/users")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_settings_blocks_sub_admin(sub_admin_auth_headers):
    """GET /api/v1/admin/settings must return 403 for sub_admin role."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/admin/settings", headers=sub_admin_auth_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_users_allows_sub_admin(sub_admin_auth_headers):
    """GET /api/v1/admin/users must return non-403 for sub_admin role (DB may fail, but auth passes)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/admin/users", headers=sub_admin_auth_headers)
    assert response.status_code != 403
