from httpx import AsyncClient


async def test_root_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    # Service name is env-driven (default "sira-api"); must not carry the
    # pre-generalization "santepublique-aof-api" string.
    assert data["service"] == "sira-api"
    assert "santepublique" not in data["service"]


async def test_api_v1_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_openapi_description_has_no_west_africa_health_tagline(
    client: AsyncClient,
) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    description = response.json().get("info", {}).get("description", "") or ""
    lowered = description.lower()
    assert "public health in west africa" not in lowered
    assert "santé publique" not in lowered
