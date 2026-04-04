"""Claude API service for content generation."""

import json
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
        self._max_tokens = _cache.get("ai__max_tokens_content", 64000)
        self._temperature = _cache.get("ai__temperature_content", 0.7)

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
    ) -> dict[str, Any]:
        """
        Generate structured content (non-streaming) and parse JSON response.

        Args:
            system_prompt: System prompt with JSON structure requirements
            user_message: User message with context
            content_type: Type of content being generated (lesson, quiz, etc.)

        Returns:
            Parsed JSON content as dictionary
        """
        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                temperature=self._temperature,
            )

            if not response.content or len(response.content) == 0:
                raise ValueError("Empty response from Claude API")

            # Extract text from response
            content_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content_text += block.text

            # Try to parse JSON from the response
            try:
                # Strip markdown code fences if present
                clean_text = content_text.strip()
                if clean_text.startswith("```"):
                    # Remove opening ```json or ```
                    first_newline = clean_text.find("\n")
                    if first_newline > 0:
                        clean_text = clean_text[first_newline + 1 :]
                    # Remove closing ```
                    if clean_text.rstrip().endswith("```"):
                        clean_text = clean_text.rstrip()[:-3]

                # Look for JSON within the response text
                json_start = clean_text.find("{")
                json_end = clean_text.rfind("}") + 1

                if json_start >= 0 and json_end > json_start:
                    json_text = clean_text[json_start:json_end]

                    # Fix common Claude JSON mistakes
                    import re

                    # Remove trailing commas before } or ]
                    json_text = re.sub(r",\s*([}\]])", r"\1", json_text)

                    parsed_content = json.loads(json_text)

                    logger.info(
                        "Successfully generated structured content",
                        content_type=content_type,
                        response_length=len(content_text),
                    )

                    return parsed_content
                else:
                    raise ValueError("No JSON structure found in response")

            except json.JSONDecodeError as e:
                logger.error(
                    "Failed to parse JSON from Claude response",
                    content_type=content_type,
                    error=str(e),
                    response_preview=content_text[:200],
                )
                # Fallback: return raw content wrapped in basic structure
                return {"content": content_text, "type": content_type, "raw_response": True}

        except Exception as e:
            logger.error(
                "Failed to generate structured content", content_type=content_type, error=str(e)
            )
            raise
