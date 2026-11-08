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
from app.domain.models.course_quality import GeneratedContentRevision

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


def _row(content_type: str, content: dict, *, revision: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        content_type=content_type,
        content=copy.deepcopy(content),
        sources_cited=[],
        quality_score=None,
        quality_flags=[],
        is_manually_edited=False,
        validated=False,
        content_revision=revision,
    )


def _db(row, *, pre_images: dict | None = None) -> MagicMock:
    """Routes ``execute`` by the entity selected: the row, or a pre-image.

    ``pre_images`` maps a revision to an existing pre-image; pre-images added
    through ``db.add`` become visible to later lookups, as after an autoflush.
    """
    pre_images = dict(pre_images or {})
    db = MagicMock()
    db.statements = []

    async def execute(stmt):
        db.statements.append(stmt)
        result = MagicMock()
        if stmt.column_descriptions[0]["entity"] is GeneratedContentRevision:
            revision = stmt.compile().params["revision_1"]
            result.scalars.return_value.first.return_value = pre_images.get(revision)
        else:
            result.scalar_one_or_none.return_value = row
        return result

    def add(obj):
        if isinstance(obj, GeneratedContentRevision):
            pre_images[obj.revision] = obj

    db.execute = AsyncMock(side_effect=execute)
    db.add = MagicMock(side_effect=add)
    db.commit = AsyncMock()
    return db


async def _edit(row, posted: dict, db=None):
    db = db if db is not None else _db(row)
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


def _added_pre_images(db) -> list:
    return [
        c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], GeneratedContentRevision)
    ]


class TestFrenchNumberTypography:
    async def test_editing_a_french_quiz_with_grouped_digits_is_accepted(self):
        """ "12 500" used to "leak" the answer 500, so fixing a typo in another
        question of a French quiz was refused while the English twin passed."""
        q1 = _question(
            "q1",
            question="Un district compte 12\u202f500 enfants ; 4\u202f% sont malnutris. Combien ?",
            options=["50", "500", "5\u202f000", "125"],
            correct_answer=1,
            option_misconceptions=["Décale la virgule", None, "Prend 40 %", "Divise par 100"],
        )
        row = _row("quiz", _quiz(q1, _question("q2")))
        q2 = _question("q2", question="Quelle maladie le moustique Anopheles transmet-il ?")

        await _edit(row, _quiz(q1, q2))

        assert row.is_manually_edited is True
        assert row.content["questions"][1]["question"].startswith("Quelle maladie")


class TestEitherOrStems:
    async def test_editing_a_quiz_with_an_either_or_question_is_accepted(self):
        """ "aux nourrissons ou aux adultes" names the answer beside a
        distractor: a warning in the audit, never a 422 on an unrelated edit."""
        q1 = _question(
            "q1",
            question="Ce vaccin est-il destiné aux nourrissons ou aux adultes ?",
            options=["nourrissons", "adultes", "personnes âgées", "femmes enceintes"],
            correct_answer=0,
            option_misconceptions=[
                None,
                "Pense que tout vaccin vise les adultes",
                "Confond avec le vaccin antigrippal",
                "Confond avec le vaccin antitétanique",
            ],
        )
        row = _row("quiz", _quiz(q1, _question("q2")))
        q2 = _question("q2", explanation="Les moustiques Anopheles transmettent Plasmodium.")

        response, db = await _edit(row, _quiz(copy.deepcopy(q1), q2))

        assert response["is_manually_edited"] is True
        db.commit.assert_awaited_once()
        assert row.is_manually_edited is True
        assert row.content["questions"][1]["explanation"].startswith("Les moustiques")

    @pytest.mark.parametrize(
        ("stem", "options", "correct"),
        [
            (
                "Le SRO se donne-t-il avant ou après les repas ?",
                ["Avant les repas", "Après les repas", "Pendant la nuit", "Jamais"],
                1,
            ),
            (
                "Should ORS be given before or after meals?",
                ["Before meals", "After meals", "Only at night", "Never"],
                1,
            ),
            (
                "Le vaccin est-il administré par voie orale ou intramusculaire ?",
                [
                    "Par voie orale",
                    "Par voie intramusculaire",
                    "Par voie nasale",
                    "Par voie cutanée",
                ],
                0,
            ),
        ],
        ids=["avant-apres-repas", "before-after-meals", "voie-orale"],
    )
    async def test_editing_a_quiz_with_a_factorised_either_or_question_is_accepted(
        self, stem, options, correct
    ):
        """ "avant ou après les repas" writes "les repas" once for both options:
        the distractor is named by "avant", so a typo fix elsewhere is saved."""
        q1 = _question(
            "q1",
            question=stem,
            options=options,
            correct_answer=correct,
            option_misconceptions=[None if i == correct else f"Idée reçue {i}" for i in range(4)],
        )
        row = _row("quiz", _quiz(q1, _question("q2")))
        q2 = _question("q2", explanation="Typo fixed in the explanation of q2.")

        response, db = await _edit(row, _quiz(copy.deepcopy(q1), q2))

        assert response["is_manually_edited"] is True
        db.commit.assert_awaited_once()
        assert row.content["questions"][1]["explanation"] == "Typo fixed in the explanation of q2."


