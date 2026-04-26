"""Tests for the get_unit_content tool (#1992).

The tool serves the FULL generated body of a lesson/quiz/case study on
demand — companion to the structured listing in the system prompt
(titles + descriptions only). Lets the tutor stay focused on the course
without inlining all bodies into every prompt.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.tutor_tools import TutorToolExecutor


def _row(content_type: str, language: str, content: dict) -> SimpleNamespace:
    return SimpleNamespace(content_type=content_type, language=language, content=content)


def _executor(
    *,
    user_language: str = "fr",
    current_module_id: uuid.UUID | None = None,
) -> TutorToolExecutor:
    return TutorToolExecutor(
        retriever=MagicMock(),
        anthropic_client=MagicMock(),
        user_id=uuid.uuid4(),
        user_level=2,
        user_language=user_language,
        current_module_id=current_module_id,
    )


def _session_with_rows(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


# --- happy path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_full_lesson_body_when_unit_is_generated():
    module_id = uuid.uuid4()
    lesson_body = {
        "unit_id": "1.1",
        "introduction": "Intro paragraph",
        "concepts": ["c1", "c2"],
        "aof_example": "AOF example",
    }
    session = _session_with_rows([_row("lesson", "fr", lesson_body)])
    executor = _executor(current_module_id=module_id)

    result_str = await executor.execute("get_unit_content", {"unit_number": "1.1"}, session)
    result = json.loads(result_str)
    assert result["content_type"] == "lesson"
    assert result["unit_number"] == "1.1"
    assert result["content"]["introduction"] == "Intro paragraph"
    assert result["content"]["concepts"] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_returns_quiz_body_when_content_type_is_quiz():
    module_id = uuid.uuid4()
    quiz_body = {
        "unit_id": "1.2",
        "questions": [{"question": "Q?", "options": ["A", "B"], "correct_answer": 0}],
    }
    session = _session_with_rows([_row("quiz", "fr", quiz_body)])
    executor = _executor(current_module_id=module_id)

    result = json.loads(
        await executor.execute(
            "get_unit_content", {"unit_number": "1.2", "content_type": "quiz"}, session
        )
    )
    assert result["content_type"] == "quiz"
    assert result["content"]["questions"][0]["question"] == "Q?"


@pytest.mark.asyncio
async def test_default_content_type_is_lesson():
    module_id = uuid.uuid4()
    session = _session_with_rows([_row("lesson", "fr", {"unit_id": "1.1", "introduction": "Hi"})])
    executor = _executor(current_module_id=module_id)
    result = json.loads(await executor.execute("get_unit_content", {"unit_number": "1.1"}, session))
    assert result["content_type"] == "lesson"


# --- missing-content path ---------------------------------------------------


@pytest.mark.asyncio
async def test_returns_not_generated_when_unit_is_missing():
    """When the requested unit hasn't been generated, return error +
    available_units so the tutor can suggest a real alternative instead
    of inventing content."""
    module_id = uuid.uuid4()
    session = _session_with_rows(
        [
            _row("lesson", "fr", {"unit_id": "1.1", "introduction": "..."}),
            _row("lesson", "fr", {"unit_id": "1.2", "introduction": "..."}),
        ]
    )
    executor = _executor(current_module_id=module_id)
    result = json.loads(await executor.execute("get_unit_content", {"unit_number": "1.5"}, session))
    assert result["error"] == "not_generated"
    assert set(result["available_units"]) == {"1.1", "1.2"}
    assert result["unit_number"] == "1.5"


@pytest.mark.asyncio
async def test_returns_not_generated_when_module_has_no_content_at_all():
    module_id = uuid.uuid4()
    session = _session_with_rows([])  # no GeneratedContent rows
    executor = _executor(current_module_id=module_id)
    result = json.loads(await executor.execute("get_unit_content", {"unit_number": "1.1"}, session))
    assert result["error"] == "not_generated"
    assert result["available_units"] == []


# --- module-id resolution ----------------------------------------------------


@pytest.mark.asyncio
async def test_uses_current_module_id_when_input_omits_module_id():
    """The executor's ``current_module_id`` (set by send_message from the
    conversation context) is the default — Claude doesn't need to pass it."""
    module_id = uuid.uuid4()
    session = _session_with_rows([_row("lesson", "fr", {"unit_id": "0", "introduction": "Hi"})])
    executor = _executor(current_module_id=module_id)

    await executor.execute("get_unit_content", {"unit_number": "0"}, session)

    # The executed select must filter by the current_module_id we set.
    stmt = session.execute.await_args[0][0]
    sql = str(stmt).lower()
    assert "module_id" in sql


