"""Tests for ClaudeService truncation detection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_response(text: str, stop_reason: str = "end_turn"):
    """Build a mock Claude API response."""
    block = MagicMock()
    block.text = text
    block.type = "text"

    usage = MagicMock()
    usage.output_tokens = 100

    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    response.usage = usage
    return response


@pytest.fixture
def claude_service():
    with patch("app.ai.claude_service.get_settings") as mock_settings:
        settings = MagicMock()
        settings.anthropic_api_key = "test-key"
        mock_settings.return_value = settings

        with patch("app.ai.claude_service.SettingsCache") as mock_cache:
            cache_inst = MagicMock()
            cache_inst.get.return_value = 64000
            mock_cache.instance.return_value = cache_inst

            with patch("app.ai.claude_service.anthropic"):
                from app.ai.claude_service import ClaudeService

                service = ClaudeService()
                service.client = AsyncMock()
                return service


@pytest.mark.asyncio
async def test_normal_response_parses_correctly(claude_service):
    """stop_reason=end_turn + valid JSON -> returns parsed, no error."""
    valid_json = '{"title": "Quiz", "questions": []}'
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(valid_json, "end_turn")
    )

    result = await claude_service.generate_structured_content("system", "user", "quiz")

    assert result == {"title": "Quiz", "questions": []}


@pytest.mark.asyncio
async def test_malformed_json_returns_raw_response(claude_service):
    """stop_reason=end_turn + bad JSON -> raw_response fallback."""
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response('{"title": broken json here}', "end_turn")
    )

    result = await claude_service.generate_structured_content("system", "user", "quiz")

    assert result["raw_response"] is True
    assert result["type"] == "quiz"


@pytest.mark.asyncio
async def test_truncated_unparseable_raises_valueerror(claude_service):
    """stop_reason=max_tokens + bad JSON -> ValueError, not raw_response."""
    truncated = '{"title": "Quiz", "questions": [{"id": "q1"'
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(truncated, "max_tokens")
    )

    with pytest.raises(ValueError, match="truncated"):
        await claude_service.generate_structured_content("system", "user", "quiz")


@pytest.mark.asyncio
async def test_truncated_parseable_returns_data_with_warning(claude_service):
    """stop_reason=max_tokens + valid JSON -> returns parsed, logs warning."""
    valid_json = '{"title": "Quiz", "questions": []}'
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(valid_json, "max_tokens")
    )

    result = await claude_service.generate_structured_content("system", "user", "quiz")

    # Should still return the parsed data
    assert result == {"title": "Quiz", "questions": []}


@pytest.mark.asyncio
async def test_json_in_markdown_fences_parsed(claude_service):
    """JSON wrapped in markdown code fences is extracted correctly."""
    fenced = '```json\n{"title": "Quiz", "questions": []}\n```'
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(fenced, "end_turn")
    )

    result = await claude_service.generate_structured_content("system", "user", "quiz")

    assert result == {"title": "Quiz", "questions": []}


@pytest.mark.asyncio
async def test_trailing_comma_fixed(claude_service):
    """Trailing commas before } or ] are cleaned up."""
    bad_json = '{"title": "Quiz", "questions": [],}'
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(bad_json, "end_turn")
    )

    result = await claude_service.generate_structured_content("system", "user", "quiz")

    assert result == {"title": "Quiz", "questions": []}


@pytest.mark.asyncio
async def test_malformed_then_valid_json_retry_succeeds(claude_service):
    """Malformed JSON on first call, valid on retry — caller sees the retry result.

    Covers #1822: Claude occasionally drops a delimiter or unescapes a
    quote; one retry with a strict-JSON nudge fixes it most of the time.
    """
    malformed = '{"title": broken json here}'
    valid = '{"title": "Quiz", "questions": []}'
    claude_service.client.messages.create = AsyncMock(
        side_effect=[
            _make_response(malformed, "end_turn"),
            _make_response(valid, "end_turn"),
        ]
    )

    result = await claude_service.generate_structured_content("system", "user", "quiz")

    assert result == {"title": "Quiz", "questions": []}
    assert claude_service.client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_max_retries_zero_skips_retry(claude_service):
    """max_retries=0 preserves the pre-#1822 single-attempt behavior."""
    malformed = '{"title": broken json here}'
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(malformed, "end_turn")
    )

    result = await claude_service.generate_structured_content(
        "system", "user", "quiz", max_retries=0
    )

    assert result["raw_response"] is True
    assert claude_service.client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_truncated_response_does_not_retry(claude_service):
    """stop_reason=max_tokens skips retry; bigger output would re-truncate."""
    truncated = '{"title": "Quiz", "questions": [{"id": "q1"'
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(truncated, "max_tokens")
    )

    with pytest.raises(ValueError, match="truncated"):
        await claude_service.generate_structured_content("system", "user", "quiz")

    assert claude_service.client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_no_json_found_retried_then_falls_back(claude_service):
    """Plain-prose response with no JSON structure also goes through the retry path."""
    prose = "I'm sorry, I can't help with that right now."
    claude_service.client.messages.create = AsyncMock(
        return_value=_make_response(prose, "end_turn")
    )

    result = await claude_service.generate_structured_content("system", "user", "quiz")

    assert result["raw_response"] is True
    assert result["type"] == "quiz"
    assert claude_service.client.messages.create.await_count == 2
