"""Async HTTP client for the Meta NLLB-200 translation sidecar.

The sidecar (``infrastructure/nllb/``) wraps ``facebook/nllb-200-distilled-600M``
and exposes ``POST /translate`` + ``GET /health``. We use it to translate
French driving-school qbank questions and options into the West African
target languages before the MMS TTS sidecar synthesizes speech (#1690).

MMS is monolingual TTS and doesn't translate; feeding it raw French makes
gibberish. NLLB fills that gap without touching the MMS pipeline.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

# NLLB target codes keyed by the public qbank language code. French is
# the default source and isn't translated back to itself. Fulfulde maps
# to ``fuv_Latn`` (Nigerian) — explicitly listed in the NLLB-200
# language set published with https://ai.meta.com/blog/nllb-200/.
TARGET_CODES: dict[str, str] = {
    "mos": "mos_Latn",
    "dyu": "dyu_Latn",
    "bam": "bam_Latn",
    "ful": "fuv_Latn",
}

# Source language codes: public ISO 639-1 (as stored on QuestionBank.language)
# → NLLB FLORES-200 code. Default source is French because driving-school
# content ships in French, but banks authored in other languages can now
# be translated too (per user request #1690).
SOURCE_CODES: dict[str, str] = {
    "fr": "fra_Latn",
    "en": "eng_Latn",
    "ar": "arb_Arab",
    "pt": "por_Latn",
    "es": "spa_Latn",
}

DEFAULT_SOURCE = "fra_Latn"


def resolve_source_code(bank_language: str | None) -> str:
    """Map ``QuestionBank.language`` (ISO-639-1) to the NLLB FLORES-200 code."""
    if not bank_language:
        return DEFAULT_SOURCE
    return SOURCE_CODES.get(bank_language.lower(), DEFAULT_SOURCE)


class NLLBTranslateError(Exception):
    """Raised when the NLLB sidecar is unreachable or returns an error."""


class NLLBTranslateClient:
    """Thin async wrapper over the NLLB translation sidecar.

    A module-level semaphore keeps concurrent forward passes bounded so
    a batch pregeneration job doesn't overwhelm the single-worker sidecar.
    """

    _semaphore = asyncio.Semaphore(2)

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.nllb_url).rstrip("/")
        self._timeout = timeout_seconds or settings.nllb_timeout_seconds

    @staticmethod
    def supports(language: str) -> bool:
        return language in TARGET_CODES

    async def translate_batch(
        self,
        texts: list[str],
        target: str,
        source: str = DEFAULT_SOURCE,
    ) -> list[str]:
        """Translate a batch of short texts into ``target`` in one forward pass.

        Raises ``NLLBTranslateError`` for transport / sidecar failures so
        the caller can mark translation rows as failed and move on.
        """
        if target not in TARGET_CODES:
            raise NLLBTranslateError(f"NLLB does not support target: {target}")
        if not texts:
            return []
        if any(not t or not t.strip() for t in texts):
            raise NLLBTranslateError("NLLB received empty text in batch")

        tgt_code = TARGET_CODES[target]

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/translate",
                        json={"texts": texts, "src": source, "tgt": tgt_code},
                    )
            except httpx.HTTPError as exc:
                raise NLLBTranslateError(f"NLLB sidecar unreachable: {exc}") from exc

        if resp.status_code != 200:
            raise NLLBTranslateError(f"NLLB sidecar returned {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
        translations = payload.get("translations")
        if not isinstance(translations, list) or len(translations) != len(texts):
            raise NLLBTranslateError("NLLB sidecar returned malformed translations array")

        logger.info(
            "NLLB translate",
            target=target,
            batch_size=len(texts),
            elapsed_ms=payload.get("elapsed_ms"),
        )
        return translations

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
