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
    SUPPORTED_LANGUAGES,
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
    for lang, prefix in [
        ("mos", "Tʋʋmde"),
        ("dyu", "Sugandili"),
        ("bam", "Sugandili"),
        ("ful", "Suɓaande"),
    ]:
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


def test_supported_languages_is_non_empty_tuple():
    # Pregeneration loops over this tuple, so it must stay iterable and
    # contain at least French (the baseline).
    assert isinstance(SUPPORTED_LANGUAGES, tuple)
    assert "fr" in SUPPORTED_LANGUAGES
    assert all(isinstance(lang, str) for lang in SUPPORTED_LANGUAGES)


class _FakeTranslation:
    def __init__(self, text: str, options: list[str]):
        self.question_text = text
        self.options = options


def test_build_audio_script_uses_translation_when_provided():
    """With a translation row, question_text and options come from the
    translated content — the option PREFIX still stays in the speaker's
    language so "Tʋʋmde A: ..." reads as a Moore sentence (#1694)."""
    q = _FakeQuestion(
        "Que signifie ce panneau ?",
        ["Stop", "Céder le passage", "Danger"],
    )
    translation = _FakeTranslation(
        "Tagem sɛbga bʋko la bʋgo?",
        ["Zĩigi", "Kõ sori", "Yɛlga"],
    )
    script = build_audio_script(q, "mos", translation=translation)
    # French source must NOT appear — the whole point of translation is
    # that MMS-TTS pronounces Moore words, not French transliterations.
    assert "Que signifie" not in script
    assert "Stop" not in script
    assert "Céder" not in script
    # Translated content must appear, with Moore prefix.
    assert script.startswith("Tagem sɛbga")
    assert "Tʋʋmde A: Zĩigi" in script
    assert "Tʋʋmde B: Kõ sori" in script
    assert "Tʋʋmde C: Yɛlga" in script


def test_build_audio_script_falls_back_to_source_when_translation_none():
    """When NLLB is unreachable the translation is None — we must still
    produce a playable script in the source language rather than crash."""
    q = _FakeQuestion("Question source", ["A", "B"])
    script = build_audio_script(q, "mos", translation=None)
    assert script.startswith("Question source")
    assert "Tʋʋmde A: A" in script
