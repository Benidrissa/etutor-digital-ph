"""Tests for the admin ``PUT /admin/courses/{course_id}/content/{content_id}`` guard.

``edit_content`` used to assign the posted dict raw and mark the row
``validated`` + ``is_manually_edited`` — which also locks it out of the quality
agent. An edit the read paths cannot parse (``correct_answer: 7``, three
options) then broke every later read with no automatic repair. The handler is
called directly with a mocked session, so no database is needed.
"""

from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.admin_courses import EditContentRequest, edit_content

ADMIN = SimpleNamespace(id=str(uuid.uuid4()), role="admin")

MISCONCEPTIONS = [
    "Thinks cholera is mosquito-borne",
    None,
    "Confuses rash illnesses",
    "Thinks TB is",
]


def _question(qid: str = "q1", **overrides) -> dict:
    question = {
        "id": qid,
        "question": "Which disease is transmitted by the Anopheles mosquito?",
        "options": ["Cholera", "Malaria", "Measles", "Tuberculosis"],
        "correct_answer": 1,
        "option_misconceptions": list(MISCONCEPTIONS),
        "explanation": "Anopheles mosquitoes carry Plasmodium.",
        "sources_cited": ["WHO"],
        "difficulty": "easy",
    }
    question.update(overrides)
    return question


def _quiz(*questions: dict, unit_id: str | None = "1.2") -> dict:
    content = {
        "title": "Vector-borne diseases",
        "description": "",
        "questions": list(questions) or [_question("q1"), _question("q2")],
        "time_limit_minutes": 15,
        "passing_score": 80.0,
    }
    if unit_id is not None:
        content["unit_id"] = unit_id
    return content


LESSON = {
    "introduction": "Intro.",
    "concepts": ["A concept."],
    "aof_example": "An example.",
    "synthesis": "Synthesis.",
    "key_points": ["Point."],
    "sources_cited": ["Book p.1"],
}


def _row(content_type: str, content: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        content_type=content_type,
        content=copy.deepcopy(content),
        is_manually_edited=False,
        validated=False,
    )


def _db(row) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


async def _edit(row, posted: dict):
    db = _db(row)
    response = await edit_content(
        course_id=uuid.uuid4(),
        content_id=row.id,
        request=EditContentRequest(content=posted),
        current_user=ADMIN,
        db=db,
    )
    return response, db


async def _rejected(row, posted: dict) -> dict:
    before = copy.deepcopy(row.content)
    with pytest.raises(HTTPException) as exc_info:
        await _edit(row, posted)
    assert exc_info.value.status_code == 422
    assert row.content == before, "a rejected edit must not touch the row"
    assert row.is_manually_edited is False
    detail = exc_info.value.detail
    assert detail["error"] == "invalid_content"
    return detail


def _codes(detail: dict) -> set[str]:
    return {issue["code"] for issue in detail["issues"]}


