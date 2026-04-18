"""Regression tests for /api/v1/settings/public branding payload (issue #1618)."""

from httpx import AsyncClient


async def test_settings_public_includes_branding_defaults(client: AsyncClient) -> None:
    response = await client.get("/api/v1/settings/public")
    assert response.status_code == 200

    payload = response.json()
    assert "branding" in payload, "response must include a branding block"

    branding = payload["branding"]
    required_keys = {
        "app_name",
        "app_short_name",
        "app_description_fr",
        "app_description_en",
        "tagline_fr",
        "tagline_en",
        "theme_color",
    }
    assert required_keys.issubset(branding.keys())


async def test_branding_defaults_are_generic(client: AsyncClient) -> None:
    """Default branding must not leak the pre-generalization health copy."""
    response = await client.get("/api/v1/settings/public")
    branding = response.json()["branding"]

    stale = ["santé publique", "sante publique", "public health", "west africa"]
    for key in ("app_name", "app_description_fr", "app_description_en", "tagline_fr", "tagline_en"):
        value = (branding.get(key) or "").lower()
        for needle in stale:
            assert needle not in value, f"{key} leaks stale copy: {value!r}"


async def test_settings_public_still_includes_settings_dict(client: AsyncClient) -> None:
    """Back-compat: existing settings dict must still be present."""
    response = await client.get("/api/v1/settings/public")
    assert "settings" in response.json()
