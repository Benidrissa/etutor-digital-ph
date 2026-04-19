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
    # MMS VITS vocab is lowercase-only, no punctuation. build_audio_script
    # normalizes so the prefix ends up lowercase and the A/B label too.
    q = _FakeQuestion("Question", ["A", "B"])
    for lang, prefix in [
        ("mos", "tʋʋmde"),
        ("dyu", "sugandili"),
        ("bam", "sugandili"),
        ("ful", "suɓaande"),
    ]:
        script = build_audio_script(q, lang)
        assert f"{prefix} a" in script
        assert f"{prefix} b" in script
        # No punctuation the MMS tokenizer cannot encode.
        assert "?" not in script
        assert "." not in script
        assert ":" not in script
        assert "," not in script
        # No uppercase letters either.
        assert script == script.lower()


def test_build_audio_script_mms_strips_punctuation_from_translation():
    """Real-world case: stored dyu translation has `?` and `'` etc."""
    from types import SimpleNamespace

    q = _FakeQuestion("QUE T'INDIQUE CE PANNEAU ?", ["Oui.", "Non."])
    tr = SimpleNamespace(
        question_text="I ka kan k'a kɛ cogo di o koo ɲɔgɔn na?",
        options=["O ye mun lo yira i la?", "A b'a fɔ i ye."],
    )
    script = build_audio_script(q, "dyu", translation=tr)
    # Apostrophe survives (in MMS vocab); question mark stripped to space.
    assert "k'a" in script
    assert "ɲɔgɔn" in script
    assert "?" not in script
    assert script == script.lower()
    # Collapsed spaces — no double spaces.
    assert "  " not in script


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
