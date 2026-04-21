"""HeyGen V2 video generation API client.

Wraps three endpoints that the rest of the stack needs:

* ``POST /v2/video/generate`` — dispatch a video job.
* ``GET  /v2/video_status.get`` — fallback poll when a webhook payload
  arrives without a ``video_url``.
* Webhook signature verification (HMAC-SHA256 over the raw body using
  the shared secret stored in ``settings.heygen_webhook_secret``).

The API itself is async/webhook-native: the create call returns a
``video_id`` in seconds; actual rendering takes several minutes and
HeyGen pushes ``avatar_video.success``/``avatar_video.failed`` events
to the ``callback_url`` we supply. The service layer relies on the
webhook for the happy path; polling is only used as a reconciliation
fallback.

Retry policy: transient 5xx responses are retried with exponential
backoff; 4xx errors surface immediately because they indicate a bad
request (invalid avatar/voice id, exceeded char limit, bad api key)
that retries cannot fix.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Awaitable, Callable

import httpx
import structlog

from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.video import CreateVideoResult, VideoStatus

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.heygen.com"
_CREATE_PATH = "/v2/video/generate"
_STATUS_PATH = "/v2/video_status.get"


class HeyGenError(RuntimeError):
    """Base class for HeyGen adapter errors."""


class HeyGenAuthError(HeyGenError):
    """Raised on 401/403 — usually a bad or rotated API key."""


class HeyGenBadRequestError(HeyGenError):
    """Raised on 4xx other than auth — malformed request body."""


class HeyGenTransientError(HeyGenError):
    """Raised on 5xx / network errors — safe to retry."""


async def _retry_transient[T](
    op: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
) -> T:
    """Retry ``op`` on transient errors with exponential backoff.

    Only ``HeyGenTransientError`` and ``httpx.TransportError`` are
    retried; 4xx/auth errors propagate on the first attempt so a bad
    request (wrong avatar_id, overlong script, rotated key) never
    silently fails three times before surfacing.
    """
    last_exc: BaseException | None = None
    delay = base_delay
    for attempt in range(1, attempts + 1):
        try:
            return await op()
        except (HeyGenTransientError, httpx.TransportError) as exc:
            last_exc = exc
            if attempt == attempts:
                break
            logger.warning(
                "heygen.retry",
                attempt=attempt,
                max_attempts=attempts,
                delay_s=delay,
                error=str(exc),
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
    assert last_exc is not None
    raise last_exc


class HeyGenClient:
    """Async HeyGen V2 API client."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> HeyGenClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        key = self._settings.heygen_api_key
        if not key:
            raise HeyGenAuthError("HEYGEN_API_KEY is not configured")
        return {
            "X-Api-Key": key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        response = await self._client.request(
            method, f"{_BASE_URL}{path}", headers=self._headers(), **kwargs
        )
        if response.status_code in (401, 403):
            raise HeyGenAuthError(
                f"HeyGen auth failed ({response.status_code}): {response.text[:200]}"
            )
        if 400 <= response.status_code < 500:
            raise HeyGenBadRequestError(
                f"HeyGen rejected request ({response.status_code}): {response.text[:200]}"
            )
        if response.status_code >= 500:
            raise HeyGenTransientError(f"HeyGen server error ({response.status_code})")
        return response

    async def create_video(
        self,
        *,
        script: str,
        avatar_id: str,
        voice_id: str,
        callback_url: str,
        language: str,
    ) -> CreateVideoResult:
        """Dispatch a new video job. Returns the HeyGen video_id."""
        if not script.strip():
            raise HeyGenBadRequestError("script is empty")
        if not avatar_id:
            raise HeyGenBadRequestError("avatar_id is required")
        if not voice_id:
            raise HeyGenBadRequestError("voice_id is required")

        body = {
            "video_inputs": [
                {
                    "character": {
                        "type": "avatar",
                        "avatar_id": avatar_id,
                    },
                    "voice": {
                        "type": "text",
                        "voice_id": voice_id,
                        "input_text": script,
                    },
                }
            ],
            "callback_url": callback_url,
            "caption": True,
        }

        async def _call() -> httpx.Response:
            return await self._request("POST", _CREATE_PATH, json=body)

        response = await _retry_transient(_call)
        data = response.json() or {}
        inner = data.get("data") or {}
        video_id = inner.get("video_id") or data.get("video_id")
        if not video_id:
            raise HeyGenError(f"HeyGen create returned no video_id: {data!r}")

        logger.info(
            "heygen.create_video.dispatched",
            video_id=video_id,
            language=language,
            script_chars=len(script),
        )
        return CreateVideoResult(provider_video_id=str(video_id))

    async def get_video(self, video_id: str) -> VideoStatus:
        """Fetch current status of a previously-dispatched video."""

        async def _call() -> httpx.Response:
            return await self._request(
                "GET",
                _STATUS_PATH,
                params={"video_id": video_id},
            )

        response = await _retry_transient(_call)
        data = response.json() or {}
        inner = data.get("data") or {}
        raw_status = (inner.get("status") or "").lower()
        mapped = {
            "pending": "pending",
            "waiting": "pending",
            "processing": "processing",
            "completed": "completed",
            "success": "completed",
            "failed": "failed",
            "error": "failed",
        }.get(raw_status, raw_status or "pending")
        return VideoStatus(
            provider_video_id=video_id,
            status=mapped,
            video_url=inner.get("video_url"),
            error=inner.get("error") or inner.get("message"),
        )

    def verify_webhook_signature(self, *, signature: str, raw_body: bytes) -> bool:
        """Return True when the header's HMAC-SHA256 matches our secret.

        HeyGen signs the raw request body with the shared secret the
        operator configured in the HeyGen dashboard; we compare the
        hex digest using ``hmac.compare_digest`` to avoid timing
        leaks. Missing secret or signature returns False rather than
        raising so callers can log and 403 cleanly.
        """
        secret = self._settings.heygen_webhook_secret
        if not secret or not signature:
            return False
        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        # Some dashboards prefix the signature with "sha256=".
        candidate = signature.strip()
        if candidate.startswith("sha256="):
            candidate = candidate[len("sha256=") :]
        return hmac.compare_digest(expected, candidate)
