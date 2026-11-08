"""The lesson → story pipeline, end to end, with a fake model and no database.

The load-bearing test is the first one: a realistic lesson (introduction,
concepts, field example, synthesis, key points, sources) and its 4-option
quiz, run through the whole pipeline with a model response, must give a week
the Appendix C validator passes with zero errors AND zero warnings — for an
English and a French target language alike.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.ai.prompts.story_from_lesson import (
    STORY_KIDS_SYSTEM_KEY,
    STORY_SYSTEM_KEY,
    build_story_user_message,
    get_story_system_prompt,
    plan_for,
)
from app.api.v1.schemas.story_course import StoryCourse, ValidationIssue
from app.domain.models.story_course import StoryCourseRecord
from app.domain.services import story_from_lesson_service as service_module
from app.domain.services import story_repair as repair
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import (
    NotALessonUnit,
    StoryBinding,
    StoryFromLessonService,
    content_digest,
    covering_quiz_unit,
    story_sources_are_fresh,
    upsert_story_course,
    validate_document,
)

FIXTURE = Path(__file__).parent / "fixtures" / "lesson_story_unit.json"
UNIT_ID = uuid.UUID("2f1e0d3c-4b5a-4968-8776-655443322110")
MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")
QUIZ_UNIT_ID = uuid.UUID("3a2b1c0d-5e4f-4a7b-8c9d-0e1f2a3b4c5d")


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_ctx(raw: dict[str, Any], language: str, **overrides: Any) -> repair.LessonStoryContext:
    data = raw[language]
    mcqs, _ = repair.parse_quiz_mcqs(copy.deepcopy(data["quiz"]["questions"]))
    values: dict[str, Any] = {
        "module_unit_id": UNIT_ID,
        "language": language,
        "unit_number": "1.2",
        "unit_title": {"en": "Preventing malaria in children", "fr": "Prévenir le paludisme"},
        "module_title": {"en": "Malaria control", "fr": "Lutte contre le paludisme"},
        "course_title": {"en": "Public health", "fr": "Santé publique"},
        "module_number": 3,
        "lesson": copy.deepcopy(data["lesson"]),
        "mcqs": mcqs,
        "has_quiz": bool(mcqs),
    }
    values.update(overrides)
    return repair.LessonStoryContext(**values)


class FakeClaude:
    """Stands in for ClaudeService.generate_structured_content.

    Returns the queued responses in order (the last one repeats) and records
    every user message, so tests can count calls and read repair feedback.
    """

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.messages: list[str] = []
        self.content_types: list[str] = []

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        self.content_types.append(content_type)
        index = min(len(self.messages) - 1, len(self.responses) - 1)
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


def revalidate(doc: dict[str, Any]):
    """Validate the stored document from scratch, as the publish route does."""
    return validate_story_course(StoryCourse.model_validate(copy.deepcopy(doc)))


def steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for c in doc["chapters"] for s in c["scenes"] for step in s["steps"]]


# --------------------------------------------------------------------------
# The load-bearing test
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_lesson_and_quiz_give_a_story_with_zero_errors_and_zero_warnings(raw, language):
    model = FakeClaude(raw[language]["spine"])
    generation = await StoryFromLessonService(model).generate_document(
        make_ctx(raw, language), system_prompt="system"
    )

    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.report.errors == []
    assert generation.report.warnings == [], [w.model_dump() for w in generation.report.warnings]
    assert generation.model_calls == 1
    assert model.content_types == ["story"]

    # The stored document itself must re-validate clean, checks included.
    report = revalidate(generation.doc)
    assert report.ok
    assert report.errors == [] and report.warnings == []

    # Every stored MCQ became a question, asked once.
    doc = generation.doc
    derived = [q for q in doc["questions"] if q.get("derived_from")]
    assert [q["derived_from"] for q in derived] == ["q1", "q2", "q3", "q4"]


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_story_follows_the_cross_track_contracts(raw, language):
    generation = await StoryFromLessonService(FakeClaude(raw[language]["spine"])).generate_document(
        make_ctx(raw, language), system_prompt="system"
    )
    doc = generation.doc
    home = "en" if language == "fr" else "fr"

    # C1: the language pair, and every text object carries both languages.
    assert doc["languages"] == {"target": language, "home": home}
    for step in steps(doc):
        if step["type"] in ("narrate", "say", "concept"):
            assert step["en"] and step["fr"]
    # C2: story lines at most 100 characters in BOTH languages.
    for step in steps(doc):
        if step["type"] in ("narrate", "say"):
            assert len(step["en"]) <= 100 and len(step["fr"]) <= 100
    # C4: the learner is the hero.
    assert doc["learner"] == {"first_name": "{child}"}
    assert any("{child}" in s.get("en", "") for s in steps(doc) if s["type"] == "narrate")
    # C5: catch mini-game, items rounds, per_correct 1, no rule.
    (game,) = doc["minigames"]
    assert game["engine"] == "catch" and game["points"] == {"per_correct": 1}
    assert "rule" not in game
    assert all("items" in r and "prompt" in r for r in game["rounds"])
    # C6: the validator's checks are stored in the document.
    checks = doc["checks"]
    assert checks["max_points"] == generation.report.checks.max_points > 0
    assert checks["questions"] == len(doc["questions"])
    assert checks["errors"] == 0 and checks["warnings"] == 0
    assert checks["predicted_typical"]["points"] <= checks["max_points"]
    # C8: the reserved slug.
    assert doc["id"] == f"lesson-{UNIT_ID.hex}-{language}"


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_a_stored_question_the_validator_rejects_costs_no_repair_call(raw, language):
    """A cached quiz question that the story validator's MCQ checks reject
    (here: two options equal but for a final period) is left out before the
    model is called, so the story still takes one call and validates clean."""
    quiz = copy.deepcopy(raw[language]["quiz"]["questions"])
    quiz.append(
        {
            "id": "defective",
            "question": quiz[0]["question"],
            "options": ["In the morning", "In the morning.", "At noon", "At night"],
            "correct_answer": 0,
        }
    )
    mcqs, dropped = repair.parse_quiz_mcqs(quiz)
    assert dropped == [{"question": "defective", "reason": "duplicate_options"}]

    model = FakeClaude(raw[language]["spine"])
    generation = await StoryFromLessonService(model).generate_document(
        make_ctx(raw, language, mcqs=mcqs, has_quiz=True), system_prompt="system"
    )

    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.model_calls == 1


# --------------------------------------------------------------------------
# Quiz fidelity
# --------------------------------------------------------------------------


def _tampering_spine(spine: dict[str, Any], target: str) -> dict[str, Any]:
    """A model that tries to rewrite the quiz it was told to leave alone."""
    spine = copy.deepcopy(spine)
    for derived in spine["derived"]:
        derived["prompt"] = {target: "TAMPERED STEM", "en": "TAMPERED", "fr": "TRAFIQUÉ"}
        derived["question"] = "TAMPERED STEM"
        derived["options"] = ["TAMPERED A", "TAMPERED B", "TAMPERED C", "TAMPERED D"]
        derived["choices"] = [{"id": "a", "en": "X", "fr": "X"}]
        derived["answer"] = "d"
        derived["correct_answer"] = 3
        derived["explanation"] = {"en": "TAMPERED", "fr": "TRAFIQUÉ"}
        # And claims a misconception for the correct option.
        derived["distractors"].append({"option": "a", "misconception": "m_day_biting"})
        derived["distractors"].append({"option": "c", "misconception": "m_day_biting"})
    # An "extra" question that reuses a derived id to overwrite it.
    spine["questions"].append(
        {
            "id": "q1",
            "type": "choice",
            "prompt": {"en": "Overwritten?", "fr": "Écrasée ?"},
            "choices": [
                {"id": "a", "en": "Yes", "fr": "Oui"},
                {"id": "b", "en": "No", "fr": "Non", "misconception": "m_day_biting"},
            ],
            "answer": "a",
        }
    )
    return spine


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_a_tampering_model_cannot_change_the_quiz(raw, language):
    quiz = raw[language]["quiz"]["questions"]
    spine = _tampering_spine(raw[language]["spine"], language)
    generation = await StoryFromLessonService(FakeClaude(spine)).generate_document(
        make_ctx(raw, language), system_prompt="system"
    )
    doc = generation.doc
    all_steps = steps(doc)
    by_id = {q["id"]: q for q in doc["questions"]}

    for number, stored in enumerate(quiz, start=1):
        question = by_id[f"q{number}"]
        assert question["type"] == "choice"
        assert [c[language] for c in question["choices"]] == stored["options"]
        letter = "abcd"[stored["correct_answer"]]
        assert question["answer"] == letter
        correct = next(c for c in question["choices"] if c["id"] == letter)
        assert "misconception" not in correct
        situation = next((s for s in all_steps if s.get("id") == f"situation-q{number}"), None)
        if situation is not None:
            assert situation[language] == [stored["question"]]
        else:
            assert question["prompt"][language] == stored["question"]
        assert question["explanation"][language] == stored["explanation"]

    # The colliding extra question was renamed, not merged into q1.
    assert len([q for q in doc["questions"] if q["id"] == "q1"]) == 1
    assert "TAMPERED" not in json.dumps(doc)


def test_enforce_quiz_fidelity_restores_edited_quiz_text(raw):
    ctx = make_ctx(raw, "en")
    doc = repair.build_story_document(ctx, raw["en"]["spine"]).doc
    q1 = doc["questions"][0]
    q1["prompt"]["en"] = "edited"
    q1["choices"][0]["en"] = "edited"
    q1["answer"] = "a"
    repair.enforce_quiz_fidelity(doc, ctx)
    stored = raw["en"]["quiz"]["questions"][0]
    assert q1["prompt"]["en"] == stored["question"]
    assert q1["choices"][0]["en"] == stored["options"][0]
    assert q1["answer"] == "c"


# --------------------------------------------------------------------------
# Repair loop, salvage and drafts
# --------------------------------------------------------------------------


def _spine_without_misconceptions(spine: dict[str, Any]) -> dict[str, Any]:
    broken = copy.deepcopy(spine)
    for derived in broken["derived"]:
        derived["distractors"] = []
    return broken


async def test_repair_loop_feeds_errors_back_and_stops_when_clean(raw):
    broken = _spine_without_misconceptions(raw["en"]["spine"])
    model = FakeClaude(broken, raw["en"]["spine"])
    generation = await StoryFromLessonService(model).generate_document(
        make_ctx(raw, "en"), system_prompt="system"
    )
    assert generation.report.ok and generation.model_calls == 2
    feedback = model.messages[1]
    assert "=== REPAIR (attempt 1 of 3) ===" in feedback
    assert "[distractor_without_misconception] questions[q1].choices[0]" in feedback
    assert '"derived"' in feedback  # the previous spine is quoted back


async def test_repair_loop_stops_after_its_budget(raw):
    broken = _spine_without_misconceptions(raw["en"]["spine"])
    # Without the course's own option_misconceptions, nothing can fill the gap.
    ctx = make_ctx(raw, "en")
    for mcq in ctx.mcqs:
        mcq.option_misconceptions = []
    model = FakeClaude(broken)
    generation = await StoryFromLessonService(model).generate_document(ctx, system_prompt="system")
    assert len(model.messages) == 3  # the first call plus 2 repairs
    assert generation.model_calls == 3
    assert not generation.report.ok
    assert not generation.salvaged  # dropping every question is not a story
    assert generation.doc["checks"]["errors"] == len(generation.report.errors) > 0


async def test_unreadable_answers_count_against_the_budget(raw):
    model = FakeClaude({"raw_response": True, "content": "{oops"}, ValueError("truncated"))
    generation = await StoryFromLessonService(model).generate_document(
        make_ctx(raw, "en"), system_prompt="system"
    )
    assert len(model.messages) == 3
    assert not generation.report.ok
    assert "could not be read as JSON" in model.messages[1]


async def test_salvage_drops_a_model_question_that_never_validates(raw):
    spine = copy.deepcopy(raw["en"]["spine"])
    spine["questions"].append(
        {
            "id": "x2",
            "type": "choice",
            "objective": "o2",
            "prompt": {"en": "Which drug treats confirmed malaria?", "fr": "Quel médicament ?"},
            "choices": [
                {"id": "a", "en": "ACT", "fr": "CTA"},
                {"id": "b", "en": "Aspirin", "fr": "Aspirine"},
            ],
            "answer": "a",
        }
    )
    model = FakeClaude(spine)
    generation = await StoryFromLessonService(model).generate_document(
        make_ctx(raw, "en"), system_prompt="system"
    )
    assert generation.salvaged
    assert generation.report.ok
    assert "x2" not in {q["id"] for q in generation.doc["questions"]}
    assert generation.dropped["questions"] == ["x2"]
    assert len(model.messages) == 3


async def test_unit_without_a_quiz_still_validates(raw):
    spine = copy.deepcopy(raw["en"]["spine"])
    spine["derived"] = []
    spine["questions"] = [
        {
            "id": f"x{n}",
            "type": "choice",
            "objective": objective,
            "prompt": {"en": prompt_en, "fr": prompt_fr},
            "choices": [
                {"id": "a", "en": right_en, "fr": right_fr},
                {"id": "b", "en": wrong_en, "fr": wrong_fr, "misconception": misconception},
            ],
            "answer": "a",
            "hints": [{"en": "Think back to the lesson.", "fr": "Repense à la leçon."}],
        }
        for n, (
            objective,
            prompt_en,
            prompt_fr,
            right_en,
            right_fr,
            wrong_en,
            wrong_fr,
            misconception,
        ) in enumerate(
            [
                (
                    "o1",
                    "When should a net be used?",
                    "Quand utiliser la moustiquaire ?",
                    "Every night",
                    "Chaque nuit",
                    "Only in the rainy season",
                    "Seulement en saison des pluies",
                    "m_day_biting",
                ),
                (
                    "o1",
                    "Who receives SMC?",
                    "Qui reçoit la CPS ?",
                    "Children aged 3-59 months",
                    "Les enfants de 3 à 59 mois",
                    "All adults",
                    "Tous les adultes",
                    "m_school_age",
                ),
                (
                    "o2",
                    "What comes before ACT?",
                    "Que faut-il avant une CTA ?",
                    "A positive test",
                    "Un test positif",
                    "A high fever alone",
                    "Une forte fièvre seule",
                    "m_fever_is_proof",
                ),
                (
                    "o2",
                    "The RDT is negative. Next step?",
                    "Le TDR est négatif. Ensuite ?",
                    "Look for another cause",
                    "Chercher une autre cause",
                    "Give ACT anyway",
                    "Donner une CTA quand même",
                    "m_season_overrides_test",
                ),
            ],
            start=1,
        )
    ]
    ctx = make_ctx(raw, "en", mcqs=[], has_quiz=False)
    assert plan_for(ctx).extra_questions == 4
    assert "this unit has no quiz yet" in build_story_user_message(ctx)

    generation = await StoryFromLessonService(FakeClaude(spine)).generate_document(
        ctx, system_prompt="system"
    )
    assert generation.report.ok
    assert generation.report.warnings == []
    assert not [s for s in generation.doc["sources"] if s["kind"] == "test"]


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


def test_story_prompts_are_registered_and_unit_bound():
    from app.ai.prompts.lesson import _UNIT_BINDING_REQUIRED_KEYS
    from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

    for key in (STORY_SYSTEM_KEY, STORY_KIDS_SYSTEM_KEY):
        assert key in DEFAULTS_BY_KEY, "an unregistered key renders an EMPTY prompt"
        assert "{unit_title}" in DEFAULTS_BY_KEY[key].default
        assert key in _UNIT_BINDING_REQUIRED_KEYS
    flag = DEFAULTS_BY_KEY["story-mode-feature-enabled"]
    assert flag.default is True and flag.value_type == "boolean"


def test_system_prompt_renders_the_child_placeholder_and_languages():
    prompt = get_story_system_prompt("fr", "CI", 2, "apply", "Santé publique", None, "M", "Unit X")
    assert "{child}" in prompt
    assert "Unit X" in prompt
    assert "Language of instruction: French; home language: English" in prompt
    assert prompt.rstrip().endswith("ending with }.")


def test_kids_courses_get_the_kids_prompt():
    course = SimpleNamespace(
        taxonomy_categories=[SimpleNamespace(type="audience", slug="primary_school")],
        title_en="Science (Ages 8-10)",
        title_fr="Sciences",
    )
    prompt = get_story_system_prompt("en", "CI", 1, "remember", "Science", course=course)
    assert "young learners aged 8-10" in prompt


def test_feature_is_attributed_in_the_cost_ledger():
    from app.ai.claude_service import _feature_for_content_type
    from app.domain.models.ai_usage_event import FEATURE_STORY_GENERATION

    assert _feature_for_content_type("story") == FEATURE_STORY_GENERATION == "story_generation"


def test_user_message_lists_the_quiz_and_its_misconceptions(raw):
    message = build_story_user_message(make_ctx(raw, "en"))
    assert "[q4] Which children receive seasonal malaria chemoprevention?" in message
    assert "c) At night  <- correct" in message
    assert "why it is wrong (from the course): Thinks only newborns are at risk." in message
    assert '"derived": exactly 4 entries' in message
    assert "{child}" in message and "{{child}}" not in message
    # Key points reach the model even though extract_lesson_text drops them.
    assert "4. Nets protect a whole community only when coverage is high." in message


# --------------------------------------------------------------------------
# Database edges, with a recording fake session
# --------------------------------------------------------------------------


class FakeResult:
    def __init__(self, value: Any = None, rows: list[Any] | None = None) -> None:
        self.value = value
        self.rows = rows if rows is not None else ([] if value is None else [value])

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, *results: FakeResult) -> None:
        self.results = list(results)
        self.added: list[Any] = []
        self.commits = 0
        self.statements: list[Any] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None

    async def rollback(self):
        return None

    async def get(self, model, key):
        return None


LESSON_CONTENT = {"introduction": "Nets work at night.", "key_points": ["Sleep under a net."]}
QUIZ_CONTENT = {"questions": [{"id": "q1", "question": "When?", "options": ["a", "b"]}]}


def _source_row(row_id: int, revision: int, content: dict, unit_id: uuid.UUID = UNIT_ID):
    """One row of the freshness query: id, revision, content, owning unit."""
    return SimpleNamespace(
        id=uuid.UUID(int=row_id),
        content_revision=revision,
        content=copy.deepcopy(content),
        module_unit_id=unit_id,
    )


def _bound_record(**overrides: Any) -> StoryCourseRecord:
    values = {
        "slug": f"lesson-{UNIT_ID.hex}-en",
        "module_unit_id": UNIT_ID,
        "language": "en",
        "source_lesson_content_id": uuid.UUID(int=1),
        "source_lesson_revision": 2,
        "source_lesson_digest": content_digest(LESSON_CONTENT),
        "source_quiz_content_id": uuid.UUID(int=2),
        "source_quiz_revision": 1,
        "source_quiz_digest": content_digest(QUIZ_CONTENT),
    }
    values.update(overrides)
    return StoryCourseRecord(**values)


def _no_quiz_record() -> StoryCourseRecord:
    return _bound_record(
        source_quiz_content_id=None, source_quiz_revision=None, source_quiz_digest=None
    )


def _module_units(*specs: tuple[uuid.UUID, str, int, str | None]):
    """Rows of the module-units query: (id, unit_number, order_index, unit_type)."""
    return FakeResult(
        rows=[
            SimpleNamespace(id=uid, unit_number=number, order_index=index, unit_type=kind)
            for uid, number, index, kind in specs
        ]
    )


LESSON_THEN_QUIZ = (
    (UNIT_ID, "1.2", 1, "lesson"),
    (QUIZ_UNIT_ID, "1.3", 2, "quiz"),
)


def _in_list(statement) -> list[Any]:
    """The values of the ``IN`` clause of a compiled statement."""
    params = statement.compile().params
    return next(v for v in params.values() if isinstance(v, list | tuple))


class TestContentDigest:
    def test_is_sha256_of_canonical_json(self):
        import hashlib

        expected = hashlib.sha256(b'{"a":[1,2],"b":"\xc3\xa9"}').hexdigest()
        assert content_digest({"b": "é", "a": [1, 2]}) == expected
        assert len(expected) == 64

    def test_key_order_does_not_matter_but_content_does(self):
        assert content_digest({"a": 1, "b": 2}) == content_digest({"b": 2, "a": 1})
        assert content_digest({"a": 1}) != content_digest({"a": 2})


class TestFreshness:
    async def test_hand_authored_weeks_are_never_stale(self):
        session = FakeSession()
        assert await story_sources_are_fresh(session, StoryCourseRecord(slug="w4"))
        assert session.statements == []

    async def test_fresh_when_revisions_and_digests_match(self):
        session = FakeSession(
            FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT), _source_row(2, 1, QUIZ_CONTENT)])
        )
        assert await story_sources_are_fresh(session, _bound_record())
        assert len(session.statements) == 1  # the unit's own quiz: nothing else to check

    async def test_stale_when_the_lesson_was_regenerated(self):
        session = FakeSession(
            FakeResult(rows=[_source_row(1, 3, LESSON_CONTENT), _source_row(2, 1, QUIZ_CONTENT)])
        )
        assert not await story_sources_are_fresh(session, _bound_record())

    async def test_stale_when_the_quiz_was_regenerated(self):
        session = FakeSession(
            FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT), _source_row(2, 2, QUIZ_CONTENT)])
        )
        assert not await story_sources_are_fresh(session, _bound_record())

    async def test_stale_when_the_lesson_was_edited_without_a_new_revision(self):
        """An admin's manual edit (admin_courses.edit_content) keeps the revision."""
        edited = {**LESSON_CONTENT, "introduction": "Corrected: nets work at night."}
        session = FakeSession(
            FakeResult(rows=[_source_row(1, 2, edited), _source_row(2, 1, QUIZ_CONTENT)])
        )
        assert not await story_sources_are_fresh(session, _bound_record())

    async def test_stale_when_the_quiz_was_edited_without_a_new_revision(self):
        """A corrected answer must reach the story even though the revision is the same."""
        edited = copy.deepcopy(QUIZ_CONTENT)
        edited["questions"][0]["correct_answer"] = 1
        session = FakeSession(
            FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT), _source_row(2, 1, edited)])
        )
        assert not await story_sources_are_fresh(session, _bound_record())

    async def test_stale_when_no_digest_was_recorded(self):
        session = FakeSession(
            FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT), _source_row(2, 1, QUIZ_CONTENT)])
        )
        assert not await story_sources_are_fresh(session, _bound_record(source_lesson_digest=None))

    async def test_stale_when_the_quiz_was_deleted(self):
        record = _bound_record(source_quiz_content_id=None)  # FK SET NULL
        session = FakeSession(FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT)]))
        assert not await story_sources_are_fresh(session, record)

    async def test_story_without_a_quiz_goes_stale_once_the_unit_has_one(self):
        no_quiz = FakeSession(
            FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT)]),
            _module_units((UNIT_ID, "1.2", 1, "lesson")),
            FakeResult(rows=[]),
        )
        assert await story_sources_are_fresh(no_quiz, _no_quiz_record())
        quiz_now = FakeSession(
            FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT)]),
            _module_units((UNIT_ID, "1.2", 1, "lesson")),
            FakeResult(rows=[(uuid.UUID(int=9),)]),
        )
        assert not await story_sources_are_fresh(quiz_now, _no_quiz_record())

    async def test_story_without_a_quiz_goes_stale_once_its_covering_quiz_exists(self):
        session = FakeSession(
            FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT)]),
            _module_units(*LESSON_THEN_QUIZ),
            FakeResult(rows=[(uuid.UUID(int=9),)]),
        )
        assert not await story_sources_are_fresh(session, _no_quiz_record())
        # The quiz looked for is the lesson's own OR its covering quiz unit's.
        assert set(_in_list(session.statements[2])) == {UNIT_ID, QUIZ_UNIT_ID}

    async def test_story_from_a_covering_quiz_is_fresh_while_it_is_unchanged(self):
        session = FakeSession(
            FakeResult(
                rows=[
                    _source_row(1, 2, LESSON_CONTENT),
                    _source_row(2, 1, QUIZ_CONTENT, unit_id=QUIZ_UNIT_ID),
                ]
            ),
            FakeResult(rows=[]),  # the lesson unit still has no quiz of its own
        )
        assert await story_sources_are_fresh(session, _bound_record())
        assert _in_list(session.statements[1]) == [UNIT_ID]

    async def test_story_from_a_covering_quiz_goes_stale_when_that_quiz_is_edited(self):
        edited = copy.deepcopy(QUIZ_CONTENT)
        edited["questions"][0]["question"] = "When exactly?"
        session = FakeSession(
            FakeResult(
                rows=[
                    _source_row(1, 2, LESSON_CONTENT),
                    _source_row(2, 1, edited, unit_id=QUIZ_UNIT_ID),
                ]
            )
        )
        assert not await story_sources_are_fresh(session, _bound_record())

    async def test_story_from_a_covering_quiz_goes_stale_once_the_lesson_has_its_own(self):
        session = FakeSession(
            FakeResult(
                rows=[
                    _source_row(1, 2, LESSON_CONTENT),
                    _source_row(2, 1, QUIZ_CONTENT, unit_id=QUIZ_UNIT_ID),
                ]
            ),
            FakeResult(rows=[(uuid.UUID(int=9),)]),
        )
        assert not await story_sources_are_fresh(session, _bound_record())


