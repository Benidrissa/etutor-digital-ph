"""Tests for the faceless Video Agent path and poller status routing.

Covers (issues #1798, #1874, #1879):

* ``HeyGenClient.create_video_agent`` — happy path body shape,
  empty-prompt rejection, and retry behaviour.
* ``HeyGenClient.get_video`` — always polls ``/v3/videos/{id}`` after
  HeyGen deprecated the v2 status endpoint (#1874); surfaces
  ``failure_message`` + ``failure_code`` in the mapped ``VideoStatus``.
* Poller delegates a generating row to the correct status endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.domain.models.generated_audio import GeneratedAudio
from app.infrastructure.video import VideoStatus
from app.infrastructure.video.heygen_client import (
    HeyGenBadRequestError,
    HeyGenClient,
    HeyGenTransientError,
)
from app.tasks.heygen_poll import _reconcile_one

# ── fakes ────────────────────────────────────────────────────────────


def _settings(api_key: str = "ak"):
    s = MagicMock()
    s.heygen_api_key = api_key
    s.heygen_webhook_secret = ""
    s.heygen_callback_base_url = ""
    return s


def _make_response(status_code: int, body: dict | None = None):
    req = httpx.Request("POST", "https://api.heygen.com/v3/video-agents")
    return httpx.Response(status_code=status_code, json=body or {}, request=req)


class _FakeHttp:
    """Records calls so we can assert on URL routing and retry counts."""

    def __init__(self, response: httpx.Response):
        self._response = response
        self.calls: list[dict[str, object]] = []

    async def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self._response

    async def aclose(self):
        pass


def _make_record(
    *,
    api_version: str | None = None,
    provider_video_id: str = "vid-abc",
) -> GeneratedAudio:
    record = GeneratedAudio(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        media_type="video",
        language="en",
        status="generating",
    )
    record.provider_video_id = provider_video_id
    record.created_at = datetime.now(UTC)
    if api_version is not None:
        record.media_metadata = {"api_version": api_version}
    return record


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass


# ── create_video_agent ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_video_agent_sends_prompt_and_returns_video_id():
    http = _FakeHttp(_make_response(200, {"data": {"video_id": "vid-v3"}}))
    client = HeyGenClient(settings=_settings(), client=http)

    result = await client.create_video_agent(
        prompt="A 3-minute summary about hygiene for children",
        language="en",
    )

    assert result.provider_video_id == "vid-v3"
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/v3/video-agents")
    assert call["kwargs"]["json"]["prompt"].startswith("A 3-minute")
    # No callback_url when not requested.
    assert "callback_url" not in call["kwargs"]["json"]


@pytest.mark.asyncio
async def test_create_video_agent_includes_callback_when_provided():
    http = _FakeHttp(_make_response(200, {"data": {"video_id": "vid-v3"}}))
    client = HeyGenClient(settings=_settings(), client=http)

    await client.create_video_agent(
        prompt="hello",
        language="fr",
        callback_url="https://api.example.test/cb",
    )
    assert http.calls[0]["kwargs"]["json"]["callback_url"] == "https://api.example.test/cb"


@pytest.mark.asyncio
async def test_create_video_agent_rejects_empty_prompt():
    http = _FakeHttp(_make_response(200, {"data": {"video_id": "x"}}))
    client = HeyGenClient(settings=_settings(), client=http)
    with pytest.raises(HeyGenBadRequestError):
        await client.create_video_agent(prompt="   ", language="en")


@pytest.mark.asyncio
async def test_create_video_agent_retries_5xx(monkeypatch):
    failing = _make_response(503, {"message": "upstream"})
    ok = _make_response(200, {"data": {"video_id": "vid-v3"}})
    http = MagicMock()
    http.request = AsyncMock(side_effect=[failing, ok])
    http.aclose = AsyncMock()

    async def _sleep(_s):
        return None

    import app.infrastructure.video.heygen_client as mod

    monkeypatch.setattr(mod.asyncio, "sleep", _sleep)

    client = HeyGenClient(settings=_settings(), client=http)
    result = await client.create_video_agent(prompt="hello", language="en")
    assert result.provider_video_id == "vid-v3"
    assert http.request.await_count == 2


@pytest.mark.asyncio
async def test_create_video_agent_surfaces_exhausted_transient(monkeypatch):
    http = MagicMock()
    http.request = AsyncMock(return_value=_make_response(500, {"message": "boom"}))
    http.aclose = AsyncMock()

    async def _sleep(_s):
        return None

    import app.infrastructure.video.heygen_client as mod

    monkeypatch.setattr(mod.asyncio, "sleep", _sleep)

    client = HeyGenClient(settings=_settings(), client=http)
    with pytest.raises(HeyGenTransientError):
        await client.create_video_agent(prompt="hello", language="en")


# ── get_video routing (always v3 after #1874/#1879) ────────────────


@pytest.mark.asyncio
async def test_get_video_hits_v3_videos_path():
    http = _FakeHttp(
        _make_response(
            200,
            {
                "data": {
                    "status": "completed",
                    "video_url": "https://heygen.test/out.mp4",
                }
            },
        )
    )
    client = HeyGenClient(settings=_settings(), client=http)
    result = await client.get_video("vid-abc")
    assert http.calls[0]["url"].endswith("/v3/videos/vid-abc")
    # v3 payload maps cleanly into our VideoStatus.
    assert isinstance(result, VideoStatus)
    assert result.status == "completed"
    assert result.video_url == "https://heygen.test/out.mp4"


@pytest.mark.asyncio
async def test_get_video_surfaces_failure_message():
    http = _FakeHttp(
        _make_response(
            200,
            {
                "data": {
                    "status": "failed",
                    "failure_code": "MOVIO_PAYMENT_INSUFFICIENT_CREDIT",
                    "failure_message": "Insufficient credit.",
                }
            },
        )
    )
    client = HeyGenClient(settings=_settings(), client=http)
    result = await client.get_video("vid-insufficient")
    assert result.status == "failed"
    assert result.error is not None
    assert "Insufficient credit" in result.error
    assert "MOVIO_PAYMENT_INSUFFICIENT_CREDIT" in result.error


# ── Poller routing ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_finalises_ready_rows(monkeypatch):
    record = _make_record(api_version="v3-agent")
    session = _FakeSession()

    client = AsyncMock()
    client.get_video = AsyncMock(
        return_value=VideoStatus(
            provider_video_id="vid-v3",
            status="completed",
            video_url="https://heygen.test/out.mp4",
        )
    )

    async def _fake_finalize(*args, **kwargs):
        return "ready"

    monkeypatch.setattr(
        "app.tasks.heygen_poll.finalize_lesson_video",
        _fake_finalize,
    )

    outcome = await _reconcile_one(
        record=record,
        client=client,
        session=session,  # type: ignore[arg-type]
    )
    assert outcome == "ready"
    # The poller calls get_video with just the video_id — no
    # api_version kwarg after #1874 since /v3/videos/{id} is the
    # only endpoint that works.
    client.get_video.assert_awaited_once_with(str(record.provider_video_id))
