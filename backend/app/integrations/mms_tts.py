"""Meta MMS TTS HTTP client for Moore (mos) and Dioula (dyu) synthesis."""

from __future__ import annotations

import structlog

from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

MMS_LANGUAGE_CODES: dict[str, str] = {
    "mos": "mos",
    "dyu": "dyu",
}

_SUPPORTED_LANGUAGES = frozenset(MMS_LANGUAGE_CODES)


class MMSTTSClient:
    """Async HTTP client for the Meta MMS TTS Docker sidecar.

    The sidecar exposes a single POST endpoint:
        POST /synthesize
        Body: {"text": "<text>", "language": "<mos|dyu>"}
        Response: WAV audio bytes (Content-Type: audio/wav)

    Configured via MMS_SIDECAR_URL env variable.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.mms_sidecar_url).rstrip("/")

    async def synthesize(self, text: str, language: str) -> bytes:
        """Synthesize speech for the given text using Meta MMS.

        Args:
            text: Plain text to synthesize (no markdown).
            language: Language code — "mos" (Moore) or "dyu" (Dioula).

        Returns:
            WAV audio bytes.

        Raises:
            ValueError: If language is not supported.
            RuntimeError: If the MMS sidecar returns a non-2xx response.
        """
        if language not in _SUPPORTED_LANGUAGES:
            raise ValueError(
                f"MMS TTS: unsupported language '{language}'. "
                f"Supported: {sorted(_SUPPORTED_LANGUAGES)}"
            )

        import httpx

        url = f"{self._base_url}/synthesize"
        payload = {"text": text, "language": language}

        logger.info(
            "MMS TTS: synthesizing",
            language=language,
            text_length=len(text),
            url=url,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)

        if response.status_code != 200:
            error_body = response.text[:500]
            logger.error(
                "MMS TTS: sidecar error",
                status_code=response.status_code,
                body=error_body,
                language=language,
            )
            raise RuntimeError(f"MMS TTS sidecar returned {response.status_code}: {error_body}")

        audio_bytes = response.content
        if not audio_bytes:
            raise RuntimeError("MMS TTS sidecar returned empty audio bytes")

        logger.info(
            "MMS TTS: synthesis complete",
            language=language,
            audio_size_bytes=len(audio_bytes),
        )
        return audio_bytes