class TestCoveringQuizUnit:
    """The quiz unit whose quiz a lesson's story draws its questions from."""

    UNITS = [
        SimpleNamespace(id=n, unit_number=f"1.{n}", order_index=n - 1, unit_type=kind)
        for n, kind in enumerate(
            ["lesson", "lesson", "quiz", "lesson", "case-study", "quiz", "lesson"], start=1
        )
    ]

    @pytest.mark.parametrize(
        ("lesson", "quiz"),
        [(1, 3), (2, 3), (4, 6), (7, 6)],
        ids=["first", "just-before", "past-a-case-study", "after-the-last-quiz"],
    )
    def test_first_quiz_after_else_nearest_before(self, lesson, quiz):
        assert covering_quiz_unit(self.UNITS, lesson).id == quiz

    def test_follows_teaching_order_not_row_order(self):
        units = list(reversed(self.UNITS))
        assert covering_quiz_unit(units, 1).id == 3

    def test_unit_numbers_sort_naturally_on_an_order_index_tie(self):
        units = [
            SimpleNamespace(id="l", unit_number="1.9", order_index=0, unit_type="lesson"),
            SimpleNamespace(id="q10", unit_number="1.10", order_index=0, unit_type="quiz"),
            SimpleNamespace(id="q2", unit_number="1.2", order_index=0, unit_type="quiz"),
        ]
        assert covering_quiz_unit(units, "l").id == "q10"

    def test_no_quiz_unit_in_the_module(self):
        units = [u for u in self.UNITS if u.unit_type != "quiz"]
        assert covering_quiz_unit(units, 1) is None
        assert covering_quiz_unit(self.UNITS, "not-in-module") is None


