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
_AGENT_CREATE_PATH = "/v3/video-agents"
_V3_CREATE_PATH = "/v3/videos"
_V3_STATUS_PATH_TEMPLATE = "/v3/videos/{video_id}"


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
        language: str,
        callback_url: str | None = None,
    ) -> CreateVideoResult:
        """Dispatch a new video job. Returns the HeyGen video_id.

        ``callback_url`` is optional: when omitted, HeyGen won't push
        a completion event and the caller is expected to poll
        ``get_video`` to learn about the terminal status. This keeps
        the client usable from multi-tenant deployments where there
        is no single stable public URL to register.
        """
        if not script.strip():
            raise HeyGenBadRequestError("script is empty")
        if not avatar_id:
            raise HeyGenBadRequestError("avatar_id is required")
        if not voice_id:
            raise HeyGenBadRequestError("voice_id is required")

        body: dict = {
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
            "caption": True,
        }
        if callback_url:
            body["callback_url"] = callback_url

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

    async def create_content_video(
        self,
        *,
        script: str,
        voice_id: str,
        image_url: str,
        language: str,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        callback_url: str | None = None,
    ) -> CreateVideoResult:
        """Dispatch a content-focused (no-avatar) HeyGen render.

        Uses the v3 ``/v3/videos`` endpoint with ``type="image"``: the
        narration voice plays over a static branded background with
        synced captions, no talking head. This is the uniform,
        web-ready path (16:9, 720p) that the product wants for every
        lesson regardless of domain.

        The image URL must be publicly reachable so HeyGen's renderer
        can fetch it — typically the frontend's branded asset served
        at the tenant's public hostname.
        """
        if not script.strip():
            raise HeyGenBadRequestError("script is empty")
        if not voice_id:
            raise HeyGenBadRequestError("voice_id is required")
        if not image_url:
            raise HeyGenBadRequestError("image_url is required")

        body: dict = {
            "type": "image",
            "image": {"type": "url", "url": image_url},
            "script": script,
            "voice_id": voice_id,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": "mp4",
        }
        if callback_url:
            body["callback_url"] = callback_url

        async def _call() -> httpx.Response:
            return await self._request("POST", _V3_CREATE_PATH, json=body)

        response = await _retry_transient(_call)
        data = response.json() or {}
        inner = data.get("data") or {}
        video_id = inner.get("video_id") or data.get("video_id")
        if not video_id:
            raise HeyGenError(f"HeyGen content video create returned no video_id: {data!r}")

        logger.info(
            "heygen.create_content_video.dispatched",
            video_id=video_id,
            language=language,
            script_chars=len(script),
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        )
        return CreateVideoResult(provider_video_id=str(video_id))

    async def create_video_agent(
        self,
        *,
        prompt: str,
        language: str,
        callback_url: str | None = None,
    ) -> CreateVideoResult:
        """Dispatch a Video Agent job — avatar/voice auto-picked.

        Use this when the tenant hasn't seeded explicit avatar/voice
        IDs; HeyGen's agent picks both from the prompt. Costs roughly
        double a Direct Video call but keeps the feature zero-config
        for fresh tenants. See ``/docs/choosing-the-right-video-api``.
        """
        if not prompt.strip():
            raise HeyGenBadRequestError("prompt is empty")

        body: dict = {"prompt": prompt}
        if callback_url:
            body["callback_url"] = callback_url

        async def _call() -> httpx.Response:
            return await self._request("POST", _AGENT_CREATE_PATH, json=body)

        response = await _retry_transient(_call)
        data = response.json() or {}
        inner = data.get("data") or {}
        video_id = inner.get("video_id") or data.get("video_id")
        if not video_id:
            raise HeyGenError(f"HeyGen agent create returned no video_id: {data!r}")
        logger.info(
            "heygen.create_video_agent.dispatched",
            video_id=video_id,
            language=language,
            prompt_chars=len(prompt),
        )
        return CreateVideoResult(provider_video_id=str(video_id))

    async def get_video(self, video_id: str, *, api_version: str = "v2") -> VideoStatus:
        """Fetch current status of a previously-dispatched video.

        ``api_version`` selects the status endpoint: ``"v2"`` for
        Direct Video (``/v2/video_status.get``) and ``"v3-agent"``
        for Video Agent (``/v3/videos/{id}``). The two response
        shapes differ slightly; we normalise both into the same
        ``VideoStatus``.
        """

        if api_version == "v3-agent":

            async def _call() -> httpx.Response:
                return await self._request(
                    "GET",
                    _V3_STATUS_PATH_TEMPLATE.format(video_id=video_id),
                )
        else:

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
        # v3 uses ``video_url`` per docs; v2 also returns ``video_url``.
        # Accept ``url`` as an additional fallback in case either
        # surface renames the field in a future minor revision.
        video_url = (
            inner.get("video_url") or inner.get("url") or data.get("video_url") or data.get("url")
        )
        return VideoStatus(
            provider_video_id=video_id,
            status=mapped,
            video_url=video_url,
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
