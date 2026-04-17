"""Unit tests for qbank audio helpers + TTS dispatch.

DB/MinIO paths are intentionally out of scope — they're thin wrappers over
already-tested primitives. These tests pin down the behaviors that matter:
the spoken script format, size estimation, and the fact that unsupported
languages don't hit any TTS backend.
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.domain.services.qbank_audio_service import (
    QBankAudioService,
    build_audio_script,
    estimate_duration_seconds,
)


class _FakeQuestion:
    def __init__(self, text: str, options: list[str]):
        self.question_text = text
        self.options = options


def test_build_audio_script_french_prefix():
    q = _FakeQuestion("Que signifie ce panneau ?", ["Stop", "Céder", "Danger"])
    script = build_audio_script(q, "fr")
    assert script.startswith("Que signifie ce panneau ?")
    assert "Option A: Stop" in script
    assert "Option B: Céder" in script
    assert "Option C: Danger" in script
    assert script.endswith(".")


def test_build_audio_script_mms_languages_use_native_prefix():
    q = _FakeQuestion("Question", ["A", "B"])
    for lang, prefix in [("mos", "Tʋʋmde"), ("dyu", "Sugandili"), ("bam", "Sugandili")]:
        script = build_audio_script(q, lang)
        assert f"{prefix} A" in script
        assert f"{prefix} B" in script


def test_build_audio_script_handles_empty_options():
    q = _FakeQuestion("Just a question", [])
    script = build_audio_script(q, "fr")
    assert script == "Just a question."


def test_estimate_duration_seconds_opus_rate():
    # 30s clip at ~48 kbps = ~180 KB
    assert estimate_duration_seconds(180 * 1024) == 30
    # Always returns at least 1 second for tiny blobs
    assert estimate_duration_seconds(10) == 1


@pytest.mark.asyncio
async def test_synthesize_rejects_unsupported_language():
    svc = QBankAudioService(
        mms_client=types.SimpleNamespace(
            synthesize=AsyncMock(side_effect=AssertionError("should not be called")),
        )
    )
    with pytest.raises(HTTPException) as exc:
        await svc._synthesize_bytes("hi", "en")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_synthesize_dispatches_mms_languages_to_client():
    fake_mms = types.SimpleNamespace(synthesize=AsyncMock(return_value=b"OGG"))
    svc = QBankAudioService(mms_client=fake_mms)
    out = await svc._synthesize_bytes("lakala", "dyu")
    assert out == b"OGG"
    fake_mms.synthesize.assert_awaited_once_with("lakala", "dyu")