class TestUpsert:
    async def test_lesson_story_that_is_not_publishable_is_demoted_to_draft(self, raw):
        doc = repair.build_story_document(make_ctx(raw, "en"), {}).doc
        report = validate_document(doc)
        assert not report.ok
        existing = StoryCourseRecord(slug=doc["id"], status="published")
        session = FakeSession(FakeResult(existing))
        binding = StoryBinding(MODULE_ID, UNIT_ID, "en", uuid.UUID(int=1), 4)
        record = await upsert_story_course(
            session,
            course=StoryCourse.model_validate(doc),
            content=doc,
            report=report,
            course_id=None,
            publish=False,
            binding=binding,
        )
        assert record is existing
        assert record.status == "draft" and record.is_valid is False
        assert record.module_unit_id == UNIT_ID and record.source_lesson_revision == 4

    async def test_authored_week_saved_without_publish_stays_published(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "story_course_w04.json").read_text("utf-8")
        )
        course = StoryCourse.model_validate(fixture)
        existing = StoryCourseRecord(slug=course.id, status="published")
        session = FakeSession(FakeResult(existing))
        record = await upsert_story_course(
            session,
            course=course,
            content=fixture,
            report=validate_story_course(course),
            course_id=None,
            publish=False,
        )
        assert record.status == "published"
        assert record.module_unit_id is None


