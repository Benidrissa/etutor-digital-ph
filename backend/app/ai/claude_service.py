"""Claude API service for content generation."""

import json
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import structlog

from app.ai.providers import resolve_provider
from app.ai.providers.base import LLMProvider
from app.ai.usage_context import ai_usage_context
from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

# content_type → ledger feature (#2629). Unlisted types pass through verbatim —
# the feature column is a free-form string.
_CONTENT_TYPE_FEATURES = {
    "lesson": "lesson_generation",
    "quiz": "quiz_generation",
    "flashcard": "flashcard_generation",
    "flashcards": "flashcard_generation",
    "case_study": "case_study",
    "case": "case_study",
}


def _feature_for_content_type(content_type: str) -> str:
    return _CONTENT_TYPE_FEATURES.get(content_type, content_type)


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ContentMessage:
    """Minimal provider-neutral stand-in for an Anthropic ``Message``.

    Content-generation callers only read ``.content`` (a list of blocks with
    ``.text``); this lets ``generate_lesson_content`` return the same shape
    whether the active provider is Anthropic or OpenAI-compatible.
    """

    content: list[_TextBlock]
    stop_reason: str
    usage: dict[str, Any]


class ClaudeService:
    """Service for content generation, routed through a pluggable provider.

    The active model is the admin-selected ``ai-model-content`` setting; it is
    resolved to a provider (Anthropic, or an OpenAI-compatible backend such as
    Moonshot Kimi) at call time. The class name is retained for compatibility
    with existing call sites.
    """

    def __init__(self):
        self.settings = get_settings()
        if not self.settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")

        _cache = SettingsCache.instance()
        self._max_tokens = _cache.get("ai-max-tokens-content", 64000)
        self._temperature = _cache.get("ai-temperature-content", 0.7)
        self._model = _cache.get("ai-model-content", "claude-sonnet-4-6")

    def _provider(self) -> LLMProvider:
        """Resolve the provider for the configured content model."""
        return resolve_provider(self._model)

    async def generate_lesson_content_stream(
        self,
        system_prompt: str,
        user_message: str,
    ) -> AsyncGenerator[str, None]:
        """
        Generate lesson content using Claude API with streaming.

        Args:
            system_prompt: System prompt for pedagogical context
            user_message: User message with RAG context and requirements

        Returns:
            AsyncGenerator for streaming text chunks
        """
        try:
            async for chunk in self._provider().stream(
                system=system_prompt,
                user_message=user_message,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                model=self._model,
            ):
                yield chunk

        except Exception as e:
            logger.error("LLM streaming call failed", model=self._model, error=str(e))
            raise

    async def generate_lesson_content(
        self,
        system_prompt: str,
        user_message: str,
        json_object: bool = False,
    ) -> _ContentMessage:
        """
        Generate lesson content (non-streaming) via the active provider.

        Args:
            system_prompt: System prompt for pedagogical context
            user_message: User message with RAG context and requirements
            json_object: Enable JSON mode on OpenAI-compat backends (Moonshot
                Kimi) so they emit syntactically valid JSON instead of
                occasionally dropping a bracket (#2560). Set it when the
                caller parses the response as JSON (lessons, case studies) —
                NOT for plain-text callers (audio scripts). Anthropic ignores
                the flag (prompt-driven JSON).

        Returns:
            A message-like object whose ``.content`` is a single text block
            (provider-neutral; callers accumulate ``block.text``).
        """
        try:
            result = await self._provider().complete(
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                model=self._model,
                json_object=json_object,
            )
            return _ContentMessage(
                content=[_TextBlock(text=result.text)],
                stop_reason=result.stop_reason,
                usage=result.usage,
            )

        except Exception as e:
            logger.error("Claude API call failed", error=str(e))
            raise

    async def generate_structured_content(
        self,
        system_prompt: str,
        user_message: str,
        content_type: str,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        """
        Generate structured content (non-streaming) and parse JSON response.

        On a malformed-JSON parse failure (Claude occasionally drops a delimiter
        or unescapes a quote — see #1822), retries up to ``max_retries`` extra
        times with a sharpened user message asking for strict JSON. Truncation
        (``stop_reason=max_tokens``) is NOT retried; a bigger response would
        only re-truncate.

        Args:
            system_prompt: System prompt with JSON structure requirements
            user_message: User message with context
            content_type: Type of content being generated (lesson, quiz, etc.)
            max_retries: Extra attempts after the first on JSON parse failure.
                Default 1 means up to 2 total Claude calls.

        Returns:
            Parsed JSON content as dictionary, or ``{"raw_response": True, ...}``
            if all attempts failed to parse.
        """
        last_error: str | None = None
        last_preview: str = ""
        last_content_text: str = ""

        for attempt in range(max_retries + 1):
            if attempt == 0:
                effective_user_message = user_message
            else:
                effective_user_message = (
                    "Your previous response was not valid JSON.\n"
                    f"Parse error: {last_error}\n"
                    f"Response preview: {last_preview!r}\n\n"
                    "Respond with STRICT, valid JSON only. No prose, no markdown "
                    "fences, no trailing commas, no unescaped quotes inside strings. "
                    "Match the schema in the original request exactly.\n\n"
                    f"{user_message}"
                )

            try:
                # Ledger fallback: attribute to the content_type when no caller
                # set a more specific feature (#2629).
                with ai_usage_context(_feature_for_content_type(content_type), only_if_unset=True):
                    result = await self._provider().complete(
                        system=system_prompt,
                        messages=[{"role": "user", "content": effective_user_message}],
                        max_tokens=self._max_tokens,
                        temperature=self._temperature,
                        model=self._model,
                        json_object=True,
                    )
            except Exception as e:
                logger.error(
                    "Failed to generate structured content",
                    content_type=content_type,
                    error=str(e),
                )
                raise

            content_text = result.text
            if not content_text:
                raise ValueError("Empty response from LLM provider")

            is_truncated = result.stop_reason == "max_tokens"
            if is_truncated:
                logger.warning(
                    "LLM response truncated at max_tokens",
                    content_type=content_type,
                    usage_output=result.usage.get("output_tokens"),
                )

            last_content_text = content_text

            try:
                parsed_content = self._extract_json(content_text)
            except json.JSONDecodeError as e:
                last_error = str(e)
                last_preview = content_text[:200]

                if is_truncated:
                    logger.error(
                        "Truncated JSON could not be parsed",
                        content_type=content_type,
                        error=last_error,
                    )
                    raise ValueError(
                        f"Response truncated (stop_reason=max_tokens) "
                        f"for {content_type}. JSON is incomplete."
                    )

                if attempt < max_retries:
                    logger.warning(
                        "JSON parse failed, retrying with strict-JSON nudge",
                        content_type=content_type,
                        attempt=attempt + 1,
                        error=last_error,
                        response_preview=last_preview,
                    )
                    continue

                logger.error(
                    "Failed to parse JSON from Claude response",
                    content_type=content_type,
                    error=last_error,
                    response_preview=last_preview,
                    attempts=max_retries + 1,
                )
                return {
                    "content": content_text,
                    "type": content_type,
                    "raw_response": True,
                }

            if is_truncated:
                logger.warning(
                    "JSON parsed but response was truncated — content may be incomplete",
                    content_type=content_type,
                )

            logger.info(
                "Successfully generated structured content",
                content_type=content_type,
                response_length=len(content_text),
                attempt=attempt + 1,
            )
            return parsed_content

        # Defensive: loop always returns or raises above; fall-through fallback.
        return {
            "content": last_content_text,
            "type": content_type,
            "raw_response": True,
        }

    async def generate_structured_content_cached(
        self,
        system_blocks: list[dict[str, Any]],
        user_message: str,
        content_type: str,
        max_retries: int = 1,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Generate structured JSON with cache-aware system blocks.

        Mirrors :meth:`generate_structured_content` but takes
        pre-assembled system *blocks* (each a ``{"type": "text",
        "text": ..., "cache_control": {"type": "ephemeral"}}`` dict)
        instead of a flat string. Anthropic stores each block at the
        cache breakpoint in front of it; subsequent calls with the
        identical block sequence read from cache at ~10% of the
        write-side input cost.

        Used by the course-quality auditor: a 20-unit course pass
        builds the (rubric + syllabus + source summaries + glossary)
        prefix once and reuses it 19 times, dropping prefix input cost
        by ~85%.

        Returns a tuple of ``(parsed_json, usage_dict)`` so the caller
        can persist token + cache statistics into
        ``unit_quality_assessments``.
        """
        last_error: str | None = None
        last_preview: str = ""
        last_content_text: str = ""
        last_usage: dict[str, Any] = {}

        eff_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        eff_temperature = temperature if temperature is not None else self._temperature
        eff_model = model if model is not None else self._model

        for attempt in range(max_retries + 1):
            if attempt == 0:
                effective_user_message = user_message
            else:
                effective_user_message = (
                    "Your previous response was not valid JSON.\n"
                    f"Parse error: {last_error}\n"
                    f"Response preview: {last_preview!r}\n\n"
                    "Respond with STRICT, valid JSON only. No prose, no markdown "
                    "fences, no trailing commas, no unescaped quotes inside strings. "
                    "Match the schema in the original system prompt exactly.\n\n"
                    f"{user_message}"
                )

            try:
                # Provider resolved from eff_model (the auditor may run a
                # different model than the content path). Non-Anthropic providers
                # strip cache_control from the system blocks automatically.
                with ai_usage_context(_feature_for_content_type(content_type), only_if_unset=True):
                    result = await resolve_provider(eff_model).complete(
                        system=system_blocks,
                        messages=[{"role": "user", "content": effective_user_message}],
                        max_tokens=eff_max_tokens,
                        temperature=eff_temperature,
                        model=eff_model,
                        json_object=True,
                    )
            except Exception as e:
                logger.error(
                    "Cached structured call failed",
                    content_type=content_type,
                    error=str(e),
                )
                raise

            last_usage = result.usage

            content_text = result.text
            if not content_text:
                raise ValueError("Empty response from LLM provider")

            is_truncated = result.stop_reason == "max_tokens"
            if is_truncated:
                logger.warning(
                    "Cached response truncated at max_tokens",
                    content_type=content_type,
                    usage=last_usage,
                )
            last_content_text = content_text

            try:
                parsed = self._extract_json(content_text)
            except json.JSONDecodeError as e:
                last_error = str(e)
                last_preview = content_text[:200]
                if is_truncated:
                    raise ValueError(
                        f"Cached response truncated for {content_type}; JSON incomplete."
                    ) from e
                if attempt < max_retries:
                    logger.warning(
                        "JSON parse failed (cached call), retrying with strict-JSON nudge",
                        content_type=content_type,
                        attempt=attempt + 1,
                        error=last_error,
                        response_preview=last_preview,
                    )
                    continue
                logger.error(
                    "Cached structured content parse failed after retries",
                    content_type=content_type,
                    error=last_error,
                    response_preview=last_preview,
                    attempts=max_retries + 1,
                )
                return (
                    {
                        "content": content_text,
                        "type": content_type,
                        "raw_response": True,
                    },
                    last_usage,
                )

            logger.info(
                "Cached structured content generated",
                content_type=content_type,
                response_length=len(content_text),
                attempt=attempt + 1,
                usage=last_usage,
            )
            return parsed, last_usage

        return (
            {
                "content": last_content_text,
                "type": content_type,
                "raw_response": True,
            },
            last_usage,
        )

    @staticmethod
    def _extract_json(content_text: str) -> dict[str, Any]:
        """
        Extract and parse JSON from Claude's response text.

        Strips markdown fences, locates the outermost ``{...}`` or ``[...]``,
        removes trailing commas before ``}`` / ``]``, then ``json.loads``.

        Raises:
            json.JSONDecodeError: If no JSON structure is found, or if the
                located span fails to parse. Both cases use the same exception
                so the caller's retry path covers them uniformly.
        """
        clean_text = content_text.strip()
        if clean_text.startswith("```"):
            first_newline = clean_text.find("\n")
            if first_newline > 0:
                clean_text = clean_text[first_newline + 1 :]
            if clean_text.rstrip().endswith("```"):
                clean_text = clean_text.rstrip()[:-3]

        obj_start = clean_text.find("{")
        arr_start = clean_text.find("[")

        if arr_start >= 0 and (obj_start < 0 or arr_start < obj_start):
            json_start = arr_start
            json_end = clean_text.rfind("]") + 1
        else:
            json_start = obj_start
            json_end = clean_text.rfind("}") + 1

        if json_start < 0 or json_end <= json_start:
            raise json.JSONDecodeError("No JSON structure found in response", clean_text or "", 0)

        json_text = clean_text[json_start:json_end]
        json_text = re.sub(r",\s*([}\]])", r"\1", json_text)
        return json.loads(json_text)
