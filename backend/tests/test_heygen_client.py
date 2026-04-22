"""Tests for HeyGen adapter webhook signature + retry semantics.

Also covers the web-ready MP4 sniff used in the HeyGen webhook
handler: we only accept objects with an ISO-BMFF ``ftyp`` box so
non-MP4 bytes never land silently in MinIO.
"""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.infrastructure.video.heygen_client import (
    HeyGenAuthError,
    HeyGenBadRequestError,
    HeyGenClient,
    HeyGenTransientError,
)


def _settings(secret: str = "wh-secret", api_key: str = "ak"):
    s = MagicMock()
    s.heygen_api_key = api_key
    s.heygen_webhook_secret = secret
    s.heygen_callback_base_url = "https://example.test"
    return s


def _sig(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid_hex():
    client = HeyGenClient(settings=_settings())
    body = b'{"event":"avatar_video.success"}'
    assert client.verify_webhook_signature(
        signature=_sig("wh-secret", body),
        raw_body=body,
    )


def test_verify_signature_accepts_sha256_prefix():
    client = HeyGenClient(settings=_settings())
    body = b'{"event":"avatar_video.success"}'
    prefixed = "sha256=" + _sig("wh-secret", body)
    assert client.verify_webhook_signature(
        signature=prefixed,
        raw_body=body,
    )


def test_verify_signature_rejects_wrong_secret():
    client = HeyGenClient(settings=_settings(secret="right"))
    body = b"payload"
    wrong = _sig("wrong", body)
    assert not client.verify_webhook_signature(signature=wrong, raw_body=body)


def test_verify_signature_rejects_empty_secret_or_header():
    client = HeyGenClient(settings=_settings(secret=""))
    assert not client.verify_webhook_signature(signature="anything", raw_body=b"x")
    client2 = HeyGenClient(settings=_settings(secret="s"))
    assert not client2.verify_webhook_signature(signature="", raw_body=b"x")


def test_verify_signature_resists_tampered_body():
    client = HeyGenClient(settings=_settings())
    body = b'{"event":"avatar_video.success","video_id":"abc"}'
    sig = _sig("wh-secret", body)
    tampered = body.replace(b"abc", b"xyz")
    assert not client.verify_webhook_signature(signature=sig, raw_body=tampered)


class _FakeHttp:
    """Minimal AsyncClient stand-in that returns a canned response."""

    def __init__(self, response: httpx.Response):
        self._response = response
        self.calls = 0

    async def request(self, *_args, **_kwargs):
        self.calls += 1
        return self._response

    async def aclose(self):
        pass


def _make_response(status_code: int, body: dict | None = None):
    req = httpx.Request("POST", "https://api.heygen.com/v2/video/generate")
    return httpx.Response(
        status_code=status_code,
        json=body or {},
        request=req,
    )


@pytest.mark.asyncio
async def test_create_video_fail_fast_on_4xx():
    http = _FakeHttp(_make_response(400, {"message": "bad avatar"}))
    client = HeyGenClient(settings=_settings(), client=http)
    with pytest.raises(HeyGenBadRequestError):
        await client.create_video(
            script="hello",
            avatar_id="a",
            voice_id="v",
            callback_url="https://example.test/cb",
            language="en",
        )
    assert http.calls == 1  # no retry on 4xx


@pytest.mark.asyncio
async def test_create_video_auth_error_surfaces():
    http = _FakeHttp(_make_response(401, {"message": "bad key"}))
    client = HeyGenClient(settings=_settings(), client=http)
    with pytest.raises(HeyGenAuthError):
        await client.create_video(
            script="hello",
            avatar_id="a",
            voice_id="v",
            callback_url="https://example.test/cb",
            language="en",
        )


@pytest.mark.asyncio
async def test_create_video_retries_on_5xx_then_succeeds(monkeypatch):
    success = _make_response(200, {"data": {"video_id": "vid-ok"}})
    failing = _make_response(503, {"message": "upstream"})

    http = MagicMock()
    http.request = AsyncMock(side_effect=[failing, failing, success])
    http.aclose = AsyncMock()

    # Avoid real sleeping.
    async def _sleep(_s):
        return None

    import app.infrastructure.video.heygen_client as mod

    monkeypatch.setattr(mod.asyncio, "sleep", _sleep)

    client = HeyGenClient(settings=_settings(), client=http)
    result = await client.create_video(
        script="hi",
        avatar_id="a",
        voice_id="v",
        callback_url="https://example.test/cb",
        language="en",
    )
    assert result.provider_video_id == "vid-ok"
    assert http.request.await_count == 3


@pytest.mark.asyncio
async def test_create_video_gives_up_after_max_attempts(monkeypatch):
    http = MagicMock()
    http.request = AsyncMock(return_value=_make_response(500, {"message": "boom"}))
    http.aclose = AsyncMock()

    async def _sleep(_s):
        return None

    import app.infrastructure.video.heygen_client as mod

    monkeypatch.setattr(mod.asyncio, "sleep", _sleep)

    client = HeyGenClient(settings=_settings(), client=http)
    with pytest.raises(HeyGenTransientError):
        await client.create_video(
            script="hi",
            avatar_id="a",
            voice_id="v",
            callback_url="https://example.test/cb",
            language="en",
        )
    assert http.request.await_count == 3


def test_is_web_ready_mp4_accepts_ftyp_header():
    from app.domain.services.lesson_video_service import is_web_ready_mp4

    # Minimal ISO-BMFF: size(4) + "ftyp"(4) + brand(4) padding
    mp4_head = b"\x00\x00\x00\x18" + b"ftyp" + b"isom" + b"\x00" * 4
    assert is_web_ready_mp4(mp4_head + b"rest-of-file")


def test_is_web_ready_mp4_rejects_webm_and_junk():
    from app.domain.services.lesson_video_service import is_web_ready_mp4

    # WebM / Matroska starts with 0x1A 0x45 0xDF 0xA3 — no ftyp box.
    webm_head = b"\x1a\x45\xdf\xa3" + b"\x00" * 20
    assert not is_web_ready_mp4(webm_head)
    assert not is_web_ready_mp4(b"")
    assert not is_web_ready_mp4(b"not a video")


@pytest.mark.asyncio
async def test_create_video_rejects_blank_inputs():
    http = _FakeHttp(_make_response(200, {"data": {"video_id": "x"}}))
    client = HeyGenClient(settings=_settings(), client=http)
    with pytest.raises(HeyGenBadRequestError):
        await client.create_video(
            script="   ",
            avatar_id="a",
            voice_id="v",
            callback_url="https://example.test/cb",
            language="en",
        )
    with pytest.raises(HeyGenBadRequestError):
        await client.create_video(
            script="hi",
            avatar_id="",
            voice_id="v",
            callback_url="https://example.test/cb",
            language="en",
        )
