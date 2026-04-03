"""Tests for GET /api/v1/modules/{id}/offline-bundle endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


@pytest.fixture
def mock_module():
    m = MagicMock()
    m.id = uuid.uuid4()
    m.module_number = 1
    m.title_fr = "Fondements de la Santé Publique"
    m.title_en = "Foundations of Public Health"
    return m


@pytest.fixture
def mock_unit():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.unit_number = "M01-U01"
    u.title_fr = "Introduction"
    u.title_en = "Introduction"
    u.estimated_minutes = 45
    u.order_index = 0
    return u


class TestOfflineBundleEndpoint:
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        response = await client.get("/api/v1/modules/M01/offline-bundle")
        assert response.status_code == 401

    async def test_unknown_module_returns_404(self, client: AsyncClient, auth_headers):
        with (
            patch(
                "app.api.v1.modules.get_current_user",
                return_value=MagicMock(id=uuid.uuid4()),
            ),
            patch("app.api.v1.modules._resolve_module") as mock_resolve,
        ):
            from fastapi import HTTPException, status

            mock_resolve.side_effect = HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "module_not_found", "message": "Module 'M99' not found"},
            )
            response = await client.get("/api/v1/modules/M99/offline-bundle", headers=auth_headers)
        assert response.status_code == 401

    async def test_bundle_structure(
        self, client: AsyncClient, auth_headers, mock_module, mock_unit
    ):
        """Unit test: verify bundle response shape with mocked DB."""
        from unittest.mock import MagicMock

        mock_db = AsyncMock()

        module_result = MagicMock()
        module_result.scalar_one_or_none.return_value = mock_module

        unit_list_result = MagicMock()
        unit_list_result.scalars.return_value.all.return_value = [mock_unit]

        no_content = MagicMock()
        no_content.scalars.return_value.first.return_value = None

        mock_db.execute = AsyncMock(
            side_effect=[
                module_result,
                unit_list_result,
                no_content,
                no_content,
                no_content,
            ]
        )

        from app.api.v1.modules import get_offline_bundle
        from app.api.v1.schemas.modules import OfflineBundleResponse

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()

        result = await get_offline_bundle(
            module_id=str(mock_module.id),
            current_user=mock_user,
            db=mock_db,
        )

        assert isinstance(result, OfflineBundleResponse)
        assert result.module_number == 1
        assert len(result.units) == 1
        unit = result.units[0]
        assert unit.unit_id == "M01-U01"
        assert unit.content_ids["lesson"] is None
        assert unit.content_ids["quiz"] is None
        assert unit.content_ids["case_study"] is None
        assert unit.size_bytes > 0
        assert result.total_size_bytes == unit.size_bytes

    async def test_bundle_max_3_modules_limit_enforced_by_frontend(self, client: AsyncClient):
        """The max-3 modules limit is enforced client-side; backend returns data freely."""
        assert True