# --------------------------------------------------------------------------
# The orchestration, end to end with fakes
# --------------------------------------------------------------------------


def _module_and_unit():
    course = SimpleNamespace(
        title_en="Public health",
        title_fr="Santé publique",
        description_en="",
        description_fr="",
        taxonomy_categories=[],
    )
    module = SimpleNamespace(
        id=MODULE_ID,
        course=course,
        course_id=uuid.UUID(int=77),
        title_en="Malaria control",
        title_fr="Lutte contre le paludisme",
        module_number=3,
        bloom_level="apply",
    )
    unit = SimpleNamespace(
        id=UNIT_ID,
        unit_number="1.2",
        title_en="Preventing malaria in children",
        title_fr="Prévenir le paludisme",
        unit_type="lesson",
    )
    return module, unit


def _content_row(content: dict, revision: int, row_id: int):
    return SimpleNamespace(
        id=uuid.UUID(int=row_id),
        content=copy.deepcopy(content),
        level=1,
        country_context="CI",
        content_revision=revision,
    )


@pytest.mark.parametrize("valid", [True, False])
async def test_generate_and_store_a_unit_story(raw, valid):
    module, unit = _module_and_unit()
    lesson = _content_row(raw["en"]["lesson"], 2, 1)
    quiz = _content_row(raw["en"]["quiz"], 1, 2)
    session = FakeSession(
        FakeResult(module),  # the module, with its course
        FakeResult(unit),  # the unit
        FakeResult(None),  # no cached story yet
        FakeResult(rows=[lesson]),  # cached lesson rows
        FakeResult(rows=[quiz]),  # cached quiz rows
        FakeResult(None),  # upsert: no row with this slug
    )
    spine = raw["en"]["spine"] if valid else _spine_without_misconceptions(raw["en"]["spine"])
    if not valid:
        quiz.content["questions"][3].pop("option_misconceptions")
    model = FakeClaude(spine)

    record = await StoryFromLessonService(model).get_or_generate_unit_story(
        MODULE_ID, "1.2", "en", session
    )

    assert session.added == [record] and session.commits == 1
    assert record.slug == f"lesson-{UNIT_ID.hex}-en"
    assert record.module_id == MODULE_ID and record.module_unit_id == UNIT_ID
    assert record.language == "en"
    assert record.source_lesson_content_id == lesson.id and record.source_lesson_revision == 2
    assert record.source_quiz_content_id == quiz.id and record.source_quiz_revision == 1
    assert record.source_lesson_digest == content_digest(lesson.content)
    assert record.source_quiz_digest == content_digest(quiz.content)
    assert record.course_id == module.course_id
    assert record.content["checks"]["max_points"] == record.max_points
    assert record.validation_report["ok"] is valid
    if valid:
        assert record.status == "published" and record.is_valid is True
        assert len(model.messages) == 1
    else:
        assert record.status == "draft" and record.is_valid is False
        assert len(model.messages) == 3
        assert record.validation_report["errors"]


async def test_a_fresh_cached_story_is_returned_without_calling_the_model(raw):
    module, unit = _module_and_unit()
    cached = _bound_record()
    session = FakeSession(
        FakeResult(module),
        FakeResult(unit),
        FakeResult(cached),
        FakeResult(rows=[_source_row(1, 2, LESSON_CONTENT), _source_row(2, 1, QUIZ_CONTENT)]),
    )
    model = FakeClaude({})
    record = await StoryFromLessonService(model).get_or_generate_unit_story(
        MODULE_ID, "1.2", "en", session
    )
    assert record is cached
    assert model.messages == []


async def test_unknown_unit_is_a_value_error():
    module, _unit = _module_and_unit()
    session = FakeSession(FakeResult(module), FakeResult(None))
    with pytest.raises(ValueError, match="not found"):
        await StoryFromLessonService(FakeClaude({})).get_or_generate_unit_story(
            MODULE_ID, "9.9", "en", session
        )


async def test_missing_lesson_without_a_lesson_service_is_a_value_error(raw):
    module, unit = _module_and_unit()
    session = FakeSession(
        FakeResult(module), FakeResult(unit), FakeResult(None), FakeResult(rows=[])
    )
    with pytest.raises(ValueError, match="No lesson is cached"):
        await StoryFromLessonService(FakeClaude({})).get_or_generate_unit_story(
            MODULE_ID, "1.2", "en", session
        )


