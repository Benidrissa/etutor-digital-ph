"""HeyGen Video Agent client — faceless explainer videos only.

HeyGen has no dedicated ``/faceless`` endpoint; every avatar-specific
endpoint (``/v2/video/generate``, ``/v3/videos`` with ``type=avatar``
or ``type=image``) renders a human character. The only way to get a
faceless explainer-style output is the Video Agent API:

* ``POST /v3/video-agents`` with ``{prompt, voice_id}`` and — critically —
  **no** ``avatar_id``. The agent generates b-roll + captions + narration
  driven entirely by the prompt.
* ``GET  /v3/videos/{video_id}`` to poll for completion (the v2 status
  endpoint returns 404 as of April 2026 — see #1874).
* Webhook signature verification (HMAC-SHA256 over the raw body using
  the shared secret stored in ``settings.heygen_webhook_secret``).

The prompt is expected to include explicit "no avatar / no on-screen
presenter / b-roll only" directives so HeyGen's agent doesn't drift back
into picking a talking head (#1879). Callers assemble the prompt; this
client just dispatches.

Retry policy: transient 5xx responses are retried with exponential
backoff; 4xx errors surface immediately because they indicate a bad
request (invalid voice id, overlong prompt, rotated key, insufficient
credit) that retries cannot fix.
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
_AGENT_CREATE_PATH = "/v3/video-agents"
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
    request (overlong prompt, rotated key, insufficient credit) never
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
    """Async HeyGen Video Agent API client — faceless explainers only."""

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

    async def create_video_agent(
        self,
        *,
        prompt: str,
        language: str,
        voice_id: str | None = None,
        callback_url: str | None = None,
    ) -> CreateVideoResult:
        """Dispatch a faceless explainer video via the Video Agent API.

        ``prompt`` must contain explicit faceless directives ("no avatar,
        no on-screen presenter, b-roll only") alongside the narration
        script — HeyGen's agent respects prompt instructions but will
        drift into picking a talking head if the prompt doesn't forbid
        one. See ``LessonVideoService`` for the canonical prompt shape.

        ``voice_id`` is optional. When supplied, HeyGen uses that specific
        voice for narration (stable output across dispatches). When
        omitted, HeyGen picks a voice per dispatch (non-deterministic).

        ``avatar_id`` is intentionally NOT a parameter — this client only
        produces faceless output (#1879). If a caller wants an avatar,
        add a separate method; don't bolt it onto this one.
        """
        if not prompt.strip():
            raise HeyGenBadRequestError("prompt is empty")

        body: dict = {"prompt": prompt}
        if voice_id:
            body["voice_id"] = voice_id
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
            voice_id=voice_id or "<auto>",
            prompt_chars=len(prompt),
        )
        return CreateVideoResult(provider_video_id=str(video_id))

    async def get_video(self, video_id: str) -> VideoStatus:
        """Fetch current status of a previously-dispatched video.

        Uses ``/v3/videos/{id}`` unconditionally (#1874). HeyGen's v2
        status endpoint returns 404 as of April 2026; the v3 endpoint
        accepts any video_id HeyGen has issued regardless of which
        create path produced it, since the video_id namespace is
        shared.
        """

        async def _call() -> httpx.Response:
            return await self._request(
                "GET",
                _V3_STATUS_PATH_TEMPLATE.format(video_id=video_id),
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
        video_url = (
            inner.get("video_url") or inner.get("url") or data.get("video_url") or data.get("url")
        )
        # HeyGen v3 returns rich failure details as ``failure_message``
        # + ``failure_code`` (e.g. "Insufficient credit"). Prefer those
        # so the DB ``error_message`` column carries an actionable
        # reason rather than the generic "heygen reported failure"
        # fallback that the service writes when ``error`` is None
        # (see #1878).
        error_parts: list[str] = []
        failure_message = inner.get("failure_message")
        failure_code = inner.get("failure_code")
        if failure_message:
            error_parts.append(str(failure_message))
        if failure_code and failure_code not in (failure_message or ""):
            error_parts.append(f"({failure_code})")
        rich_error = " ".join(error_parts) or None
        legacy_error = inner.get("error") or inner.get("message")
        return VideoStatus(
            provider_video_id=video_id,
            status=mapped,
            video_url=video_url,
            error=rich_error or legacy_error,
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
