"""Unit tests for the deterministic layer of lesson-story generation.

Each test pins one rule the builder enforces so the model does not have to:
the int-answer coercion that otherwise costs two validator errors, C2 line
lengths, the ``{child}`` placeholder, ask spacing, the catch mini-game shape,
image-only visuals, misconception declaration and the answer-leak guard.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.api.v1.schemas.story_course import StoryCourse, ValidationReport
from app.domain.services import story_repair as repair
from app.domain.services.story_course_validator import validate_story_course

FIXTURE = Path(__file__).parent / "fixtures" / "lesson_story_unit.json"
UNIT_ID = uuid.UUID("2f1e0d3c-4b5a-4968-8776-655443322110")


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_ctx(raw: dict[str, Any], language: str = "en", **overrides: Any):
    data = raw[language]
    mcqs, _ = repair.parse_quiz_mcqs(copy.deepcopy(data["quiz"]["questions"]))
    values = {
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


def spine_for(raw: dict[str, Any], language: str = "en") -> dict[str, Any]:
    return copy.deepcopy(raw[language]["spine"])


def validate(doc: dict[str, Any]) -> ValidationReport:
    return validate_story_course(StoryCourse.model_validate(doc))


def all_steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for c in doc["chapters"] for s in c["scenes"] for step in s["steps"]]


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_is_untouched(self):
        assert repair.truncate("Hello there", 100) == "Hello there"

    def test_cuts_at_a_word_boundary_within_the_limit(self):
        text = "word " * 40
        out = repair.truncate(text, 100)
        assert len(out) <= 100
        assert out.endswith("…")
        assert not out[:-1].endswith(" ")
        assert "wor…" not in out

    def test_never_splits_the_child_placeholder(self):
        text = "x" * 90 + " {child}, and a long tail that will be cut away"
        out = repair.truncate(text, 95)
        assert len(out) <= 95
        assert "{chi" not in out.replace("{child}", "")


def test_clean_text_strips_figures_and_markdown():
    text = "**Nets** work ⟦FIG1⟧ at [night](http://x) {{source_image:abc-123}}\n# Title"
    assert repair.clean_text(text) == "Nets work at night Title"


def test_slug_and_language_pair_follow_c8_and_c1():
    assert repair.story_slug(UNIT_ID, "fr") == f"lesson-{UNIT_ID.hex}-fr"
    assert repair.language_pair("fr") == {"target": "fr", "home": "en"}
    assert repair.language_pair("en") == {"target": "en", "home": "fr"}


# --------------------------------------------------------------------------
# Stored quiz MCQs
# --------------------------------------------------------------------------


class TestParseQuizMcqs:
    def test_keeps_valid_questions_with_sequential_refs(self, raw):
        mcqs, dropped = repair.parse_quiz_mcqs(raw["en"]["quiz"]["questions"])
        assert [m.ref for m in mcqs] == ["q1", "q2", "q3", "q4"]
        assert dropped == []
        assert mcqs[0].correct_index == 2

    def test_digit_string_correct_answer_is_coerced(self):
        mcqs, _ = repair.parse_quiz_mcqs(
            [
                {
                    "id": "a",
                    "question": "Pick one",
                    "options": ["w", "x", "y", "z"],
                    "correct_answer": "3",
                }
            ]
        )
        assert mcqs[0].correct_index == 3

    def test_duplicate_options_are_dropped_and_reported(self):
        mcqs, dropped = repair.parse_quiz_mcqs(
            [
                {
                    "id": "dup",
                    "question": "Which sign comes with measles?",
                    "options": ["Fever and rash", "fever  and RASH", "Cough", "Diarrhoea"],
                    "correct_answer": 0,
                }
            ]
        )
        assert mcqs == []
        assert dropped == [{"question": "dup", "reason": "duplicate_options"}]

    def test_correct_option_in_the_stem_is_dropped_and_reported(self):
        mcqs, dropped = repair.parse_quiz_mcqs(
            [
                {
                    "id": "leak",
                    "question": "Nets treated with insecticide protect at night. What protects at night?",
                    "options": ["Nets treated with insecticide", "Sun", "Rain", "Wind"],
                    "correct_answer": 0,
                }
            ]
        )
        assert mcqs == []
        assert dropped[0]["reason"] == "answer_in_stem"

    def test_malformed_questions_are_dropped(self):
        mcqs, dropped = repair.parse_quiz_mcqs(
            [
                {"id": "a", "question": "", "options": ["x", "y"], "correct_answer": 0},
                {"id": "b", "question": "Q?", "options": ["x", "y"], "correct_answer": 5},
                {"id": "c", "question": "Q?", "options": "x", "correct_answer": 0},
                "not a question",
            ]
        )
        assert mcqs == []
        assert len(dropped) == 4

    def test_option_misconceptions_are_kept_and_blank_at_the_answer(self):
        mcqs, _ = repair.parse_quiz_mcqs(
            [
                {
                    "id": "a",
                    "question": "Q?",
                    "options": ["w", "x", "y", "z"],
                    "correct_answer": 1,
                    "option_misconceptions": ["first", "ignored at answer", "", "fourth"],
                }
            ]
        )
        assert mcqs[0].option_misconceptions == ["first", None, None, "fourth"]


# --------------------------------------------------------------------------
# Answer coercion
# --------------------------------------------------------------------------


class TestAnswerCoercion:
    """An int answer must become the choice id, never stay a number.

    The design measured the naive mapping (``answer = correct_answer``): two
    errors, ``choice_answer_unresolved`` plus a spurious
    ``distractor_without_misconception`` on the right option.
    """

    @pytest.mark.parametrize("answer", [2, "2", "c", "C"])
    def test_extra_choice_answer_becomes_a_choice_id(self, raw, answer):
        spine = spine_for(raw)
        spine["questions"] = [
            {
                "id": "x9",
                "type": "choice",
                "objective": "o1",
                "prompt": {
                    "en": "Which tool works while people sleep?",
                    "fr": "Quel outil agit pendant le sommeil ?",
                },
                "choices": [
                    {"en": "A fan", "fr": "Un ventilateur", "misconception": "m_day_biting"},
                    {"en": "A torch", "fr": "Une lampe", "misconception": "m_day_biting"},
                    {"en": "A treated net", "fr": "Une moustiquaire imprégnée"},
                ],
                "answer": answer,
            }
        ]
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        question = next(q for q in doc["questions"] if q["id"] == "x9")
        assert question["answer"] == "c"
        assert "misconception" not in question["choices"][2]
        codes = {e.code for e in validate(doc).errors}
        assert "choice_answer_unresolved" not in codes
        assert "distractor_without_misconception" not in codes

    def test_naive_int_answer_would_have_failed(self, raw):
        """Guard the premise: the validator really rejects an int answer."""
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        question = doc["questions"][0]
        question["answer"] = 2
        question["choices"][2]["misconception"] = None
        codes = [e.code for e in validate(doc).errors if "questions[q1]" in e.path]
        assert "choice_answer_unresolved" in codes
        assert "distractor_without_misconception" in codes

    def test_distractor_given_by_index_maps_to_its_letter(self, raw):
        spine = spine_for(raw, "fr")  # its q1 names option b as the integer 1
        doc = repair.build_story_document(make_ctx(raw, "fr"), spine).doc
        q1 = next(q for q in doc["questions"] if q["id"] == "q1")
        assert q1["choices"][1]["misconception"] == "m_day_biting"
        assert any(t["answer"] == "b" for t in q1["traps"])


# --------------------------------------------------------------------------
# Learner is the hero, C1 and C2
# --------------------------------------------------------------------------


class TestStoryLines:
    def test_learner_is_the_child_placeholder(self, raw):
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        assert doc["learner"] == {"first_name": "{child}"}
        assert "gender" not in doc["learner"]

    @pytest.mark.parametrize("language", ["en", "fr"])
    def test_child_is_addressed_in_both_languages(self, raw, language):
        doc = repair.build_story_document(make_ctx(raw, language), {}).doc
        lines = [s for s in all_steps(doc) if s["type"] in ("narrate", "say")]
        assert any("{child}" in s["en"] for s in lines)
        assert any("{child}" in s["fr"] for s in lines)

    def test_every_story_line_is_capped_at_100_in_both_languages(self, raw):
        spine = spine_for(raw)
        long_en = "You walk " + "very " * 60 + "far, {child}."
        long_fr = "Tu marches " + "très " * 60 + "loin, {child}."
        for key in ("opening", "mentor_intro", "example_intro", "wrap_up"):
            spine["story"][key] = {"en": long_en, "fr": long_fr}
        spine["story"]["example_dialogue"] = [{"who": "peer", "en": long_en, "fr": long_fr}]
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        lines = [s for s in all_steps(doc) if s["type"] in ("narrate", "say")]
        truncated = [s for s in lines if s["en"].endswith("…")]
        assert truncated, "the long lines must have been cut"
        for step in lines:
            assert len(step["en"]) <= repair.STORY_LINE_LIMIT
            assert len(step["fr"]) <= repair.STORY_LINE_LIMIT
        assert validate(doc).ok

    def test_lines_are_language_keyed_for_a_french_target(self, raw):
        """C1: "en" holds English even when French is the target."""
        doc = repair.build_story_document(make_ctx(raw, "fr"), spine_for(raw, "fr")).doc
        assert doc["languages"] == {"target": "fr", "home": "en"}
        opener = all_steps(doc)[0]
        assert opener["en"] == "This story is about you, {child}."
        assert opener["fr"] == "Cette histoire parle de toi, {child}."
        key_points = next(
            s for s in all_steps(doc) if s["type"] == "concept" and s["title"]["en"] == "Key points"
        )
        # The French target rows are the lesson's own key points, verbatim.
        assert key_points["fr"] == raw["fr"]["lesson"]["key_points"]
        assert key_points["en"] == raw["fr"]["spine"]["key_points_home"]

    def test_ai_disclosure_is_added_to_every_intro_language(self, raw):
        spine = spine_for(raw)
        spine["tutor"]["intro"] = {
            "en": "Hi {child}, I'm Margo.",
            "fr": "Salut {child}, c'est Margo.",
        }
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        assert "AI" in doc["tutor"]["intro"]["en"]
        assert "IA" in doc["tutor"]["intro"]["fr"]
        assert doc["tutor"]["persona"] == "margo"
        margo = next(c for c in doc["cast"] if c["id"] == "margo")
        assert margo["kind"] == "ai_tutor" and margo["art"] == "margo"


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def _many_mcqs(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"s{n}",
            "question": f"Statement number {n}: which option is right?",
            "options": [f"Right {n}", f"Wrong A {n}", f"Wrong B {n}", f"Wrong C {n}"],
            "correct_answer": 0,
            "explanation": "Because.",
        }
        for n in range(1, count + 1)
    ]


class TestLayout:
    def test_never_more_than_two_asks_in_a_row(self, raw):
        mcqs, _ = repair.parse_quiz_mcqs(_many_mcqs(12))
        ctx = make_ctx(raw, mcqs=mcqs)
        ctx.lesson["concepts"] = []
        doc = repair.build_story_document(ctx, {}).doc
        run = longest = 0
        for step in all_steps(doc):
            run = run + 1 if step["type"] == "ask" else 0
            longest = max(longest, run)
        assert longest <= repair.MAX_ASKS_IN_A_ROW

    def test_every_question_is_asked_exactly_once(self, raw):
        mcqs, _ = repair.parse_quiz_mcqs(_many_mcqs(9))
        doc = repair.build_story_document(make_ctx(raw, mcqs=mcqs), {}).doc
        asked = [s["ref"] for s in all_steps(doc) if s["type"] == "ask"]
        assert sorted(asked) == sorted(q["id"] for q in doc["questions"])
        assert len(asked) == len(set(asked))

    def test_only_image_visuals_backed_by_a_lesson_figure(self, raw):
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        shows = [s for s in all_steps(doc) if s["type"] == "show"]
        assert len(shows) == 1
        assert shows[0]["visual"] == "image"
        assert shows[0]["params"]["source_image_id"] == "1b0d4c1e-7f3a-4a63-9a0e-2c51d1f0a001"
        assert shows[0]["caption"] == {
            "en": "When Anopheles mosquitoes bite",
            "fr": "Quand les anophèles piquent",
        }

    def test_no_show_step_without_a_figure(self, raw):
        doc = repair.build_story_document(make_ctx(raw, "fr"), spine_for(raw, "fr")).doc
        assert not [s for s in all_steps(doc) if s["type"] == "show"]

    def test_long_quiz_stem_moves_to_a_situation_step(self, raw):
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        q3 = next(q for q in doc["questions"] if q["id"] == "q3")
        assert q3["prompt"]["en"] == "Read the situation above, then choose the best answer."
        steps = all_steps(doc)
        index = next(i for i, s in enumerate(steps) if s.get("ref") == "q3")
        situation = steps[index - 1]
        assert situation["id"] == "situation-q3"
        assert situation["en"] == [raw["en"]["quiz"]["questions"][2]["question"]]

    def test_unknown_place_falls_back_to_the_catalog(self, raw):
        spine = spine_for(raw)
        spine["example"]["place"] = "hospital_ward"
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        places = {s["place"] for c in doc["chapters"] for s in c["scenes"]}
        assert "hospital_ward" not in places
        assert validate(doc).ok

    def test_week_course_and_unit_are_set(self, raw):
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        assert doc["format"] == "story-course/1"
        assert doc["id"] == f"lesson-{UNIT_ID.hex}-en"
        assert doc["week"] == 3
        assert doc["unit"] == "1.2 · Preventing malaria in children"


class TestMinigame:
    def test_catch_engine_with_items_rounds(self, raw):
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        (game,) = doc["minigames"]
        declared = {m["id"] for m in doc["misconceptions"]}
        assert game["engine"] == "catch"
        assert game["points"] == {"per_correct": 1}
        assert "rule" not in game
        for round_data in game["rounds"]:
            assert set(round_data) == {"prompt", "items"}
            assert set(round_data["prompt"]) == {"en", "fr"}
            assert any(item["correct"] for item in round_data["items"])
            for item in round_data["items"]:
                assert set(item["label"]) == {"en", "fr"}
                if item["correct"]:
                    assert "trap" not in item
                else:
                    assert item["trap"] in declared
        assert any(s["type"] == "game" and s["ref"] == game["id"] for s in all_steps(doc))

    def test_wrong_items_without_a_trap_and_rounds_without_a_target_are_dropped(self, raw):
        spine = spine_for(raw)
        spine["minigame"]["rounds"] = [
            {
                "items": [
                    {
                        "label": {"en": "Only wrong", "fr": "Faux"},
                        "correct": False,
                        "trap": "m_day_biting",
                    }
                ]
            },
            {
                "items": [
                    {"label": {"en": "True one", "fr": "Vrai"}, "correct": True},
                    {"label": {"en": "Untagged wrong", "fr": "Faux sans piège"}, "correct": False},
                ]
            },
        ]
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        rounds = doc["minigames"][0]["rounds"]
        assert len(rounds) == 1
        assert [i["label"]["en"] for i in rounds[0]["items"]] == ["True one"]
        report = validate(doc)
        assert report.ok and not report.warnings

    def test_falls_back_to_the_lesson_key_points(self, raw):
        doc = repair.build_story_document(make_ctx(raw), {}).doc
        (game,) = doc["minigames"]
        labels = [i["label"]["en"] for r in game["rounds"] for i in r["items"]]
        assert labels[0] == raw["en"]["lesson"]["key_points"][0]
        assert all(i["correct"] for r in game["rounds"] for i in r["items"])


class TestMisconceptions:
    def test_undeclared_reference_is_declared_from_its_option(self, raw):
        spine = spine_for(raw)
        spine["derived"][0]["distractors"][0]["misconception"] = "m_brand_new"
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        declared = {m["id"]: m for m in doc["misconceptions"]}
        assert "m_brand_new" in declared
        assert "In the morning" in declared["m_brand_new"]["en"]
        assert declared["m_brand_new"]["from_test"] is False
        assert validate(doc).ok

    def test_course_option_misconceptions_fill_in_for_the_model(self, raw):
        spine = spine_for(raw)
        q4 = next(d for d in spine["derived"] if d["ref"] == "q4")
        q4["distractors"] = []
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        question = next(q for q in doc["questions"] if q["id"] == "q4")
        texts = {m["id"]: m["en"] for m in doc["misconceptions"]}
        wrong = [c for c in question["choices"] if c["id"] != question["answer"]]
        assert [texts[c["misconception"]] for c in wrong] == [
            "Confuses SMC with school-age campaigns.",
            "Thinks only newborns are at risk.",
            "Confuses prevention with treatment.",
        ]

    def test_missing_misconception_is_left_for_the_repair_loop(self, raw):
        spine = spine_for(raw)
        spine["derived"][0]["distractors"] = []
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        codes = {(e.code, e.path) for e in validate(doc).errors}
        assert ("distractor_without_misconception", "questions[q1].choices[0]") in codes


class TestLeakGuard:
    def test_hint_naming_the_answer_is_dropped(self, raw):
        spine = spine_for(raw)
        spine["derived"][0]["hint"] = {"en": "The answer is at night.", "fr": "C'est la nuit."}
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        assert doc["questions"][0]["hints"] == []

    def test_trap_hint_naming_the_answer_drops_the_trap_not_the_misconception(self, raw):
        spine = spine_for(raw)
        spine["derived"][0]["distractors"][0]["hint"] = {
            "en": "No: at night!",
            "fr": "Non : la nuit !",
        }
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        q1 = doc["questions"][0]
        assert "a" not in {t["answer"] for t in q1["traps"]}
        assert q1["choices"][0]["misconception"] == "m_day_biting"

    def test_leaking_home_stem_falls_back_to_the_quiz_stem(self, raw):
        spine = spine_for(raw)
        spine["derived"][0]["prompt_home"] = "Les anophèles piquent-ils la nuit ?"
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        q1 = doc["questions"][0]
        assert (
            q1["prompt"]["fr"]
            == q1["prompt"]["en"]
            == raw["en"]["quiz"]["questions"][0]["question"]
        )

    def test_duplicate_home_options_fall_back_to_the_quiz_options(self, raw):
        spine = spine_for(raw)
        spine["derived"][0]["options_home"] = ["Le matin", "Le matin", "La nuit", "L'après-midi"]
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        q1 = doc["questions"][0]
        assert [c["fr"] for c in q1["choices"]] == raw["en"]["quiz"]["questions"][0]["options"]

    def test_extra_question_with_the_answer_in_its_prompt_is_dropped(self, raw):
        spine = spine_for(raw)
        spine["questions"] = [
            {
                "id": "x1",
                "type": "choice",
                "prompt": {
                    "en": "Treated nets: which tool is a treated net?",
                    "fr": "Quel outil ?",
                },
                "choices": [
                    {"en": "Treated net", "fr": "Moustiquaire"},
                    {"en": "Fan", "fr": "Ventilateur", "misconception": "m_day_biting"},
                ],
                "answer": "a",
            }
        ]
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        assert "x1" not in {q["id"] for q in doc["questions"]}

    def test_unsupported_question_types_are_dropped(self, raw):
        spine = spine_for(raw)
        spine["questions"] = [
            {
                "id": "x1",
                "type": "number",
                "prompt": {"en": "How many?", "fr": "Combien ?"},
                "answer": 4,
                "verify": {"fn": "calc", "args": ["2+2"]},
            }
        ]
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        assert "x1" not in {q["id"] for q in doc["questions"]}


class TestCoverage:
    def test_rebalances_so_each_objective_has_two_questions_and_an_exercise(self, raw):
        spine = spine_for(raw)
        for derived in spine["derived"]:
            derived["objective"] = "o1"
        spine["exercises"] = spine["exercises"][:1]
        doc = repair.build_story_document(make_ctx(raw), spine).doc
        report = validate(doc)
        assert report.ok
        assert not [
            w
            for w in report.warnings
            if w.code in ("thin_question_coverage", "no_exercise_for_objective")
        ]

    def test_uncoverable_objectives_are_merged(self, raw):
        spine = spine_for(raw)
        spine["objectives"].append({"id": "o3", "en": "Third", "fr": "Troisième"})
        spine["questions"] = []
        mcqs, _ = repair.parse_quiz_mcqs(_many_mcqs(3))
        doc = repair.build_story_document(make_ctx(raw, mcqs=mcqs), spine).doc
        # Three questions cannot give three — or two — objectives two each.
        assert len(doc["objectives"]) == 1
        assert {q["objective"] for q in doc["questions"]} == {"o1"}
        assert {e["objective"] for e in doc["exercises"]} == {"o1"}
        assert doc["tutor"]["scope"]["this_week"] == ["o1"]
        coverage = {"thin_question_coverage", "no_exercise_for_objective"}
        assert not [w for w in validate(doc).warnings if w.code in coverage]


def test_too_few_questions_is_not_publishable(raw):
    ctx = make_ctx(raw, mcqs=[], has_quiz=False)
    doc = repair.build_story_document(ctx, {}).doc
    report = repair.publishable(validate(doc), doc)
    assert not report.ok
    assert "too_few_questions" in {e.code for e in report.errors}


def test_implicated_items_reads_paths():
    from app.api.v1.schemas.story_course import ValidationIssue

    report = ValidationReport(
        ok=False,
        errors=[
            ValidationIssue(
                severity="error", code="x", path="questions[x2].choices[1]", message=""
            ),
            ValidationIssue(severity="error", code="x", path="exercises[E2].prompt.en", message=""),
            ValidationIssue(severity="error", code="x", path="minigames[g1].rounds[0]", message=""),
            ValidationIssue(severity="error", code="x", path="tutor.intro", message=""),
        ],
    )
    assert repair.implicated_items(report) == ({"x2"}, {"E2"}, True)


# --------------------------------------------------------------------------
# Model output in the wrong shape never raises (FC-3)
# --------------------------------------------------------------------------


def _x1(doc: dict[str, Any]) -> dict[str, Any]:
    return next(q for q in doc["questions"] if q["id"] == "x1")


class TestShapeHardening:
    def test_hints_given_as_one_object_are_one_hint(self, raw):
        spine = spine_for(raw)
        spine["questions"][0]["hints"] = {"en": "It is most people.", "fr": "La plupart."}
        build = repair.build_story_document(make_ctx(raw), spine)
        assert _x1(build.doc)["hints"] == [{"en": "It is most people.", "fr": "La plupart."}]
        assert build.issues == []

    def test_hints_given_as_a_string_are_one_hint_with_a_missing_translation(self, raw):
        spine = spine_for(raw)
        spine["questions"][0]["hints"] = "It is most of the people."
        build = repair.build_story_document(make_ctx(raw), spine)
        assert _x1(build.doc)["hints"] == [
            {"en": "It is most of the people.", "fr": "It is most of the people."}
        ]
        assert [(i.code, i.path) for i in build.issues] == [
            ("missing_translation", "questions[x1].hints[0]")
        ]

    @pytest.mark.parametrize("value", [7, None, True, 2.5])
    def test_hints_of_no_usable_shape_are_no_hints(self, raw, value):
        spine = spine_for(raw)
        spine["questions"][0]["hints"] = value
        assert _x1(repair.build_story_document(make_ctx(raw), spine).doc)["hints"] == []

    WRONG = [{}, {"en": "x"}, "text", 7, None, True, [1, "two", None, {}]]

    @pytest.mark.parametrize("value", WRONG)
    @pytest.mark.parametrize(
        "where",
        [
            ("objectives",),
            ("misconceptions",),
            ("characters",),
            ("chapter_titles",),
            ("story",),
            ("story", "example_dialogue"),
            ("concepts",),
            ("example",),
            ("key_points_home",),
            ("derived",),
            ("derived", 0, "distractors"),
            ("derived", 0, "options_home"),
            ("derived", 0, "hint"),
            ("questions",),
            ("questions", 0, "traps"),
            ("questions", 0, "choices"),
            ("exercises",),
            ("exercises", 0, "working"),
            ("minigame",),
            ("minigame", "rounds"),
            ("minigame", "rounds", 0, "items"),
            ("tutor",),
        ],
        ids=lambda w: ".".join(map(str, w)) if isinstance(w, tuple) else None,
    )
    def test_any_field_in_any_wrong_shape_still_builds(self, raw, where, value):
        spine = spine_for(raw)
        target = spine
        for key in where[:-1]:
            target = target[key]
        target[where[-1]] = copy.deepcopy(value)
        build = repair.build_story_document(make_ctx(raw), spine)
        StoryCourse.model_validate(build.doc)  # still a story-course/1 document

    @pytest.mark.parametrize("spine", [None, [], "spine", 7, {"derived": {"q1": {}}}])
    def test_a_spine_that_is_not_an_object_still_builds(self, raw, spine):
        StoryCourse.model_validate(repair.build_story_document(make_ctx(raw), spine).doc)


# --------------------------------------------------------------------------
# Copy-fallbacks are recorded, never silent (FC-6)
# --------------------------------------------------------------------------


def _issue_paths(build: repair.StoryBuild) -> set[str]:
    assert all(i.code == "missing_translation" for i in build.issues)
    return {i.path for i in build.issues}


class TestMissingTranslations:
    @pytest.mark.parametrize("language", ["en", "fr"])
    def test_a_well_behaved_spine_records_nothing(self, raw, language):
        build = repair.build_story_document(make_ctx(raw, language), spine_for(raw, language))
        assert build.issues == []

    def test_text_object_records_a_copy_only_with_a_path_inside_a_build(self):
        assert repair.text_object({"en": "Hi"}, path="x") == {"en": "Hi", "fr": "Hi"}
        token = repair._SINK.set(repair._Translations())
        try:
            repair.text_object({"en": "Hi"}, path="objectives[0]")
            repair.text_object({"en": "Hi"})  # lesson data: no path, nothing recorded
            repair.text_object({"en": "Hi", "fr": "Salut"}, path="ok")
            issues = repair._SINK.get().issues
        finally:
            repair._SINK.reset(token)
        assert [(i.code, i.path) for i in issues] == [("missing_translation", "objectives[0].fr")]

    def test_objective_without_its_french(self, raw):
        spine = spine_for(raw)
        spine["objectives"][0].pop("fr")
        build = repair.build_story_document(make_ctx(raw), spine)
        assert _issue_paths(build) == {"objectives[0].fr"}
        # The copy is still made: the story keeps both keys.
        assert build.doc["objectives"][0]["fr"] == build.doc["objectives"][0]["en"]

    def test_story_line_without_its_english_on_a_french_story(self, raw):
        spine = spine_for(raw, "fr")
        spine["story"]["opening"].pop("en")
        build = repair.build_story_document(make_ctx(raw, "fr"), spine)
        assert _issue_paths(build) == {"story.opening.en"}

    @pytest.mark.parametrize(
        ("field", "value", "path"),
        [
            ("options_home", None, "derived[q1].options_home"),
            ("options_home", ["Le matin", "À midi"], "derived[q1].options_home"),
            (
                "options_home",
                ["Le matin", "Le matin", "La nuit", "Jamais"],
                "derived[q1].options_home",
            ),
            ("prompt_home", None, "derived[q1].prompt_home"),
            ("prompt_home", "Les anophèles piquent-ils la nuit ?", "derived[q1].prompt_home"),
            ("explanation_home", None, "derived[q1].explanation_home"),
        ],
        ids=[
            "no-options",
            "too-few",
            "duplicates",
            "no-prompt",
            "leaking-prompt",
            "no-explanation",
        ],
    )
    def test_home_side_of_a_derived_question(self, raw, field, value, path):
        spine = spine_for(raw)
        if value is None:
            spine["derived"][0].pop(field)
        else:
            spine["derived"][0][field] = value
        assert _issue_paths(repair.build_story_document(make_ctx(raw), spine)) == {path}

    def test_course_misconception_copied_for_a_wrong_option(self, raw):
        spine = spine_for(raw)
        next(d for d in spine["derived"] if d["ref"] == "q4")["distractors"] = []
        paths = _issue_paths(repair.build_story_document(make_ctx(raw), spine))
        assert paths == {
            f"derived[q4].distractors[{letter}].misconception.fr" for letter in ("b", "c", "d")
        }

    def test_key_points_without_their_translation(self, raw):
        spine = spine_for(raw)
        spine["key_points_home"] = spine["key_points_home"][:1]
        assert _issue_paths(repair.build_story_document(make_ctx(raw), spine)) == {
            "key_points_home"
        }

    def test_concepts_fall_back_to_the_lessons_own_prose(self, raw):
        spine = spine_for(raw)
        spine["concepts"] = []
        assert _issue_paths(repair.build_story_document(make_ctx(raw), spine)) == {"concepts"}

    def test_concept_rows_missing_one_language(self, raw):
        spine = spine_for(raw)
        spine["concepts"][1]["fr"] = []
        assert _issue_paths(repair.build_story_document(make_ctx(raw), spine)) == {"concepts[1].fr"}

    def test_example_falls_back_to_the_lessons_own(self, raw):
        spine = spine_for(raw)
        spine["example"].pop("en")
        spine["example"].pop("fr")
        assert _issue_paths(repair.build_story_document(make_ctx(raw), spine)) == {"example"}

    def test_a_dropped_extra_question_reports_nothing(self, raw):
        spine = spine_for(raw)
        spine["questions"].append(
            {
                "id": "x9",
                "type": "choice",
                "prompt": {"en": "Is the answer Yes?"},  # leaks its answer: dropped
                "choices": [{"id": "a", "en": "Yes"}, {"id": "b", "en": "No"}],
                "answer": "a",
            }
        )
        build = repair.build_story_document(make_ctx(raw), spine)
        assert "x9" not in {q["id"] for q in build.doc["questions"]}
        assert build.issues == []

    def test_unused_misconceptions_report_nothing(self, raw):
        spine = spine_for(raw)
        spine["misconceptions"].append({"id": "m_unused", "en": "Never used."})
        assert repair.build_story_document(make_ctx(raw), spine).issues == []

    def test_an_objective_merged_away_reports_nothing(self, raw):
        """No question covers a third objective: it is merged away, and so is its copy."""
        spine = spine_for(raw)
        spine["objectives"].append({"id": "o9", "en": "Know a third thing about nets"})
        build = repair.build_story_document(make_ctx(raw), spine)
        assert [o["id"] for o in build.doc["objectives"]] == ["o1", "o2"]
        assert "Know a third thing about nets" not in json.dumps(build.doc)
        assert build.issues == []

    def test_a_kept_objective_still_reports_its_copy(self, raw):
        spine = spine_for(raw)
        spine["objectives"][1].pop("fr")
        spine["objectives"].append({"id": "o9", "en": "Know a third thing about nets"})
        build = repair.build_story_document(make_ctx(raw), spine)
        assert [o["id"] for o in build.doc["objectives"]] == ["o1", "o2"]
        assert _issue_paths(build) == {"objectives[1].fr"}

    @staticmethod
    def _without_an_example(raw):
        spine = spine_for(raw)
        spine.pop("example")
        ctx = make_ctx(raw)
        ctx.lesson.pop("aof_example", None)
        return ctx, spine

    def test_example_lines_of_a_story_without_an_example_report_nothing(self, raw):
        ctx, spine = self._without_an_example(raw)
        spine["story"]["example_intro"].pop("fr")
        spine["story"]["example_dialogue"][0].pop("fr")
        build = repair.build_story_document(ctx, spine)
        shown = json.dumps(build.doc, ensure_ascii=False)
        assert spine["story"]["example_intro"]["en"][:40] not in shown
        assert build.issues == []
        # The lines the story does show are still reported.
        spine["story"]["opening"].pop("fr")
        assert _issue_paths(repair.build_story_document(ctx, spine)) == {"story.opening.fr"}

    def test_example_lines_shown_in_the_field_scene_are_reported(self, raw):
        spine = spine_for(raw)
        spine["story"]["example_intro"].pop("fr")
        build = repair.build_story_document(make_ctx(raw), spine)
        assert _issue_paths(build) == {"story.example_intro.fr"}

    def test_a_chapter_the_layout_never_opens_reports_nothing(self, raw):
        ctx, spine = self._without_an_example(raw)
        spine["concepts"] = spine["concepts"][:1]  # one concept: chapter 2 is never opened
        spine["chapter_titles"][1] = {"en": "Out in the field"}
        build = repair.build_story_document(ctx, spine)
        assert "Out in the field" not in json.dumps(build.doc)
        assert build.issues == []
        spine["chapter_titles"][2] = {"en": "Over to you"}
        assert _issue_paths(repair.build_story_document(ctx, spine)) == {"chapter_titles[2].fr"}

    def test_settling_turns_copies_into_warnings_and_keeps_other_errors(self):
        from app.api.v1.schemas.story_course import Checks, ValidationIssue

        def issue(code):
            return ValidationIssue(severity="error", code=code, path="p", message="m")

        report = ValidationReport(
            ok=False,
            errors=[issue("missing_translation"), issue("missing_translation")],
            checks=Checks(errors=2),
        )
        settled = repair.settle_translations(report)
        assert settled.ok and settled.errors == []
        assert [w.severity for w in settled.warnings] == ["warning", "warning"]
        assert (settled.checks.errors, settled.checks.warnings) == (0, 2)
        mixed = repair.settle_translations(
            report.model_copy(update={"errors": [*report.errors, issue("answer_leak")]})
        )
        assert not mixed.ok and [e.code for e in mixed.errors] == ["answer_leak"]


# --------------------------------------------------------------------------
# X5: a long quiz stem keeps the lead-in, the situation step and a ``stem``
# --------------------------------------------------------------------------


class TestLongStem:
    @pytest.mark.parametrize("language", ["en", "fr"])
    def test_question_carries_the_verbatim_stem(self, raw, language):
        doc = repair.build_story_document(make_ctx(raw, language), spine_for(raw, language)).doc
        q3 = next(q for q in doc["questions"] if q["id"] == "q3")
        stored = raw[language]["quiz"]["questions"][2]["question"]
        home = "en" if language == "fr" else "fr"
        home_stem = next(d for d in spine_for(raw, language)["derived"] if d["ref"] == "q3")[
            "prompt_home"
        ]
        assert q3["stem"] == {language: stored, home: home_stem}
        assert q3["prompt"][language] != stored  # the generic lead-in
        steps = all_steps(doc)
        index = next(i for i, s in enumerate(steps) if s.get("ref") == "q3")
        assert steps[index - 1]["id"] == "situation-q3"
        assert steps[index - 1][language] == [stored]

    def test_short_stems_have_no_stem_field(self, raw):
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        assert [q["id"] for q in doc["questions"] if "stem" in q] == ["q3"]

    def test_fidelity_restores_an_edited_stem(self, raw):
        ctx = make_ctx(raw)
        doc = repair.build_story_document(ctx, spine_for(raw)).doc
        q3 = next(q for q in doc["questions"] if q["id"] == "q3")
        q3["stem"]["en"] = "edited"
        repair.enforce_quiz_fidelity(doc, ctx)
        assert q3["stem"]["en"] == raw["en"]["quiz"]["questions"][2]["question"]

    @pytest.mark.parametrize("lang", ["en", "fr"])
    def test_a_stem_giving_the_answer_away_is_an_error(self, raw, lang):
        doc = repair.build_story_document(make_ctx(raw), spine_for(raw)).doc
        q3 = next(q for q in doc["questions"] if q["id"] == "q3")
        correct = next(c for c in q3["choices"] if c["id"] == q3["answer"])
        q3["stem"][lang] += f" Hint: {correct[lang]}"
        report = repair.publishable(validate(doc), doc)
        assert ("answer_leak", f"questions[q3].stem.{lang}") in {
            (e.code, e.path) for e in report.errors
        }
        assert repair.implicated_items(report)[0] == {"q3"}