@pytest.mark.parametrize("unit_type", ["quiz", "case-study", "scenario"])
async def test_a_non_lesson_unit_generates_nothing(raw, unit_type):
    """FC-8: no orphan lesson, no story, no model call for a quiz/case/scenario unit."""
    module, unit = _module_and_unit()
    unit.unit_type = unit_type
    session = FakeSession(FakeResult(module), FakeResult(unit))
    model = FakeClaude(raw["en"]["spine"])

    class LessonService:
        calls = 0

        async def get_or_generate_lesson(self, **kwargs):
            LessonService.calls += 1
            raise AssertionError("a lesson was generated for a non-lesson unit")

    service = StoryFromLessonService(model, lesson_service=LessonService())
    with pytest.raises(NotALessonUnit):
        await service.get_or_generate_unit_story(MODULE_ID, "1.2", "en", session)
    assert model.messages == [] and LessonService.calls == 0
    assert session.added == [] and session.commits == 0
    with pytest.raises(NotALessonUnit):
        await service._lesson_row(session, module, unit, "en", 1, "CI")


# --------------------------------------------------------------------------
# A covering quiz unit: the lesson unit has no quiz of its own (FC-2)
# --------------------------------------------------------------------------

#: MCQs of the module's quiz unit that test OTHER lessons than the fixture's.
OTHER_LESSON_MCQS = {
    "en": [
        {
            "id": "tb1",
            "question": "How long does standard tuberculosis treatment last?",
            "options": ["Two weeks", "Six months", "Ten years", "One day"],
            "correct_answer": 1,
            "explanation": "The standard regimen lasts six months.",
        },
        {
            "id": "wash1",
            "question": "When should hands be washed with soap?",
            "options": ["Only on Sundays", "Before eating", "Never", "Once a year"],
            "correct_answer": 1,
            "explanation": "Washing before eating stops germs.",
        },
    ],
    "fr": [
        {
            "id": "tb1",
            "question": "Combien de temps dure le traitement standard de la tuberculose ?",
            "options": ["Deux semaines", "Six mois", "Dix ans", "Un jour"],
            "correct_answer": 1,
            "explanation": "Le schéma standard dure six mois.",
        },
        {
            "id": "wash1",
            "question": "Quand faut-il se laver les mains au savon ?",
            "options": ["Le dimanche", "Avant de manger", "Jamais", "Une fois par an"],
            "correct_answer": 1,
            "explanation": "Se laver avant de manger arrête les microbes.",
        },
    ],
}


def covering_quiz(raw: dict[str, Any], language: str) -> dict[str, Any]:
    """The quiz unit's quiz: one other lesson's MCQ, the fixture's four, another one."""
    other = copy.deepcopy(OTHER_LESSON_MCQS[language])
    return {"questions": [other[0], *copy.deepcopy(raw[language]["quiz"]["questions"]), other[1]]}


def picking_spine(raw: dict[str, Any], language: str, *extra_refs: str) -> dict[str, Any]:
    """The fixture spine, its picks renumbered to the covering quiz (q1..q4 -> q2..q5).

    ``extra_refs`` are appended as further picks (unknown ids, or more picks).
    """
    spine = copy.deepcopy(raw[language]["spine"])
    for entry in spine["derived"]:
        entry["ref"] = f"q{int(entry['ref'][1:]) + 1}"
    template = spine["derived"][0]
    for ref in extra_refs:
        spine["derived"].append({**copy.deepcopy(template), "ref": ref})
    return spine


def covering_ctx(raw: dict[str, Any], language: str) -> repair.LessonStoryContext:
    mcqs, _ = repair.parse_quiz_mcqs(covering_quiz(raw, language)["questions"])
    return make_ctx(
        raw, language, mcqs=mcqs, has_quiz=True, quiz_scope="covering", quiz_unit_number="1.3"
    )


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_story_derives_verbatim_from_a_sibling_quiz_unit(raw, language):
    """The picked MCQs of the covering quiz, verbatim; 0 errors, 0 warnings."""
    ctx = covering_ctx(raw, language)
    model = FakeClaude(picking_spine(raw, language, "q99", "zz"))
    generation = await StoryFromLessonService(model).generate_document(ctx, system_prompt="system")

    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.report.errors == []
    assert generation.report.warnings == [], [w.model_dump() for w in generation.report.warnings]
    assert revalidate(generation.doc).ok
    assert generation.model_calls == 1

    doc = generation.doc
    stored = raw[language]["quiz"]["questions"]
    derived = [q for q in doc["questions"] if q.get("derived_from")]
    # The four relevant MCQs, in quiz order, under their candidate ids.
    assert [q["derived_from"] for q in derived] == [m["id"] for m in stored]
    assert [q["id"] for q in derived] == ["q2", "q3", "q4", "q5"]
    by_source = {q["derived_from"]: q for q in derived}
    for mcq in stored:
        question = by_source[mcq["id"]]
        assert [c[language] for c in question["choices"]] == mcq["options"]
        assert question["answer"] == "abcd"[mcq["correct_answer"]]
        shown = question.get("stem", question["prompt"])[language]
        assert shown == mcq["question"]
    # Irrelevant MCQs never reach the story; unknown picks are ignored.
    text = json.dumps(doc, ensure_ascii=False)
    for other in OTHER_LESSON_MCQS[language]:
        assert other["question"] not in text
        assert other["id"] not in {q.get("derived_from") for q in doc["questions"]}
    assert not {"q1", "q6", "q99", "zz"} & {q["id"] for q in doc["questions"]}
    assert {"kind": "test", "ref": "Unit 1.3 quiz", "used_for": "questions, derived verbatim"} in (
        doc["sources"]
    )

    # The model was given every candidate, with its id, and told to pick.
    message = model.messages[0]
    assert "CANDIDATE QUIZ QUESTIONS from the quiz of unit 1.3" in message
    assert f"[q1] {OTHER_LESSON_MCQS[language][0]['question']}" in message
    assert f"[q6] {OTHER_LESSON_MCQS[language][1]['question']}" in message
    assert f"at most {repair.MAX_PICKED_MCQS}" in message


async def test_picks_from_a_covering_quiz_are_bounded(raw):
    ctx = covering_ctx(raw, "en")
    spine = picking_spine(raw, "en", "q1", "q6")  # six picks, all of them known
    picked = repair.picked_mcqs(ctx, spine)
    assert [m.ref for m in picked] == ["q2", "q3", "q4", "q5"]  # the first 4 picked
    assert len(picked) == repair.MAX_PICKED_MCQS


def test_the_lesson_units_own_quiz_is_used_whole(raw):
    """No picking when the quiz is the lesson's own: every MCQ is a question."""
    ctx = make_ctx(raw, "en")
    assert [m.ref for m in repair.picked_mcqs(ctx, {"derived": []})] == ["q1", "q2", "q3", "q4"]


def _sibling_session(raw, module, unit, *, cached_quiz: bool):
    lesson = _content_row(raw["en"]["lesson"], 2, 1)
    quiz = _content_row(covering_quiz(raw, "en"), 3, 2)
    quiz.module_unit_id = QUIZ_UNIT_ID
    results = [
        FakeResult(module),  # the module, with its course
        FakeResult(unit),  # the unit
        FakeResult(None),  # no cached story yet
        FakeResult(rows=[lesson]),  # cached lesson rows
        FakeResult(rows=[]),  # the lesson unit has no quiz of its own
        _module_units(*LESSON_THEN_QUIZ),  # the module's units
        FakeResult(rows=[quiz] if cached_quiz else []),  # the quiz unit's cached quiz
        FakeResult(None),  # upsert: no row with this slug
    ]
    return FakeSession(*results), lesson, quiz


