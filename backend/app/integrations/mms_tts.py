"""Async HTTP client for the Meta MMS TTS sidecar service.

The sidecar is a separate Docker service (see infrastructure/mms-tts) that
wraps facebook/mms-tts-{mos,dyu,bam} models and returns OGG/Opus audio. We
call it over plain HTTP from the backend and the Celery worker.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

SUPPORTED_LANGUAGES = {"mos", "dyu", "bam"}


class MMSTTSError(Exception):
    """Raised when the MMS sidecar returns an error or is unreachable."""


class MMSTTSClient:
    """Thin async wrapper over the MMS TTS sidecar.

    A module-level semaphore keeps concurrent CPU-bound synthesis calls
    bounded so a batch job can't overwhelm the single-worker sidecar.
    """

    _semaphore = asyncio.Semaphore(2)

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.mms_tts_url).rstrip("/")
        self._timeout = timeout_seconds or settings.mms_tts_timeout_seconds

    @staticmethod
    def supports(language: str) -> bool:
        return language in SUPPORTED_LANGUAGES

    async def synthesize(self, text: str, language: str) -> bytes:
        """Return OGG/Opus audio bytes for ``text`` in the given language.

        Raises MMSTTSError for any transport or sidecar-side failure; the
        caller is expected to mark the audio row ``failed`` and surface the
        error in logs rather than crashing the whole batch.
        """
        if language not in SUPPORTED_LANGUAGES:
            raise MMSTTSError(f"MMS TTS does not support language: {language}")
        if not text or not text.strip():
            raise MMSTTSError("MMS TTS received empty text")

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/synthesize",
                        json={"text": text, "language": language},
                    )
            except httpx.HTTPError as exc:
                raise MMSTTSError(f"MMS sidecar unreachable: {exc}") from exc

        if resp.status_code != 200:
            raise MMSTTSError(f"MMS sidecar returned {resp.status_code}: {resp.text[:200]}")
        audio = resp.content
        if not audio:
            raise MMSTTSError("MMS sidecar returned empty body")

        logger.info(
            "MMS TTS synthesis",
            language=language,
            text_chars=len(text),
            audio_bytes=len(audio),
        )
        return audio

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
