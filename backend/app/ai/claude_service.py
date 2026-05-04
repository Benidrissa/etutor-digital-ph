"""Claude API service for content generation."""

import json
import re
from collections.abc import AsyncGenerator
from typing import Any

import anthropic
import structlog
from anthropic.types import Message

from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()


class ClaudeService:
    """Service for interacting with Claude API for content generation."""

    def __init__(self):
        self.settings = get_settings()
        if not self.settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")

        self.client = anthropic.AsyncAnthropic(
            api_key=self.settings.anthropic_api_key,
            timeout=600.0,
        )

        _cache = SettingsCache.instance()
        self._max_tokens = _cache.get("ai-max-tokens-content", 64000)
        self._temperature = _cache.get("ai-temperature-content", 0.7)

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
            async with self.client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                temperature=self._temperature,
            ) as stream_manager:
                async for event in stream_manager:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield event.delta.text

        except Exception as e:
            logger.error("Claude API streaming call failed", error=str(e))
            raise

    async def generate_lesson_content(
        self,
        system_prompt: str,
        user_message: str,
    ) -> Message:
        """
        Generate lesson content using Claude API without streaming.

        Args:
            system_prompt: System prompt for pedagogical context
            user_message: User message with RAG context and requirements

        Returns:
            Message object from Claude API
        """
        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                temperature=self._temperature,
            )
            return response

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
                response = await self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=self._max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": effective_user_message}],
                    temperature=self._temperature,
                )
            except Exception as e:
                logger.error(
                    "Failed to generate structured content",
                    content_type=content_type,
                    error=str(e),
                )
                raise

            if not response.content or len(response.content) == 0:
                raise ValueError("Empty response from Claude API")

            is_truncated = response.stop_reason == "max_tokens"
            if is_truncated:
                logger.warning(
                    "Claude response truncated at max_tokens",
                    content_type=content_type,
                    usage_output=getattr(response.usage, "output_tokens", None),
                )

            content_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content_text += block.text

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
                response = await self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=eff_max_tokens,
                    system=system_blocks,
                    messages=[{"role": "user", "content": effective_user_message}],
                    temperature=eff_temperature,
                )
            except Exception as e:
                logger.error(
                    "Claude cached call failed",
                    content_type=content_type,
                    error=str(e),
                )
                raise

            usage = getattr(response, "usage", None)
            last_usage = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_creation_input_tokens": getattr(
                    usage, "cache_creation_input_tokens", None
                ),
                "cache_read_input_tokens": getattr(
                    usage, "cache_read_input_tokens", None
                ),
            }

            if not response.content or len(response.content) == 0:
                raise ValueError("Empty response from Claude API")

            is_truncated = response.stop_reason == "max_tokens"
            if is_truncated:
                logger.warning(
                    "Claude cached response truncated at max_tokens",
                    content_type=content_type,
                    usage=last_usage,
                )

            content_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content_text += block.text
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
