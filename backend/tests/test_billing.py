"""Tests for billing endpoints: balance, packages, purchase, transactions, usage."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.billing import _get_credit_service
from app.domain.models.user import UserRole
from app.domain.services.credit_service import PackageNotFoundError
from app.domain.services.jwt_auth_service import JWTAuthService
from app.main import app


def _make_headers(role: str = "user", user_id: str | None = None) -> dict:
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id=user_id or str(uuid.uuid4()),
        email=f"{role}@test.com",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers():
    return _make_headers(role=UserRole.user.value)


def _mock_txn(
    txn_id: uuid.UUID | None = None,
    txn_type: str = "purchase",
    amount: int = 500,
    balance_after: int = 500,
    description: str = "Purchase: Essentiel / Essential",
) -> MagicMock:
    mock_txn = MagicMock()
    mock_txn.id = txn_id or uuid.uuid4()
    mock_txn.type = txn_type
    mock_txn.amount = amount
    mock_txn.balance_after = balance_after
    mock_txn.description = description
    mock_txn.created_at = datetime(2026, 4, 4, 11, 0, 0)
    return mock_txn


@pytest.mark.asyncio
async def test_balance_requires_auth():
    """GET /api/v1/billing/balance must return 401 without token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/billing/balance")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_packages_requires_auth():
    """GET /api/v1/billing/packages must return 401 without token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/billing/packages")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_transactions_requires_auth():
    """GET /api/v1/billing/transactions must return 401 without token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/billing/transactions")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_purchase_requires_auth():
    """POST /api/v1/billing/purchase must return 401 without token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/billing/purchase",
            json={"package_id": str(uuid.uuid4())},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_usage_requires_auth():
    """GET /api/v1/billing/usage must return 401 without token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/billing/usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_balance_returns_correct_schema(user_headers):
    """GET /api/v1/billing/balance returns CreditBalanceResponse."""
    balance_data = {
        "balance": 350,
        "total_purchased": 500,
        "total_spent": 150,
        "total_earned": 0,
    }
    mock_service = AsyncMock()
    mock_service.get_balance.return_value = balance_data

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/billing/balance", headers=user_headers)
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 200
    data = response.json()
    assert data["balance"] == 350
    assert data["total_purchased"] == 500
    assert data["total_spent"] == 150
    assert data["total_earned"] == 0


@pytest.mark.asyncio
async def test_list_packages_returns_list(user_headers):
    """GET /api/v1/billing/packages returns a list of packages."""
    pkg_id = uuid.uuid4()
    mock_pkg = MagicMock()
    mock_pkg.id = pkg_id
    mock_pkg.name_fr = "Essentiel"
    mock_pkg.name_en = "Essential"
    mock_pkg.credits = 500
    mock_pkg.price_xof = 8000
    mock_pkg.price_usd = 12.0

    mock_service = AsyncMock()
    mock_service.list_packages.return_value = [mock_pkg]

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/billing/packages", headers=user_headers)
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name_en"] == "Essential"
    assert data[0]["credits"] == 500


@pytest.mark.asyncio
async def test_purchase_creates_transaction(user_headers):
    """POST /api/v1/billing/purchase returns 201 with transaction."""
    pkg_id = uuid.uuid4()
    mock_txn = _mock_txn()

    mock_service = AsyncMock()
    mock_service.purchase.return_value = mock_txn

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/billing/purchase",
                json={"package_id": str(pkg_id)},
                headers=user_headers,
            )
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "purchase"
    assert data["amount"] == 500
    assert data["balance_after"] == 500


@pytest.mark.asyncio
async def test_purchase_package_not_found_returns_404(user_headers):
    """POST /api/v1/billing/purchase returns 404 for unknown package."""
    mock_service = AsyncMock()
    mock_service.purchase.side_effect = PackageNotFoundError("Package not found")

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/billing/purchase",
                json={"package_id": str(uuid.uuid4())},
                headers=user_headers,
            )
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_transactions_returns_paginated(user_headers):
    """GET /api/v1/billing/transactions returns paginated response."""
    mock_txn = _mock_txn()

    mock_service = AsyncMock()
    mock_service.list_transactions.return_value = {
        "items": [mock_txn],
        "total": 1,
        "page": 1,
        "limit": 20,
        "has_next": False,
    }

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/billing/transactions", headers=user_headers)
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["has_next"] is False
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_list_transactions_type_filter(user_headers):
    """GET /api/v1/billing/transactions?type=purchase passes filter to service."""
    mock_service = AsyncMock()
    mock_service.list_transactions.return_value = {
        "items": [],
        "total": 0,
        "page": 1,
        "limit": 20,
        "has_next": False,
    }

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/billing/transactions?type=purchase", headers=user_headers
            )
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 200
    mock_service.list_transactions.assert_called_once()
    call_kwargs = mock_service.list_transactions.call_args
    assert call_kwargs.kwargs.get("type_filter") == "purchase"


@pytest.mark.asyncio
async def test_get_usage_summary_monthly(user_headers):
    """GET /api/v1/billing/usage returns monthly usage summary."""
    mock_service = AsyncMock()
    mock_service.get_usage_summary.return_value = {
        "period": "monthly",
        "since": "2026-04-01T00:00:00+00:00",
        "total_credits_spent": 120,
        "breakdown": {"lesson_generation": 80, "tutor_chat": 40},
    }

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/billing/usage?period=monthly", headers=user_headers)
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 200
    data = response.json()
    assert data["period"] == "monthly"
    assert data["total_credits_spent"] == 120
    assert "lesson_generation" in data["breakdown"]


@pytest.mark.asyncio
async def test_get_usage_summary_daily(user_headers):
    """GET /api/v1/billing/usage?period=daily returns daily usage summary."""
    mock_service = AsyncMock()
    mock_service.get_usage_summary.return_value = {
        "period": "daily",
        "since": "2026-04-04T00:00:00+00:00",
        "total_credits_spent": 20,
        "breakdown": {"tutor_chat": 20},
    }

    app.dependency_overrides[_get_credit_service] = lambda: mock_service
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/billing/usage?period=daily", headers=user_headers)
    finally:
        app.dependency_overrides.pop(_get_credit_service, None)

    assert response.status_code == 200
    data = response.json()
    assert data["period"] == "daily"
    assert data["total_credits_spent"] == 20


@pytest.mark.asyncio
async def test_get_usage_summary_invalid_period(user_headers):
    """GET /api/v1/billing/usage with invalid period returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/billing/usage?period=yearly", headers=user_headers)

    assert response.status_code == 422