async def test_a_unit_story_is_built_from_its_covering_quiz_unit(raw):
    module, unit = _module_and_unit()
    session, lesson, quiz = _sibling_session(raw, module, unit, cached_quiz=True)
    model = FakeClaude(picking_spine(raw, "en"))

    record = await StoryFromLessonService(model).get_or_generate_unit_story(
        MODULE_ID, "1.2", "en", session
    )

    assert record.status == "published" and record.is_valid is True
    assert record.validation_report["warnings"] == []
    assert record.source_quiz_content_id == quiz.id and record.source_quiz_revision == 3
    assert record.source_quiz_digest == content_digest(quiz.content)
    derived = [q["derived_from"] for q in record.content["questions"] if q.get("derived_from")]
    assert derived == [m["id"] for m in raw["en"]["quiz"]["questions"]]
    assert "CANDIDATE QUIZ QUESTIONS from the quiz of unit 1.3" in model.messages[0]
    # The quiz of the covering unit was read from the cache, not generated.
    assert QUIZ_UNIT_ID in session.statements[6].compile().params.values()
    assert model.content_types == ["story"]


async def test_without_a_cached_covering_quiz_the_questions_are_model_authored(raw):
    module, unit = _module_and_unit()
    session, lesson, _quiz = _sibling_session(raw, module, unit, cached_quiz=False)
    spine = copy.deepcopy(raw["en"]["spine"])
    model = FakeClaude(spine)

    record = await StoryFromLessonService(model).get_or_generate_unit_story(
        MODULE_ID, "1.2", "en", session
    )

    assert record.source_quiz_content_id is None and record.source_quiz_digest is None
    assert not [q for q in record.content["questions"] if q.get("derived_from")]
    assert "this unit has no quiz yet" in model.messages[0]
    # Only story calls: no quiz is ever generated for a story.
    assert set(model.content_types) == {"story"}


# --------------------------------------------------------------------------
# A spine the builder chokes on (FC-3) and copied translations (FC-6)
# --------------------------------------------------------------------------


