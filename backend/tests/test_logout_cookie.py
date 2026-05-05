"""Tests for POST /api/v1/auth/logout cookie-mode handling (#2112).

The endpoint must accept an empty body and read the `refresh_token` from
the HttpOnly cookie. The body fallback is kept for cross-deploy
compatibility but is no longer required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_logout_with_cookie_no_body() -> None:
    """Empty-body logout succeeds when the refresh_token cookie is present.

    The pre-#2112 behaviour returned 422 here ("missing field
    refresh_token in body"). With the cookie fallback, the handler reads
    from cookie and the call returns 200.
    """
    with patch(
        "app.api.v1.local_auth.LocalAuthService.logout",
        new=AsyncMock(return_value=True),
    ) as mock:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/auth/logout",
                cookies={"refresh_token": "fake-cookie-token"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "Logged out"
    # Service should have been called with the cookie value, not None.
    mock.assert_awaited_once_with("fake-cookie-token")
    # Set-Cookie should clear the refresh_token cookie.
    set_cookie_headers = [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]
    refresh_clears = [c for c in set_cookie_headers if c.startswith("refresh_token=")]
    assert refresh_clears, f"expected refresh_token clear cookie, got {set_cookie_headers}"
    # Must clear with Max-Age=0 (or expires) and HttpOnly.
    assert any(
        "Max-Age=0" in c or "max-age=0" in c.lower() or "expires=" in c.lower()
        for c in refresh_clears
    )
    assert any("httponly" in c.lower() for c in refresh_clears)


async def test_logout_with_body_still_works() -> None:
    """Cross-deploy compatibility: the body path still works when
    older clients send `{"refresh_token": "..."}`.
    """
    with patch(
        "app.api.v1.local_auth.LocalAuthService.logout",
        new=AsyncMock(return_value=True),
    ) as mock:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "body-token"},
            )

    assert resp.status_code == 200
    mock.assert_awaited_once_with("body-token")


async def test_logout_with_no_token_at_all_still_clears_cookie() -> None:
    """If neither body nor cookie is present, logout must still 200 and
    clear the cookie (best-effort logout — never strands the user).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/logout")

    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out"
    set_cookie_headers = [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]
    refresh_clears = [c for c in set_cookie_headers if c.startswith("refresh_token=")]
    assert refresh_clears, "cookie should still be cleared even with no token"


async def test_logout_body_takes_precedence_over_cookie() -> None:
    """When both are present, body wins (matches the /refresh handler)."""
    with patch(
        "app.api.v1.local_auth.LocalAuthService.logout",
        new=AsyncMock(return_value=True),
    ) as mock:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "from-body"},
                cookies={"refresh_token": "from-cookie"},
            )

    assert resp.status_code == 200
    mock.assert_awaited_once_with("from-body")
