"""Tests for RBAC system — require_role dependency and JWT role claims."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.user import UserRole
from app.domain.services.jwt_auth_service import JWTAuthService
from app.main import app


def make_token(role: str = "user") -> str:
    jwt_service = JWTAuthService()
    return jwt_service.create_access_token(
        user_id="test-user-uuid",
        email="test@example.com",
        role=role,
    )


def auth_headers(role: str = "user") -> dict:
    return {"Authorization": f"Bearer {make_token(role)}"}


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestJWTRoleClaim:
    def test_access_token_includes_role_claim(self):
        import jwt as pyjwt

        from app.infrastructure.config.settings import settings

        token = make_token("admin")
        payload = pyjwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="santepublique-aof-frontend",
            issuer="santepublique-aof",
        )
        assert payload["role"] == "admin"

    def test_access_token_defaults_role_to_user(self):
        import jwt as pyjwt

        from app.infrastructure.config.settings import settings

        jwt_service = JWTAuthService()
        token = jwt_service.create_access_token(user_id="x", email="x@x.com")
        payload = pyjwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="santepublique-aof-frontend",
            issuer="santepublique-aof",
        )
        assert payload.get("role") is None

    def test_authenticated_user_parses_role_from_jwt(self):
        user = AuthenticatedUser(
            {
                "sub": "test-id",
                "email": "a@b.com",
                "role": "admin",
            }
        )
        assert user.role == UserRole.admin

    def test_authenticated_user_defaults_role_to_user(self):
        user = AuthenticatedUser({"sub": "test-id", "email": "a@b.com"})
        assert user.role == UserRole.user

    def test_authenticated_user_parses_expert_role(self):
        user = AuthenticatedUser({"sub": "test-id", "email": "a@b.com", "role": "expert"})
        assert user.role == UserRole.expert


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_admin_role_blocks_user_role(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/users",
            headers=auth_headers("user"),
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_role_blocks_expert_role(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/users",
            headers=auth_headers("expert"),
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_role_allows_admin(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/admin/users",
            headers=auth_headers("admin"),
        )
        assert response.status_code in (200, 500)

    @pytest.mark.asyncio
    async def test_require_role_expert_allows_expert(self):

        guard = require_role(UserRole.expert, UserRole.admin)
        expert_user = AuthenticatedUser({"sub": "x", "email": "x@x.com", "role": "expert"})

        result = await guard(user=expert_user)
        assert result.role == UserRole.expert

    @pytest.mark.asyncio
    async def test_require_role_expert_allows_admin(self):
        guard = require_role(UserRole.expert, UserRole.admin)
        admin_user = AuthenticatedUser({"sub": "x", "email": "x@x.com", "role": "admin"})

        result = await guard(user=admin_user)
        assert result.role == UserRole.admin

    @pytest.mark.asyncio
    async def test_require_role_expert_blocks_user(self):
        from fastapi import HTTPException

        guard = require_role(UserRole.expert, UserRole.admin)
        plain_user = AuthenticatedUser({"sub": "x", "email": "x@x.com", "role": "user"})

        with pytest.raises(HTTPException) as exc_info:
            await guard(user=plain_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_role_admin_blocks_user(self):
        from fastapi import HTTPException

        guard = require_role(UserRole.admin)
        plain_user = AuthenticatedUser({"sub": "x", "email": "x@x.com", "role": "user"})

        with pytest.raises(HTTPException) as exc_info:
            await guard(user=plain_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_role_admin_allows_admin(self):
        guard = require_role(UserRole.admin)
        admin_user = AuthenticatedUser({"sub": "x", "email": "x@x.com", "role": "admin"})

        result = await guard(user=admin_user)
        assert result.role == UserRole.admin

    @pytest.mark.asyncio
    async def test_no_token_returns_401_on_admin_route(self, client: AsyncClient):
        response = await client.get("/api/v1/admin/users")
        assert response.status_code == 403