class TestQuizEdits:
    async def test_valid_edit_is_saved_and_locked(self):
        row = _row("quiz", _quiz())
        posted = _quiz(_question("q1", question="Which disease do Anopheles mosquitoes spread?"))
        response, db = await _edit(row, posted)
        assert response["is_manually_edited"] is True
        db.commit.assert_awaited_once()
        assert row.is_manually_edited is True and row.validated is True
        assert row.content["questions"][0]["question"].startswith("Which disease do Anopheles")
        assert row.content["unit_id"] == "1.2"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"correct_answer": 7},
            {"options": ["Cholera", "Malaria", "Measles"]},
            {"explanation": None},
        ],
    )
    async def test_schema_violations_are_422(self, overrides):
        detail = await _rejected(_row("quiz", _quiz()), _quiz(_question(**overrides)))
        assert _codes(detail) == {"schema_invalid"}
        assert all(issue["path"].startswith("questions.0") for issue in detail["issues"])

    async def test_duplicate_options_are_422(self):
        posted = _quiz(_question(options=["Malaria", "Malaria.", "Measles", "Tuberculosis"]))
        detail = await _rejected(_row("quiz", _quiz()), posted)
        assert "duplicate_options" in _codes(detail)

    async def test_answer_leak_is_422(self):
        posted = _quiz(_question(question="Malaria — which disease do they spread?"))
        detail = await _rejected(_row("quiz", _quiz()), posted)
        leak = [i for i in detail["issues"] if i["code"] == "answer_leak"]
        assert leak[0]["path"] == "questions[q1].question"
        assert leak[0]["severity"] == "error"

    async def test_distractor_without_misconception_is_422_when_metadata_present(self):
        posted = _quiz(_question(option_misconceptions=["a", None, None, "d"]))
        detail = await _rejected(_row("quiz", _quiz()), posted)
        assert "distractor_without_misconception" in _codes(detail)

    async def test_duplicate_question_ids_are_422(self):
        detail = await _rejected(_row("quiz", _quiz()), _quiz(_question("q1"), _question("q1")))
        assert "duplicate_question_id" in _codes(detail)

    async def test_legacy_quiz_without_misconceptions_is_accepted(self):
        """Missing metadata is a warning (misconceptions_unchecked), not a block."""
        legacy = _question()
        legacy.pop("option_misconceptions")
        row = _row("quiz", _quiz(legacy))
        await _edit(row, _quiz(copy.deepcopy(legacy)))
        assert row.content["questions"][0]["option_misconceptions"] is None

    async def test_short_numeric_options_are_accepted(self):
        numeric = _question(
            question="How many days are in a fortnight?",
            options=["11", "12", "9", "14"],
            correct_answer=3,
            option_misconceptions=["a", "b", "c", None],
        )
        row = _row("quiz", _quiz(numeric))
        await _edit(row, _quiz(numeric))
        assert row.is_manually_edited is True

    async def test_misconceptions_are_normalised(self):
        row = _row("quiz", _quiz())
        await _edit(
            row, _quiz(_question(option_misconceptions=["a", "answer slot", "c", "d", "x"]))
        )
        assert row.content["questions"][0]["option_misconceptions"] == ["a", None, "c", "d"]

    async def test_stored_unit_id_wins(self):
        row = _row("quiz", _quiz(unit_id="summative"))
        posted = _quiz(unit_id="1.9")
        await _edit(row, posted)
        assert row.content["unit_id"] == "summative"

    async def test_metadata_omitted_by_an_editor_is_carried_forward(self):
        row = _row("quiz", _quiz())
        posted_question = _question(question="Which illness do Anopheles mosquitoes spread?")
        posted_question.pop("option_misconceptions")
        await _edit(row, _quiz(posted_question))
        assert row.content["questions"][0]["option_misconceptions"] == MISCONCEPTIONS

    async def test_metadata_is_not_carried_onto_changed_options(self):
        row = _row("quiz", _quiz())
        posted_question = _question(options=["Cholera", "Malaria", "Measles", "Yellow fever"])
        posted_question.pop("option_misconceptions")
        await _edit(row, _quiz(posted_question))
        assert row.content["questions"][0]["option_misconceptions"] is None


class TestOtherContentTypes:
    async def test_valid_lesson_is_saved_as_posted(self):
        row = _row("lesson", {**LESSON, "unit_id": "1.2"})
        posted = {**LESSON, "synthesis": "Better synthesis."}
        await _edit(row, posted)
        assert row.content == {**posted, "unit_id": "1.2"}

    async def test_lesson_missing_a_field_is_422(self):
        posted = {k: v for k, v in LESSON.items() if k != "key_points"}
        detail = await _rejected(_row("lesson", LESSON), posted)
        assert [i["path"] for i in detail["issues"]] == ["key_points"]

    async def test_case_study_needs_two_guided_questions(self):
        case = {
            "aof_context": "Context.",
            "real_data": "Data.",
            "guided_questions": ["Only one?"],
            "annotated_correction": "Answers.",
            "sources_cited": [],
        }
        await _rejected(_row("case", case), case)

    async def test_flashcards_need_a_list(self):
        await _rejected(_row("flashcard", {"flashcards": []}), {"flashcards": "nope"})

    async def test_missing_row_is_404(self):
        with pytest.raises(HTTPException) as exc_info:
            await edit_content(
                course_id=uuid.uuid4(),
                content_id=uuid.uuid4(),
                request=EditContentRequest(content=LESSON),
                current_user=ADMIN,
                db=_db(None),
            )
        assert exc_info.value.status_code == 404
