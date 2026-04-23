"""Tests for the v3 Video Agent fallback and poller version routing.

Covers (issue #1798):

* ``HeyGenClient.create_video_agent`` — happy path body shape,
  empty-prompt rejection, and retry behaviour matches the v2 client.
* ``HeyGenClient.get_video`` — v3 path routing by ``api_version``.
* ``_api_version_for`` — poller reads ``media_metadata.api_version``
  with a v2 fallback for legacy rows.
* Poller delegates a v3-agent row to the correct status endpoint.
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
from app.tasks.heygen_poll import _api_version_for, _reconcile_one

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


# ── get_video routing ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_video_v2_hits_status_endpoint():
    http = _FakeHttp(
        _make_response(
            200,
            {"data": {"status": "processing", "video_url": None}},
        )
    )
    client = HeyGenClient(settings=_settings(), client=http)
    await client.get_video("vid-abc")  # default v2
    assert http.calls[0]["url"].endswith("/v2/video_status.get")
    assert http.calls[0]["kwargs"]["params"] == {"video_id": "vid-abc"}


@pytest.mark.asyncio
async def test_get_video_v3_agent_hits_videos_path():
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
    result = await client.get_video("vid-v3", api_version="v3-agent")
    assert http.calls[0]["url"].endswith("/v3/videos/vid-v3")
    # v3 payload still maps cleanly into our VideoStatus.
    assert isinstance(result, VideoStatus)
    assert result.status == "completed"
    assert result.video_url == "https://heygen.test/out.mp4"


# ── _api_version_for / poller routing ─────────────────────────────


def test_api_version_for_reads_metadata():
    record = _make_record(api_version="v3-agent")
    assert _api_version_for(record) == "v3-agent"


def test_api_version_for_always_polls_via_v3():
    # After #1874, every row polls via /v3/videos/{id} because HeyGen
    # deprecated /v2/video_status.get (returns 404). Legacy rows
    # (no metadata) or rows with unknown api_version values should
    # all be routed to the v3 status endpoint.
    record = _make_record(api_version=None)
    record.media_metadata = None
    assert _api_version_for(record) == "v3-agent"


def test_api_version_for_coerces_unknown_values_to_v3():
    record = _make_record()
    record.media_metadata = {"api_version": "not-a-real-version"}
    assert _api_version_for(record) == "v3-agent"


@pytest.mark.asyncio
async def test_reconcile_v3_row_uses_v3_api_version(monkeypatch):
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
    # Key assertion: poller passed the row's api_version to the client.
    client.get_video.assert_awaited_once()
    args, kwargs = client.get_video.call_args
    assert kwargs.get("api_version") == "v3-agent"
