"""Unit tests for the NLLB client (#1694).

Stubs httpx so we don't spin the 2.4 GB model locally — these pin down
the protocol shape (flores-200 code mapping, empty-text guard, batch
reconstruction with gapped empty inputs, error conversion).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.integrations.nllb import NLLBClient, NLLBError, to_flores


def test_to_flores_maps_iso_codes():
    assert to_flores("fr") == "fra_Latn"
    assert to_flores("en") == "eng_Latn"
    assert to_flores("mos") == "mos_Latn"
    assert to_flores("dyu") == "dyu_Latn"
    assert to_flores("bam") == "bam_Latn"


def test_to_flores_passes_through_flores_codes():
    assert to_flores("fra_Latn") == "fra_Latn"
    assert to_flores("swh_Latn") == "swh_Latn"


def test_to_flores_raises_on_unknown_iso():
    with pytest.raises(NLLBError):
        to_flores("xx")


@pytest.mark.asyncio
async def test_translate_same_language_is_passthrough():
    """Translating fr -> fr must not call the sidecar."""
    client = NLLBClient(base_url="http://nllb:8000")
    with patch("httpx.AsyncClient") as ac:
        out = await client.translate("Bonjour", "fr", "fra_Latn")
    assert out == "Bonjour"
    ac.assert_not_called()


@pytest.mark.asyncio
async def test_translate_rejects_empty_text():
    client = NLLBClient(base_url="http://nllb:8000")
    with pytest.raises(NLLBError):
        await client.translate("", "fr", "mos")
    with pytest.raises(NLLBError):
        await client.translate("   ", "fr", "mos")


@pytest.mark.asyncio
async def test_translate_posts_flores_codes_and_parses_response():
    """End-to-end shape: ISO in, flores on the wire, translation out."""
    resp = httpx.Response(
        200,
        json={
            "translation": "Ne y yiibu?",
            "src_lang": "fra_Latn",
            "tgt_lang": "mos_Latn",
            "elapsed_ms": 42,
        },
    )
    mock_post = AsyncMock(return_value=resp)
    with patch("httpx.AsyncClient") as ac:
        ac.return_value.__aenter__.return_value.post = mock_post
        client = NLLBClient(base_url="http://nllb:8000")
        out = await client.translate("Comment allez-vous ?", "fr", "mos")

    assert out == "Ne y yiibu?"
    mock_post.assert_awaited_once()
    url, kwargs = mock_post.await_args.args, mock_post.await_args.kwargs
    assert url[0] == "http://nllb:8000/translate"
    assert kwargs["json"] == {
        "text": "Comment allez-vous ?",
        "src_lang": "fra_Latn",
        "tgt_lang": "mos_Latn",
    }


@pytest.mark.asyncio
async def test_translate_batch_preserves_empty_gaps():
    """Empty options must stay empty in the output rather than
    misaligning the translated list (regression guard)."""
    # Empty strings get filtered on send, so the sidecar only sees the
    # two non-empty inputs and returns two translations.
    resp = httpx.Response(
        200,
        json={
            "translations": ["T_question", "T_opt2"],
            "src_lang": "fra_Latn",
            "tgt_lang": "mos_Latn",
            "elapsed_ms": 5,
        },
    )
    mock_post = AsyncMock(return_value=resp)
    with patch("httpx.AsyncClient") as ac:
        ac.return_value.__aenter__.return_value.post = mock_post
        client = NLLBClient(base_url="http://nllb:8000")
        # Index 1 is an empty option — must be filtered on send and
        # restored as "" in the output so option letter mapping holds.
        out = await client.translate_batch(["question text", "", "opt2"], "fr", "mos")
        # Confirm the wire request excluded the empty string.
        _, kwargs = mock_post.await_args.args, mock_post.await_args.kwargs
        assert kwargs["json"]["texts"] == ["question text", "opt2"]
    assert out == ["T_question", "", "T_opt2"]


@pytest.mark.asyncio
async def test_translate_error_becomes_nllberror():
    """Sidecar 503 must surface as NLLBError so callers can degrade."""
    resp = httpx.Response(503, text="model loading")
    mock_post = AsyncMock(return_value=resp)
    with patch("httpx.AsyncClient") as ac:
        ac.return_value.__aenter__.return_value.post = mock_post
        client = NLLBClient(base_url="http://nllb:8000")
        with pytest.raises(NLLBError) as exc:
            await client.translate("salut", "fr", "mos")
    assert "503" in str(exc.value)