class TestQuizEditIsANewRevision:
    """Learners may hold the quiz at its current revision when an admin edits
    it: the edit used to rewrite the answer key under that same revision, so
    their answers were graded against the edited questions with no 409."""

    async def test_old_content_is_kept_and_the_revision_bumped(self):
        row = _row("quiz", _quiz(), revision=2)
        served = copy.deepcopy(row.content)
        # The correct option moves from index 1 to index 0.
        posted = _quiz(
            _question(
                "q1",
                options=["Malaria", "Cholera", "Measles", "Tuberculosis"],
                correct_answer=0,
                option_misconceptions=[None, "Thinks cholera is mosquito-borne", "m", "t"],
            ),
            _question("q2"),
        )
        db = _db(row)

        await _edit(row, posted, db)

        (pre_image,) = _added_pre_images(db)
        assert pre_image.revision == 2
        assert pre_image.content == served
        assert pre_image.trigger == "admin_edit"
        assert pre_image.triggered_by_user_id == uuid.UUID(ADMIN.id)
        assert row.content_revision == 3
        assert row.content["questions"][0]["correct_answer"] == 0

        # A learner who was served revision 2 is graded against what they saw.
        from app.api.v1 import quiz as quiz_api

        graded, revision = await quiz_api._content_to_grade(db, row, 2)
        assert revision == 2
        assert graded["questions"][0]["options"][1] == "Malaria"
        assert graded["questions"][0]["correct_answer"] == 1

    async def test_saving_unchanged_content_is_not_a_new_revision(self):
        row = _row("quiz", _quiz(), revision=2)
        posted = _quiz(_question("q1", question="Which disease do Anopheles mosquitoes spread?"))
        db = _db(row)
        await _edit(row, posted, db)
        assert row.content_revision == 3

        await _edit(row, posted, db)

        assert row.content_revision == 3
        assert len(_added_pre_images(db)) == 1

    async def test_the_row_is_re_read_under_a_lock(self):
        row = _row("quiz", _quiz())
        db = _db(row)
        await _edit(row, _quiz(_question("q1", question="Which illness do they spread?")), db)
        stmt = db.statements[0]
        assert stmt._for_update_arg is not None and stmt._for_update_arg.key_share is True
        assert stmt.get_execution_options()["populate_existing"] is True

    async def test_a_conflicting_pre_image_is_409_and_nothing_is_saved(self):
        row = _row("quiz", _quiz(), revision=2)
        before = copy.deepcopy(row.content)
        other = SimpleNamespace(revision=2, content=_quiz(_question("q1", correct_answer=2)))
        db = _db(row, pre_images={2: other})

        with pytest.raises(HTTPException) as exc_info:
            await _edit(row, _quiz(_question("q1", question="Which illness?")), db)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "revision_conflict"
        assert row.content == before and row.content_revision == 2
        db.commit.assert_not_awaited()


class TestOtherContentTypes:
    async def test_valid_lesson_is_saved_as_posted(self):
        row = _row("lesson", {**LESSON, "unit_id": "1.2"})
        posted = {**LESSON, "synthesis": "Better synthesis."}
        _, db = await _edit(row, posted)
        assert row.content == {**posted, "unit_id": "1.2"}
        # Not graded against a revision: no pre-image, no bump.
        assert _added_pre_images(db) == []
        assert row.content_revision == 1

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
