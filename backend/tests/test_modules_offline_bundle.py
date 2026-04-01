"""Tests for GET /api/v1/modules/{module_id}/offline-bundle."""

from httpx import AsyncClient


class TestModulesOfflineBundle:
    async def test_unauthenticated_returns_401(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/modules/M01/offline-bundle")
        assert response.status_code == 401

    async def test_invalid_module_code_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        response = await client.get("/api/v1/modules/M99/offline-bundle", headers=auth_headers)
        assert response.status_code == 404

    async def test_invalid_module_id_format_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        response = await client.get(
            "/api/v1/modules/not-a-uuid-or-code/offline-bundle",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_valid_uuid_module_not_found_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/modules/{fake_uuid}/offline-bundle",
            headers=auth_headers,
        )
        assert response.status_code == 404
