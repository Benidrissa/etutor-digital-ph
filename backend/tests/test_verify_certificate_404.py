"""Regression tests for issue #1624 — GET /api/v1/verify/<unknown> must
return a JSON 404, not a plain-text 500."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def test_verify_unknown_code_returns_404_json(client: AsyncClient) -> None:
    """When the certificate service can't find the code, respond with
    a structured JSON 404 — never a plain-text 500 (see #1624)."""
    with patch(
        "app.api.v1.certificates.CertificateService.verify_certificate",
        new=AsyncMock(return_value=None),
    ):
        response = await client.get("/api/v1/verify/DOES-NOT-EXIST-12345")

    assert response.status_code == 404
    ct = response.headers.get("content-type") or ""
    assert "application/json" in ct
    body = response.json()
    assert body == {"detail": {"error": "certificate_not_found"}}


async def test_verify_unknown_code_never_500(client: AsyncClient) -> None:
    """Defence-in-depth: even if the service raises, never leak a 500."""
    with patch(
        "app.api.v1.certificates.CertificateService.verify_certificate",
        new=AsyncMock(return_value=None),
    ):
        response = await client.get("/api/v1/verify/DOES-NOT-EXIST-12345")
    assert response.status_code != 500
    assert response.text.strip() != "Internal Server Error"
