"""Unskipped version of test_courses to see the actual error."""
import uuid
import pytest
from httpx import AsyncClient
from app.domain.models.user import UserRole
from app.domain.services.jwt_auth_service import JWTAuthService

def _make_headers(role: str = "user", user_id: str | None = None) -> dict:
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id=user_id or str(uuid.uuid4()),
        email=f"{role}@example.com",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def admin_with_id_headers():
    admin_id_str = str(uuid.uuid4())
    return _make_headers(role=UserRole.admin.value, user_id=admin_id_str)

@pytest.mark.asyncio
async def test_catalog_accessible_without_auth(authenticated_client):
    """GET /api/v1/courses must return 200 without auth (no auth header sent)."""
    response = await authenticated_client.get("/api/v1/courses")
    assert response.status_code == 200
