"""Tests for _parse_lesson_content JSON repair (#2560).

Kimi (Moonshot, OpenAI-compat provider) non-deterministically emits
structurally invalid lesson JSON — e.g. omitting the `]` that closes the
"concepts" array right before the next top-level key. The parser must repair
what it can and refuse to cache what it can't, instead of silently wrapping
the raw blob as a single "concept".
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.services.lesson_service import LessonGenerationService


@pytest.fixture
def lesson_service():
    return LessonGenerationService(
        claude_service=AsyncMock(spec=ClaudeService),
        semantic_retriever=AsyncMock(spec=SemanticRetriever),
    )


VALID_LESSON = {
    "introduction": "Une introduction.",
    "concepts": ["Concept A", "Concept B"],
    "aof_example": "Un exemple au Burkina Faso.",
    "synthesis": "Une synthèse.",
    "key_points": ["Point 1", "Point 2"],
    "sources_cited": ["Livre, p.6"],
    "__complete": True,
}


def _assert_structured(content, *, expect_synthesis=True):
    assert content.introduction == "Une introduction."
    assert content.concepts == ["Concept A", "Concept B"]
    assert content.aof_example == "Un exemple au Burkina Faso."
    if expect_synthesis:
        assert content.synthesis == "Une synthèse."
    assert content.key_points == ["Point 1", "Point 2"]
    assert "Livre, p.6" in content.sources_cited


@pytest.mark.asyncio
async def test_valid_json_parses(lesson_service):
    content = await lesson_service._parse_lesson_content(json.dumps(VALID_LESSON), [])
    _assert_structured(content)


@pytest.mark.asyncio
async def test_double_encoded_json_unwrapped(lesson_service):
    """The whole lesson object serialized as a JSON string literal."""
    content = await lesson_service._parse_lesson_content(json.dumps(json.dumps(VALID_LESSON)), [])
    _assert_structured(content)


@pytest.mark.asyncio
async def test_missing_bracket_before_top_level_key_repaired_lossless(lesson_service):
    """The exact staging defect (module 4b1f45ad unit 1.3): the `]` closing
    "concepts" is omitted right before `"aof_example"`. A single bracket
    insertion restores the payload with no loss."""
    text = json.dumps(VALID_LESSON)
    broken = text.replace('], "aof_example"', ', "aof_example"')
    assert broken != text
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)

    content = await lesson_service._parse_lesson_content(broken, [])
    _assert_structured(content)


@pytest.mark.asyncio
async def test_json_repair_hoists_stray_dict_from_concepts(lesson_service):
    """When only generic json_repair applies, fields swallowed into a stray
    dict inside "concepts" are hoisted back to the top level."""
    broken = (
        '{"introduction": "Une introduction.", '
        '"concepts": ["Concept A", "Concept B", '
        '{"aof_example": "Un exemple au Burkina Faso.", '
        '"key_points": ["Point 1", "Point 2"], '
        '"sources_cited": ["Livre, p.6"]}]'
    )  # note: never closed — unparseable without repair
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)

    content = await lesson_service._parse_lesson_content(broken, [])
    _assert_structured(content, expect_synthesis=False)


@pytest.mark.asyncio
async def test_unrecoverable_json_raises_instead_of_caching(lesson_service):
    """JSON-looking text that repairs into a non-lesson object must raise, not
    be cached as a raw single-concept blob."""
    with pytest.raises(ValueError, match="malformed JSON"):
        await lesson_service._parse_lesson_content('{"foo": "bar", "baz": [1, 2', [])


@pytest.mark.asyncio
async def test_markdown_falls_back_to_single_concept(lesson_service):
    """Genuinely non-JSON text (legacy cached markdown) keeps the old fallback."""
    text = "# Ma leçon\n\nDu contenu markdown."
    content = await lesson_service._parse_lesson_content(text, [])
    assert content.concepts == [text]
    assert content.introduction == ""


@pytest.mark.asyncio
async def test_code_fenced_json_still_parses(lesson_service):
    fenced = "```json\n" + json.dumps(VALID_LESSON) + "\n```"
    content = await lesson_service._parse_lesson_content(fenced, [])
    _assert_structured(content)