def _raising_builder(failures: int):
    """``build_story_document`` that raises for its first ``failures`` calls."""
    real = repair.build_story_document
    calls = {"n": 0}

    def build(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise TypeError("unhashable type: 'dict'")
        return real(*args, **kwargs)

    return build


async def test_a_spine_the_builder_chokes_on_costs_an_attempt_not_the_task(raw):
    model = FakeClaude(raw["en"]["spine"])
    with patch.object(repair, "build_story_document", side_effect=_raising_builder(1)):
        generation = await StoryFromLessonService(model).generate_document(
            make_ctx(raw, "en"), system_prompt="system"
        )
    assert generation.report.ok
    assert generation.model_calls == 2
    assert "[malformed_spine]" in model.messages[1]
    assert '"derived"' in model.messages[1]  # the spine is quoted back


async def test_hints_in_the_wrong_shape_no_longer_crash_the_pipeline(raw):
    spine = copy.deepcopy(raw["en"]["spine"])
    spine["questions"][0]["hints"] = {"en": "It is most people.", "fr": "La plupart."}
    generation = await StoryFromLessonService(FakeClaude(spine)).generate_document(
        make_ctx(raw, "en"), system_prompt="system"
    )
    assert generation.report.ok and generation.model_calls == 1


async def test_when_nothing_can_be_built_a_draft_is_stored_not_retried(raw):
    """Every attempt raises: the budget is spent, then a 409-able draft is stored."""
    module, unit = _module_and_unit()
    lesson = _content_row(raw["en"]["lesson"], 2, 1)
    quiz = _content_row(raw["en"]["quiz"], 1, 2)
    session = FakeSession(
        FakeResult(module),
        FakeResult(unit),
        FakeResult(None),
        FakeResult(rows=[lesson]),
        FakeResult(rows=[quiz]),
        FakeResult(None),
    )
    model = FakeClaude(raw["en"]["spine"])
    with patch.object(repair, "build_story_document", side_effect=_raising_builder(99)):
        record = await StoryFromLessonService(model).get_or_generate_unit_story(
            MODULE_ID, "1.2", "en", session
        )
    assert len(model.messages) == 3
    assert session.commits == 1
    assert record.status == "draft" and record.is_valid is False
    codes = [e["code"] for e in record.validation_report["errors"]]
    assert codes == ["malformed_course_file"]
    StoryCourse.model_validate(record.content)
    # Bound to its sources like any story, so the API answers 409 until they change.
    assert record.source_lesson_digest == content_digest(lesson.content)


async def test_when_only_the_spine_is_unusable_the_empty_build_is_the_draft(raw):
    model = FakeClaude(raw["en"]["spine"])
    with patch.object(repair, "build_story_document", side_effect=_raising_builder(3)):
        generation = await StoryFromLessonService(model).generate_document(
            make_ctx(raw, "en"), system_prompt="system"
        )
    assert not generation.report.ok
    assert [e.code for e in generation.report.errors] == ["malformed_course_file"]
    assert generation.doc["chapters"]  # the deterministic build of an empty spine
    assert generation.doc["checks"]["errors"] == 1


async def test_a_time_limit_is_never_mistaken_for_a_bad_spine(raw):
    from celery.exceptions import SoftTimeLimitExceeded

    model = FakeClaude(raw["en"]["spine"])
    with (
        patch.object(repair, "build_story_document", side_effect=SoftTimeLimitExceeded()),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        await StoryFromLessonService(model).generate_document(
            make_ctx(raw, "en"), system_prompt="system"
        )
    assert len(model.messages) == 1


async def test_a_time_limit_mid_generation_stores_nothing(raw):
    from celery.exceptions import SoftTimeLimitExceeded

    module, unit = _module_and_unit()
    session = FakeSession(
        FakeResult(module),
        FakeResult(unit),
        FakeResult(None),
        FakeResult(rows=[_content_row(raw["en"]["lesson"], 2, 1)]),
        FakeResult(rows=[_content_row(raw["en"]["quiz"], 1, 2)]),
    )
    broken = _spine_without_misconceptions(raw["en"]["spine"])
    model = FakeClaude(broken, SoftTimeLimitExceeded())  # the repair call is cut off
    with pytest.raises(SoftTimeLimitExceeded):
        await StoryFromLessonService(model).get_or_generate_unit_story(
            MODULE_ID, "1.2", "en", session
        )
    assert session.added == [] and session.commits == 0


def _spine_missing_a_translation(spine: dict[str, Any]) -> dict[str, Any]:
    spine = copy.deepcopy(spine)
    spine["objectives"][0].pop("fr")
    return spine


async def test_a_missing_translation_is_sent_back_for_repair(raw):
    model = FakeClaude(_spine_missing_a_translation(raw["en"]["spine"]), raw["en"]["spine"])
    generation = await StoryFromLessonService(model).generate_document(
        make_ctx(raw, "en"), system_prompt="system"
    )
    assert generation.model_calls == 2
    assert "[missing_translation] objectives[0].fr" in model.messages[1]
    assert generation.report.ok
    assert generation.report.warnings == []


async def test_a_translation_still_missing_after_the_budget_is_a_stored_warning(raw):
    module, unit = _module_and_unit()
    session = FakeSession(
        FakeResult(module),
        FakeResult(unit),
        FakeResult(None),
        FakeResult(rows=[_content_row(raw["en"]["lesson"], 2, 1)]),
        FakeResult(rows=[_content_row(raw["en"]["quiz"], 1, 2)]),
        FakeResult(None),
    )
    model = FakeClaude(_spine_missing_a_translation(raw["en"]["spine"]))
    record = await StoryFromLessonService(model).get_or_generate_unit_story(
        MODULE_ID, "1.2", "en", session
    )
    assert len(model.messages) == 3
    # The copy is kept as a last resort, and published — but never silently.
    assert record.status == "published" and record.is_valid is True
    report = record.validation_report
    assert report["errors"] == []
    assert [(w["code"], w["path"], w["severity"]) for w in report["warnings"]] == [
        ("missing_translation", "objectives[0].fr", "warning")
    ]
    assert record.content["checks"]["warnings"] == 1
    assert record.content["objectives"][0]["fr"] == record.content["objectives"][0]["en"]


# --------------------------------------------------------------------------
# Choosing among attempts, and one paid call per attempt
# --------------------------------------------------------------------------


def _picks_without_home_texts(raw: dict[str, Any]) -> dict[str, Any]:
    """Picks all four relevant MCQs, but two of them lack their home prompt/explanation."""
    spine = picking_spine(raw, "en")
    for entry in spine["derived"][:2]:
        entry.pop("prompt_home")
        entry.pop("explanation_home")
    return spine


def _picks_nothing(raw: dict[str, Any]) -> dict[str, Any]:
    """Picks no MCQ and writes one extra question: too few questions to publish."""
    spine = picking_spine(raw, "en")
    spine["derived"] = []
    return spine


async def test_an_attempt_that_only_copies_translations_beats_one_that_cannot_publish(raw):
    """Copies settle into warnings; too_few_questions never does. Rank accordingly."""
    model = FakeClaude(_picks_without_home_texts(raw), _picks_nothing(raw))
    generation = await StoryFromLessonService(model).generate_document(
        covering_ctx(raw, "en"), system_prompt="system"
    )

    assert generation.model_calls == 3
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    derived = [q["id"] for q in generation.doc["questions"] if q.get("derived_from")]
    assert derived == ["q2", "q3", "q4", "q5"]
    assert sorted(w.path for w in generation.report.warnings) == [
        "derived[q2].explanation_home",
        "derived[q2].prompt_home",
        "derived[q3].explanation_home",
        "derived[q3].prompt_home",
    ]
    assert {w.code for w in generation.report.warnings} == {"missing_translation"}


def test_attempts_are_ranked_by_what_still_blocks_them_once_settled():
    from app.api.v1.schemas.story_course import Checks, ValidationIssue
    from app.api.v1.schemas.story_course import ValidationReport as Report
    from app.domain.services.story_from_lesson_service import attempt_rank

    def report(*codes: str, warnings: int = 0) -> Report:
        def issue(code: str, severity: str = "error") -> ValidationIssue:
            return ValidationIssue(severity=severity, code=code, path="p", message="m")

        return Report(
            ok=not codes,
            errors=[issue(code) for code in codes],
            warnings=[issue("thin", "warning") for _ in range(warnings)],
            checks=Checks(errors=len(codes), warnings=warnings),
        )

    copies_only = report(*["missing_translation"] * 4)
    one_hard_error = report("too_few_questions")
    assert attempt_rank(copies_only) < attempt_rank(one_hard_error)
    assert attempt_rank(report("missing_translation")) < attempt_rank(copies_only)
    assert (
        attempt_rank(report())
        < attempt_rank(report(warnings=1))
        < attempt_rank(report("missing_translation"))
    )
    # A build without model content is never published: any build with some
    # comes first, however many errors it has.
    clean_but_empty = attempt_rank(report(), authored=False)
    assert attempt_rank(report("too_few_questions", "answer_leak", warnings=3)) < clean_but_empty
    assert clean_but_empty < attempt_rank(report("missing_translation"), authored=False)


#: What an unreadable answer gives :meth:`StoryFromLessonService._call_model`.
_UNREADABLE = {"raw_response": True, "content": "Here is your story, in prose."}


def _with_course_misconceptions(ctx: repair.LessonStoryContext) -> repair.LessonStoryContext:
    """Track A: every wrong option of every MCQ says why a learner would pick it.

    With these, the story built from no answer at all has no error but its
    copied translations — exactly what must never be published.
    """
    for mcq in ctx.mcqs:
        mcq.option_misconceptions = [
            None if index == mcq.correct_index else f"Believes {mcq.options[index]!r} is right."
            for index in range(len(mcq.options))
        ]
    return ctx


def _spine_with_x1(raw: dict[str, Any], language: str) -> dict[str, Any]:
    """The fixture spine with the model-authored question x1 (the fr one has none)."""
    spine = copy.deepcopy(raw[language]["spine"])
    if not any(q["id"] == "x1" for q in spine["questions"]):
        spine["questions"].append(copy.deepcopy(raw["en"]["spine"]["questions"][0]))
    return spine


def _failing_question(question_id: str):
    """``validate_document`` plus one hard error on ``question_id`` whenever it is asked."""
    real = validate_document

    def validate(doc: dict[str, Any]):
        report = real(doc)
        if any(q["id"] == question_id for q in doc["questions"]):
            issue = ValidationIssue(
                severity="error",
                code="persistent",
                path=f"questions[{question_id}].prompt",
                message="never fixed by the model",
            )
            report = repair.with_issues(report, [issue])
        return report

    return validate


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_an_unreadable_answer_never_beats_a_readable_attempt(raw, language):
    """Readable, unreadable, readable: the real attempt is salvaged, never the empty build.

    The empty build ranks (0 hard errors, 27 copies) against the real
    attempt's (1, 0): it would settle into a valid story with none of the
    model's content — generic lines, the concepts untranslated.
    """
    ctx = _with_course_misconceptions(make_ctx(raw, language))
    spine = _spine_with_x1(raw, language)
    model = FakeClaude(spine, _UNREADABLE, spine)
    with patch.object(service_module, "validate_document", side_effect=_failing_question("x1")):
        generation = await StoryFromLessonService(model).generate_document(
            ctx, system_prompt="system"
        )

    assert generation.model_calls == 3
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.salvaged and generation.dropped["questions"] == ["x1"]
    assert generation.report.warnings == [], [w.model_dump() for w in generation.report.warnings]
    assert revalidate(generation.doc).ok
    doc = generation.doc
    assert [q["id"] for q in doc["questions"]] == ["q1", "q2", "q3", "q4"]
    # The model's own story, fully translated.
    opening = spine["story"]["opening"]
    assert any(s["type"] == "narrate" and s["en"] == opening["en"] for s in steps(doc))
    concepts = [s for s in steps(doc) if s["type"] == "concept"]
    assert concepts and all(s["en"] != s["fr"] for s in concepts)


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("answer", ["unreadable", "empty object", "wrapped spine"])
async def test_a_story_without_model_content_is_never_published(raw, language, answer):
    """No attempt the builder could use anything of: a draft that says why, not a story."""
    ctx = _with_course_misconceptions(make_ctx(raw, language))
    response = {
        "unreadable": _UNREADABLE,
        "empty object": {},
        "wrapped spine": {"story_spine": raw[language]["spine"]},
    }[answer]
    model = FakeClaude(response)
    generation = await StoryFromLessonService(model).generate_document(ctx, system_prompt="system")

    assert generation.model_calls == 3
    assert not generation.report.ok
    assert [e.code for e in generation.report.errors] == ["no_model_content"]
    assert generation.doc["checks"]["errors"] == 1
    # Its copies are kept on record, as the warnings they would settle into.
    assert generation.report.warnings
    assert {w.code for w in generation.report.warnings} == {"missing_translation"}
    if answer == "unreadable":
        assert "could not be read as JSON" in model.messages[1]
    else:
        # Readable but unusable: told so, not handed the empty build's copies.
        assert "- [empty_spine]" in model.messages[1]
        assert "- [missing_translation]" not in model.messages[1]


async def test_a_story_without_model_content_is_stored_as_a_draft(raw):
    """The API then answers 409 until the lesson or quiz changes."""
    module, unit = _module_and_unit()
    lesson = _content_row(raw["en"]["lesson"], 2, 1)
    quiz_content = copy.deepcopy(raw["en"]["quiz"])
    for question in quiz_content["questions"]:
        question["option_misconceptions"] = [
            None if index == question["correct_answer"] else f"Believes {option!r} is right."
            for index, option in enumerate(question["options"])
        ]
    quiz = _content_row(quiz_content, 1, 2)
    session = FakeSession(
        FakeResult(module),
        FakeResult(unit),
        FakeResult(None),
        FakeResult(rows=[lesson]),
        FakeResult(rows=[quiz]),
        FakeResult(None),
    )
    model = FakeClaude(_UNREADABLE)
    record = await StoryFromLessonService(model).get_or_generate_unit_story(
        MODULE_ID, "1.2", "en", session
    )
    assert len(model.messages) == 3 and session.commits == 1
    assert record.status == "draft" and record.is_valid is False
    assert [e["code"] for e in record.validation_report["errors"]] == ["no_model_content"]
    assert record.source_quiz_digest == content_digest(quiz.content)


def _choice_without_misconception(number: int) -> dict[str, Any]:
    return {
        "id": f"x{number}",
        "type": "choice",
        "objective": "o2",
        "prompt": {
            "en": f"Which drug treats it (case {number})?",
            "fr": f"Quel médicament ({number}) ?",
        },
        "choices": [
            {"id": "a", "en": "ACT", "fr": "CTA"},
            {"id": "b", "en": "Aspirin", "fr": "Aspirine"},
        ],
        "answer": "a",
    }


async def test_when_the_best_attempt_cannot_be_salvaged_the_next_one_is(raw):
    """Best first, then the next: a draft only when no attempt can be published."""
    too_few = _picks_nothing(raw)  # too_few_questions: one error, nothing to drop
    two_bad = picking_spine(raw, "en")  # two errors, both on questions that can go
    two_bad["questions"] += [_choice_without_misconception(2), _choice_without_misconception(3)]
    model = FakeClaude(too_few, two_bad)
    generation = await StoryFromLessonService(model).generate_document(
        covering_ctx(raw, "en"), system_prompt="system"
    )

    assert generation.model_calls == 3
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.salvaged and generation.dropped["questions"] == ["x2", "x3"]
    assert [q["id"] for q in generation.doc["questions"]] == ["q2", "q3", "q4", "q5", "x1"]


def test_valid_results_are_ranked_copies_then_drops_then_warnings():
    from app.api.v1.schemas.story_course import Checks
    from app.api.v1.schemas.story_course import ValidationReport as Report
    from app.domain.services.story_from_lesson_service import StoryGeneration, outcome_rank

    def result(*codes: str, dropped: dict[str, list[str]] | None = None) -> StoryGeneration:
        warnings = [
            ValidationIssue(severity="warning", code=code, path="p", message="m") for code in codes
        ]
        report = Report(ok=True, warnings=warnings, checks=Checks(warnings=len(warnings)))
        return StoryGeneration(
            doc={}, report=report, model_calls=0, salvaged=bool(dropped), dropped=dropped or {}
        )

    one_drop = {"questions": ["x9"], "exercises": [], "minigames": []}
    two_drops = {"questions": ["x9"], "exercises": ["E2"], "minigames": []}
    assert (
        outcome_rank(result())
        < outcome_rank(result("thin_question_coverage"))
        < outcome_rank(result(dropped=one_drop))
        < outcome_rank(result(dropped=two_drops))
        < outcome_rank(result("missing_translation"))
    )
    # A dropped mini-game is a dropped item like any other.
    game = {"questions": [], "exercises": [], "minigames": [repair.MINIGAME_ID]}
    assert outcome_rank(result(dropped=game)) == outcome_rank(result(dropped=one_drop))


def _spine_with_x9(raw: dict[str, Any], language: str) -> dict[str, Any]:
    """The fixture spine plus x9: a real error salvage can drop (no misconception on 'b')."""
    spine = copy.deepcopy(raw[language]["spine"])
    spine["questions"].append(_choice_without_misconception(9))
    return spine


def _without_home_side(node: Any, home: str) -> Any:
    """``node`` with the home-language side of every text object removed, in place."""
    if isinstance(node, dict):
        if all(isinstance(node.get(lang), str) for lang in ("en", "fr")):
            node.pop(home)
        for value in node.values():
            _without_home_side(value, home)
    elif isinstance(node, list):
        for value in node:
            _without_home_side(value, home)
    return node


def _thin_answer(raw: dict[str, Any], language: str, kind: str) -> dict[str, Any]:
    """An answer of the model's own that is valid only once its copies are settled.

    Common answers to a repair message: a fragment of the spine, or the spine
    written in the target language alone. (The fr fixture has no extra
    question, so "questions only" takes the en one, x1.)
    """
    spine = copy.deepcopy(raw[language]["spine"])
    home = "fr" if language == "en" else "en"
    return {
        "opening only": {"story": {"opening": spine["story"]["opening"]}},
        "questions only": {"questions": copy.deepcopy(raw["en"]["spine"]["questions"])},
        "derived only": {"derived": spine["derived"]},
        "target language only": _without_home_side(spine, home),
    }[kind]


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize(
    "thin", ["opening only", "questions only", "derived only", "target language only"]
)
@pytest.mark.parametrize("thin_first", [False, True], ids=["thin-second", "thin-first"])
async def test_a_clean_salvage_beats_an_answer_valid_only_on_copies(
    raw, language, thin, thin_first
):
    """A real attempt with one salvageable error, and a thin answer of the model's own.

    The thin answer settles into a valid story, but only on its copied
    translations (a dozen to 65 lines in the wrong language); dropping the
    real attempt's one failing question (x9) gives the model's story with none.
    """
    ctx = _with_course_misconceptions(make_ctx(raw, language))
    real = _spine_with_x9(raw, language)
    thin_answer = _thin_answer(raw, language, thin)
    answers = (thin_answer, real) if thin_first else (real, thin_answer, real)
    model = FakeClaude(*answers)
    generation = await StoryFromLessonService(model).generate_document(ctx, system_prompt="system")

    assert generation.model_calls == 3
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.salvaged and generation.dropped["questions"] == ["x9"]
    assert generation.report.warnings == [], [w.model_dump() for w in generation.report.warnings]
    assert revalidate(generation.doc).ok
    doc = generation.doc
    assert "x9" not in {q["id"] for q in doc["questions"]}
    # The model's own story, fully translated.
    opening = real["story"]["opening"]
    assert any(s["type"] == "narrate" and s["en"] == opening["en"] for s in steps(doc))
    concepts = [s for s in steps(doc) if s["type"] == "concept"]
    assert concepts and all(s["en"] != s["fr"] for s in concepts)


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_an_attempt_the_model_repaired_beats_salvaging_the_one_before(raw, language):
    """Salvaging attempt 1 would drop x9; attempt 2 fixed it: attempt 2 is stored whole."""
    ctx = _with_course_misconceptions(make_ctx(raw, language))
    repaired = _spine_with_x9(raw, language)
    repaired["questions"][-1]["choices"][1]["misconception"] = "m_wrong_drug"
    repaired["misconceptions"] = [
        *repaired.get("misconceptions", []),
        {
            "id": "m_wrong_drug",
            "en": "Thinks any painkiller cures malaria.",
            "fr": "Croit que tout antidouleur guérit le paludisme.",
        },
    ]
    model = FakeClaude(_spine_with_x9(raw, language), repaired)
    generation = await StoryFromLessonService(model).generate_document(ctx, system_prompt="system")

    assert generation.model_calls == 2
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert not generation.salvaged and generation.dropped == {}
    assert generation.report.warnings == [], [w.model_dump() for w in generation.report.warnings]
    assert "x9" in {q["id"] for q in generation.doc["questions"]}


async def test_an_unreadable_answer_is_never_reported_as_a_malformed_spine(raw):
    """Even when building the story of no answer fails (a builder bug): ask for JSON again."""
    model = FakeClaude(_UNREADABLE, raw["en"]["spine"])
    with patch.object(repair, "build_story_document", side_effect=_raising_builder(1)):
        generation = await StoryFromLessonService(model).generate_document(
            make_ctx(raw, "en"), system_prompt="system"
        )
    assert "could not be read as JSON" in model.messages[1]
    assert "[malformed_spine]" not in model.messages[1]
    assert generation.report.ok and generation.model_calls == 2


class _UnreadableProvider:
    """A provider that always answers prose: never valid JSON."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, **kwargs: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(
            text="Sorry, here is the story in prose.", stop_reason="end_turn", usage={}
        )


async def test_each_attempt_is_exactly_one_paid_provider_call(raw):
    """The service's strict-JSON retry is off: the repair loop already re-asks."""
    from app.ai.claude_service import ClaudeService

    provider = _UnreadableProvider()
    claude = ClaudeService.__new__(ClaudeService)  # no settings or API key needed
    claude._max_tokens, claude._temperature, claude._model = 1000, 0.5, "stub"
    with patch.object(ClaudeService, "_provider", return_value=provider):
        generation = await StoryFromLessonService(claude).generate_document(
            make_ctx(raw, "en"), system_prompt="system"
        )
    budget = 1 + StoryFromLessonService(claude).max_repair_calls
    assert generation.model_calls == budget
    assert provider.calls == budget  # not 2 x budget
    assert not generation.report.ok


async def test_the_spine_call_turns_off_the_inner_json_retry(raw):
    seen: list[int] = []

    class Recording(FakeClaude):
        async def generate_structured_content(self, system, user, content_type, max_retries=1):
            seen.append(max_retries)
            return await super().generate_structured_content(system, user, content_type)

    await StoryFromLessonService(Recording(raw["en"]["spine"])).generate_document(
        make_ctx(raw, "en"), system_prompt="system"
    )
    assert seen == [0]
