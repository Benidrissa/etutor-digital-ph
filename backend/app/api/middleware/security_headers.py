"""Security headers middleware (pure ASGI — no BaseHTTPMiddleware)."""

from starlette.types import ASGIApp, Receive, Scope, Send

from app.infrastructure.config.settings import settings


class SecurityHeadersMiddleware:
    """Add security headers to all HTTP responses.

    Uses pure ASGI to avoid BaseHTTPMiddleware's call_next task spawning,
    which causes event loop conflicts with asyncpg in tests.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"x-xss-protection", b"0"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (
                        b"permissions-policy",
                        b"accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
                        b"magnetometer=(), microphone=(), payment=(), usb=()",
                    ),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; "
                        b"script-src 'self'; "
                        b"style-src 'self' 'unsafe-inline'; "
                        b"img-src 'self' data:; "
                        b"font-src 'self'; "
                        b"connect-src 'self'; "
                        b"frame-ancestors 'none'; "
                        b"base-uri 'self'; "
                        b"form-action 'self'",
                    ),
                ]
                if settings.app_env == "production":
                    extra.append(
                        (
                            b"strict-transport-security",
                            b"max-age=63072000; includeSubDomains; preload",
                        )
                    )
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)