@pytest.mark.asyncio
async def test_explicit_module_id_overrides_current_module_id():
    """When Claude passes module_id explicitly (e.g. discussing a different
    module), that wins over the executor's default."""
    other_module_id = uuid.uuid4()
    session = _session_with_rows([_row("lesson", "fr", {"unit_id": "1.1", "introduction": "Hi"})])
    executor = _executor(current_module_id=uuid.uuid4())

    result = json.loads(
        await executor.execute(
            "get_unit_content",
            {"unit_number": "1.1", "module_id": str(other_module_id)},
            session,
        )
    )
    assert result["content_type"] == "lesson"
    # Sanity: the executed query is still well-formed (we accepted the override).
    stmt = session.execute.await_args[0][0]
    assert "module_id" in str(stmt).lower()


@pytest.mark.asyncio
async def test_returns_error_when_no_module_id_at_all():
    """No current module + no explicit input → tutor gets a clear error
    rather than a 500 or silent empty result."""
    executor = _executor(current_module_id=None)
    session = _session_with_rows([])
    result = json.loads(await executor.execute("get_unit_content", {"unit_number": "1.1"}, session))
    assert "error" in result
    assert "module" in result["error"].lower()


# --- input validation -------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_unit_number_returns_error():
    executor = _executor(current_module_id=uuid.uuid4())
    result = json.loads(await executor.execute("get_unit_content", {}, _session_with_rows([])))
    assert "error" in result
    assert "unit_number" in result["error"]


@pytest.mark.asyncio
async def test_invalid_content_type_returns_error():
    executor = _executor(current_module_id=uuid.uuid4())
    result = json.loads(
        await executor.execute(
            "get_unit_content",
            {"unit_number": "1.1", "content_type": "flashcard"},
            _session_with_rows([]),
        )
    )
    assert "error" in result
    assert "content_type" in result["error"]


@pytest.mark.asyncio
async def test_invalid_module_id_returns_error_not_500():
    executor = _executor(current_module_id=None)
    result = json.loads(
        await executor.execute(
            "get_unit_content",
            {"unit_number": "1.1", "module_id": "not-a-uuid"},
            _session_with_rows([]),
        )
    )
    assert "error" in result
    assert "module_id" in result["error"]


# --- language scoping -------------------------------------------------------


@pytest.mark.asyncio
async def test_query_filters_by_user_language():
    """FR users get FR rows; EN users get EN rows. The query must include
    the language filter so we don't bleed cross-locale content."""
    executor = _executor(user_language="en", current_module_id=uuid.uuid4())
    session = _session_with_rows([])
    await executor.execute("get_unit_content", {"unit_number": "1.1"}, session)
    stmt = session.execute.await_args[0][0]
    assert "language" in str(stmt).lower()


# --- tool registration -----------------------------------------------------


def test_tool_is_registered_in_TOOL_DEFINITIONS():
    from app.domain.services.tutor_tools import TOOL_DEFINITIONS

    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "get_unit_content" in names
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_unit_content")
    assert "unit_number" in tool["input_schema"]["properties"]
    assert "content_type" in tool["input_schema"]["properties"]
    assert "module_id" in tool["input_schema"]["properties"]
    assert tool["input_schema"]["required"] == ["unit_number"]
