"""Async HTTP client for the shared NLLB-200 translation sidecar (#1694).

The sidecar is a separate Docker service (see infrastructure/nllb) that wraps
facebook/nllb-200-distilled-600M. Called over plain HTTP from the backend and
the Celery worker to translate QBank question text from French to Moore /
Dyula / Bambara before MMS-TTS synthesis.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)


# Map ISO-639-1 (and our internal 3-letter codes for local languages) to
# NLLB flores-200 codes. Driving-school v1 only needs the four below;
# callers can also pass flores codes directly via translate() and we'll
# pass them through unchanged.
ISO_TO_FLORES: dict[str, str] = {
    "fr": "fra_Latn",
    "en": "eng_Latn",
    "mos": "mos_Latn",
    "dyu": "dyu_Latn",
    "bam": "bam_Latn",
}


def to_flores(code: str) -> str:
    """Translate a short ISO code to NLLB flores-200, or pass through if
    it already looks like a flores code (``xxx_Latn`` / ``xxx_Cyrl`` etc)."""
    if "_" in code:
        return code
    try:
        return ISO_TO_FLORES[code]
    except KeyError as exc:
        raise NLLBError(f"unsupported language code: {code}") from exc


class NLLBError(Exception):
    """Raised when the NLLB sidecar returns an error or is unreachable."""


class NLLBClient:
    """Thin async wrapper over the NLLB translation sidecar.

    Shared concurrency bound across all callers in the same process — a
    tenant's bulk translate job can't swamp the single-worker sidecar and
    starve interactive callers. Sized conservatively because each request
    occupies one worker thread on the sidecar for the full generate() call.
    """

    _semaphore = asyncio.Semaphore(2)

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.nllb_url).rstrip("/")
        self._timeout = timeout_seconds or settings.nllb_timeout_seconds

    async def translate(self, text: str, src: str, tgt: str) -> str:
        """Translate one string. ``src``/``tgt`` may be ISO codes or flores-200.

        Raises NLLBError on any transport/sidecar failure. The caller is
        expected to catch and degrade gracefully (e.g. skip translation
        and fall back to source-language TTS, or mark the row ``failed``).
        """
        if not text or not text.strip():
            raise NLLBError("NLLB received empty text")
        src_flores = to_flores(src)
        tgt_flores = to_flores(tgt)
        if src_flores == tgt_flores:
            return text

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/translate",
                        json={
                            "text": text,
                            "src_lang": src_flores,
                            "tgt_lang": tgt_flores,
                        },
                    )
            except httpx.HTTPError as exc:
                raise NLLBError(f"NLLB sidecar unreachable: {exc}") from exc

        if resp.status_code != 200:
            raise NLLBError(f"NLLB sidecar returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        translation = data.get("translation")
        if not translation:
            raise NLLBError("NLLB sidecar returned empty translation")

        logger.info(
            "NLLB translate",
            src=src_flores,
            tgt=tgt_flores,
            chars=len(text),
            elapsed_ms=data.get("elapsed_ms"),
        )
        return translation

    async def translate_batch(self, texts: list[str], src: str, tgt: str) -> list[str]:
        """Translate multiple strings in one call — preferred for bulk jobs
        since the sidecar does NLLB tokenization + beam search once.
        """
        if not texts:
            return []
        src_flores = to_flores(src)
        tgt_flores = to_flores(tgt)
        if src_flores == tgt_flores:
            return list(texts)
        # Filter empty inputs so the sidecar validator doesn't reject the
        # whole batch if one option is blank.
        indexed = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
        if not indexed:
            return list(texts)

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/translate/batch",
                        json={
                            "texts": [t for _, t in indexed],
                            "src_lang": src_flores,
                            "tgt_lang": tgt_flores,
                        },
                    )
            except httpx.HTTPError as exc:
                raise NLLBError(f"NLLB sidecar unreachable: {exc}") from exc

        if resp.status_code != 200:
            raise NLLBError(f"NLLB sidecar returned {resp.status_code}: {resp.text[:200]}")
        translations = resp.json().get("translations", [])
        if len(translations) != len(indexed):
            raise NLLBError(
                f"NLLB batch returned {len(translations)} items for {len(indexed)} inputs"
            )

        out = list(texts)
        for (i, _), translated in zip(indexed, translations, strict=True):
            out[i] = translated
        return out

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
