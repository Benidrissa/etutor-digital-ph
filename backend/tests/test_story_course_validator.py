"""Tests for the ``story-course/1`` validator (format Appendix C).

The golden test is that the shipped Week 4 example validates clean. Everything
else deliberately breaks one thing in that example and asserts the matching
error code fires, because a validator that only ever says "ok" is worse than
no validator: it would wave through course files a child then works from.
"""

import copy
import json
from pathlib import Path

import pytest

from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services.story_course_validator import validate_story_course

FIXTURE = Path(__file__).parent / "fixtures" / "story_course_w04.json"
TIMES = "×"


@pytest.fixture(scope="module")
def raw_course() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def course(raw_course: dict) -> dict:
    """A fresh, independent copy of the valid example for each test."""
    return copy.deepcopy(raw_course)


def validate(data: dict):
    return validate_story_course(StoryCourse.model_validate(data))


def codes(data: dict) -> set[str]:
    report = validate(data)
    return {issue.code for issue in report.errors}


def warning_codes(data: dict) -> set[str]:
    report = validate(data)
    return {issue.code for issue in report.warnings}


def find(items: list[dict], key: str, value: str) -> dict:
    return next(item for item in items if item[key] == value)


class TestGoldenExample:
    """The shipped example must stay publishable: zero errors."""

    def test_validates_clean(self, course):
        report = validate(course)
        assert report.errors == [], [e.model_dump() for e in report.errors]
        assert report.warnings == [], [w.model_dump() for w in report.warnings]
        assert report.ok is True

    def test_checks_block_is_computed(self, course):
        checks = validate(course).checks
        assert checks.questions == 7
        assert checks.exercises == 3
        assert checks.paper_marks == 6  # A1(1) + C1(3) + D1(2)
        assert checks.minigame_rounds == 3
        # 7 questions x 2 first-try + 6 paper marks + 9 prime targets
        assert checks.max_points == 29
        assert checks.errors == 0
        assert checks.predicted_typical["points"] == 24

    def test_parses_photo_check_copy_alias(self, course):
        parsed = StoryCourse.model_validate(course)
        assert find(course["exercises"], "id", "D1")["photo_check"]["copy"] == "division_ladder"
        d1 = next(e for e in parsed.exercises if e.id == "D1")
        assert d1.photo_check.copy_shape == "division_ladder"


class TestStructure:
    """Appendix C.1."""

    def test_duplicate_id(self, course):
        course["questions"].append(copy.deepcopy(course["questions"][0]))
        assert "duplicate_id" in codes(course)

    def test_dangling_question_ref(self, course):
        course["chapters"][0]["scenes"][0]["steps"][3]["ref"] = "q99"
        assert "dangling_ref" in codes(course)

    def test_unknown_speaker(self, course):
        course["chapters"][0]["scenes"][0]["steps"][0]["who"] = "tonton"
        assert "unknown_speaker" in codes(course)

    def test_unknown_visual_without_art_request(self, course):
        course["chapters"][0]["scenes"][0]["steps"][1]["visual"] = "spiral_of_primes"
        assert "unknown_visual" in codes(course)

    def test_unknown_visual_is_allowed_when_declared(self, course):
        """C.1 lets a new visual through if art_requests declares it."""
        course["chapters"][0]["scenes"][0]["steps"][1]["visual"] = "spiral_of_primes"
        course["art_requests"] = [
            {"name": "spiral_of_primes", "kind": "visual", "description": "Ulam spiral"}
        ]
        assert "unknown_visual" not in codes(course)

    def test_unknown_place(self, course):
        course["chapters"][0]["scenes"][0]["place"] = "spaceship"
        assert "unknown_place" in codes(course)

    def test_unknown_engine(self, course):
        course["minigames"][0]["engine"] = "tetris"
        assert "unknown_engine" in codes(course)

    def test_unknown_engine_allowed_when_declared(self, course):
        course["minigames"][0]["engine"] = "sort_it"
        course["engine_requests"] = [{"engine": "sort_it", "rules": "drag into order"}]
        assert "unknown_engine" not in codes(course)

    def test_dangling_objective(self, course):
        find(course["questions"], "id", "q1")["objective"] = "o9"
        assert "dangling_objective" in codes(course)

    def test_dangling_misconception(self, course):
        find(course["questions"], "id", "q3")["traps"][0]["misconception"] = "m_nope"
        assert "dangling_misconception" in codes(course)

    def test_unknown_art_key(self, course):
        find(course["cast"], "id", "nandi")["art"] = "nandi_in_a_spacesuit"
        assert "unknown_art" in codes(course)

    def test_minigame_is_required(self, course):
        course["minigames"] = []
        assert "missing_minigame" in codes(course)


class TestAnswers:
    """Appendix C.2 — the answers are recomputed, never trusted."""

    def test_answer_mismatch_is_caught(self, course):
        find(course["questions"], "id", "q3")["answer"] = f"2² {TIMES} 3² {TIMES} 5"
        assert "answer_mismatch" in codes(course)

    def test_wrong_hcf_is_caught(self, course):
        find(course["questions"], "id", "q5")["answer"] = 6
        assert "answer_mismatch" in codes(course)

    def test_wrong_rounding_is_caught(self, course):
        find(course["questions"], "id", "q7")["answer"] = "0.05"
        assert "answer_mismatch" in codes(course)

    def test_trap_equal_to_answer(self, course):
        q3 = find(course["questions"], "id", "q3")
        q3["traps"][0]["answer"] = q3["answer"]
        assert "trap_equals_answer" in codes(course)

    def test_trap_without_misconception(self, course):
        find(course["questions"], "id", "q3")["traps"][0].pop("misconception")
        assert "trap_without_misconception" in codes(course)

    def test_distractor_without_misconception(self, course):
        """Wrong choices are traps, never random distractors."""
        q1 = find(course["questions"], "id", "q1")
        find(q1["choices"], "id", "b").pop("misconception")
        assert "distractor_without_misconception" in codes(course)

    def test_choice_answer_must_name_one_option(self, course):
        find(course["questions"], "id", "q1")["answer"] = "z"
        assert "choice_answer_unresolved" in codes(course)

    def test_part_marks_must_add_up(self, course):
        find(course["exercises"], "id", "C1")["marks"] = 5
        assert "marks_mismatch" in codes(course)

    def test_require_index_rejects_expanded_answer(self, course):
        q3 = find(course["questions"], "id", "q3")
        expanded = f"2 {TIMES} 2 {TIMES} 2 {TIMES} 3 {TIMES} 3 {TIMES} 5"
        q3["answer"] = expanded
        q3["traps"] = [
            {
                "answer": "2³ × 3 × 5",
                "misconception": "m_lost_factor",
                "hint": {"en": "Multiply back and check.", "fr": "Remultiplie et vérifie."},
            }
        ]
        found = codes(course)
        # Caught twice over: the engine disagrees, and require_index is violated.
        assert "answer_not_index_form" in found
        assert "answer_mismatch" in found

    def test_unknown_engine_function(self, course):
        find(course["questions"], "id", "q5")["verify"] = {"fn": "surface_area", "args": [3]}
        assert "unknown_engine_fn" in codes(course)

    def test_requested_engine_function_only_warns(self, course):
        q5 = find(course["questions"], "id", "q5")
        q5["verify"] = {"fn": "surface_area", "args": [3]}
        course["engine_requests"] = [{"engine": "surface_area", "rules": "cone"}]
        assert "unknown_engine_fn" not in codes(course)
        assert "engine_requested" in warning_codes(course)


class TestLanguagesAndLengths:
    """Appendix C.3."""

    def test_missing_language_in_text_object(self, course):
        find(course["questions"], "id", "q3")["prompt"].pop("fr")
        assert "missing_language" in codes(course)

    def test_missing_language_in_story_line(self, course):
        course["chapters"][0]["scenes"][0]["steps"][0].pop("fr")
        assert "missing_language" in codes(course)

    def test_story_line_too_long(self, course):
        course["chapters"][0]["scenes"][0]["steps"][0]["en"] = "x" * 101
        assert "too_long" in codes(course)

    def test_question_prompt_too_long(self, course):
        find(course["questions"], "id", "q3")["prompt"]["en"] = "x" * 161
        assert "too_long" in codes(course)

    def test_hint_too_long(self, course):
        find(course["questions"], "id", "q3")["hints"][0]["en"] = "x" * 141
        assert "too_long" in codes(course)

    def test_long_explanation_is_allowed(self, course):
        """A.2 limits story lines, prompts and hints — not explanations."""
        find(course["questions"], "id", "q3")["explanation"]["en"] = "x" * 400
        assert "too_long" not in codes(course)

    def test_concept_rows_must_match_across_languages(self, course):
        concept = course["chapters"][0]["scenes"][0]["steps"][2]
        concept["fr"].pop()
        assert "unequal_rows" in codes(course)

    def test_working_lines_must_match_across_languages(self, course):
        find(course["exercises"], "id", "D1")["working"]["fr"].pop()
        assert "unequal_rows" in codes(course)


class TestNoLeaks:
    """Appendix C.4 — the answer never appears before she answers."""

    def test_answer_in_prompt(self, course):
        q3 = find(course["questions"], "id", "q3")
        q3["prompt"]["en"] = f"Write 360 as 2³ {TIMES} 3² {TIMES} 5 in index form."
        assert "answer_leak" in codes(course)

    def test_answer_in_hint(self, course):
        q3 = find(course["questions"], "id", "q3")
        q3["hints"][0]["fr"] = f"La réponse est 2³ {TIMES} 3² {TIMES} 5."
        assert "answer_leak" in codes(course)

    def test_short_numeric_answers_are_not_flagged(self, course):
        """A bare "12" in a prompt is innocent; flagging it trains authors to
        ignore the check."""
        q5 = find(course["questions"], "id", "q5")
        q5["prompt"]["en"] = "Find the HCF of 24 and 36, which is under 12 tens."
        assert "answer_leak" not in codes(course)


def _wordy_choice_question(course: dict) -> dict:
    """Give q1 options long enough to be leak-checked (the shipped ones are
    one- and two-digit numbers, which sit under the leak-length floor)."""
    q1 = find(course["questions"], "id", "q1")
    words = {
        "a": ("one", "un"),
        "b": ("nine", "neuf"),
        "c": ("thirteen", "treize"),
        "d": ("twenty-one", "vingt et un"),
    }
    for choice in q1["choices"]:
        choice["en"], choice["fr"] = words[choice["id"]]
    return q1


class TestChoiceQuestionsSharedMcqChecks:
    """The shared MCQ rules (``mcq_checks``) run on choice questions.

    ``_assert_no_leak`` builds its needle from ``answer``, which for a choice
    question is the choice id — so pasting the correct option's *text* into the
    prompt used to validate clean.
    """

    def test_wordy_choices_still_validate_clean(self, course):
        _wordy_choice_question(course)
        report = validate(course)
        assert report.errors == [], [e.model_dump() for e in report.errors]
        assert report.warnings == [], [w.model_dump() for w in report.warnings]

    def test_correct_choice_text_in_prompt_is_a_leak(self, course):
        q1 = _wordy_choice_question(course)
        q1["prompt"]["en"] = "Thirteen is prime. Which of these is a prime number?"
        report = validate(course)
        leaks = [e for e in report.errors if e.code == "answer_leak"]
        assert [e.path for e in leaks] == ["questions[q1].prompt.en"]
        assert report.ok is False

    def test_a_distractor_named_in_passing_is_a_warning(self, course):
        """ "one" (three letters) counts as a named distractor, so the English
        prompt is for a person to judge; "un" is under the leak floor, so the
        French prompt names the answer alone and is an error."""
        q1 = _wordy_choice_question(course)
        q1["prompt"] = {
            "en": "Thirteen is prime. Which one of these is a prime number?",
            "fr": "Treize est un nombre premier. Lequel de ces nombres est un nombre premier ?",
        }
        report = validate(course)
        assert [e.path for e in report.errors if e.code == "answer_leak"] == [
            "questions[q1].prompt.fr"
        ]
        assert [w.path for w in report.warnings if w.code == "answer_leak_ambiguous"] == [
            "questions[q1].prompt.en"
        ]

    def test_a_hint_naming_a_distractor_then_the_answer_is_a_warning(self, course):
        q1 = _wordy_choice_question(course)
        q1["hints"] = [
            {
                "en": "Nine is 3 × 3, so the prime one is thirteen.",
                "fr": "Neuf = 3 × 3, donc le nombre premier est treize.",
            }
        ]
        report = validate(course)
        assert "answer_leak" not in {e.code for e in report.errors}
        assert sorted(w.path for w in report.warnings if w.code == "answer_leak_ambiguous") == [
            "questions[q1].hints[0].en",
            "questions[q1].hints[0].fr",
        ]

    def test_correct_choice_text_in_hint_is_a_leak(self, course):
        q1 = _wordy_choice_question(course)
        q1["hints"] = [{"en": "Try the odd ones.", "fr": "Regarde treize de près."}]
        leaks = [e for e in validate(course).errors if e.code == "answer_leak"]
        assert [e.path for e in leaks] == ["questions[q1].hints[0].fr"]

    def test_a_distractor_in_the_prompt_is_not_a_leak(self, course):
        q1 = _wordy_choice_question(course)
        q1["prompt"]["en"] = "Nine is not prime. Which one of these is a prime number?"
        assert "answer_leak" not in codes(course)

    def test_an_either_or_prompt_and_hint_are_warnings_not_errors(self, course):
        """Naming the answer next to a distractor may compare them: the story
        stays publishable and the prompt is flagged for a person to read."""
        q1 = _wordy_choice_question(course)
        q1["prompt"] = {
            "en": "Which is prime: nine or thirteen?",
            "fr": "Lequel est premier : neuf ou treize ?",
        }
        q1["hints"] = [
            {"en": "Divide nine and thirteen by 3.", "fr": "Divise neuf et treize par 3."}
        ]
        report = validate(course)
        assert report.errors == [], [e.model_dump() for e in report.errors]
        assert report.ok is True
        assert sorted(w.path for w in report.warnings if w.code == "answer_leak_ambiguous") == [
            "questions[q1].hints[0].en",
            "questions[q1].hints[0].fr",
            "questions[q1].prompt.en",
            "questions[q1].prompt.fr",
        ]

    def test_an_either_or_prompt_with_repeated_prepositions_is_publishable(self, course):
        """ "in children or in adults", "chez les enfants ou chez les adultes":
        once hard errors that made the story unpublishable."""
        q1 = find(course["questions"], "id", "q1")
        words = {
            "a": ("adults", "adultes"),
            "b": ("the elderly", "personnes âgées"),
            "c": ("children", "enfants"),
            "d": ("newborns", "nouveau-nés"),
        }
        for choice in q1["choices"]:
            choice["en"], choice["fr"] = words[choice["id"]]
        q1["prompt"] = {
            "en": "Is this disease more severe in children or in adults?",
            "fr": "Cette maladie est-elle plus grave chez les enfants ou chez les adultes ?",
        }
        report = validate(course)
        assert report.errors == [], [e.model_dump() for e in report.errors]
        assert report.ok is True
        assert sorted(w.path for w in report.warnings if w.code == "answer_leak_ambiguous") == [
            "questions[q1].prompt.en",
            "questions[q1].prompt.fr",
        ]

    def test_a_factorised_either_or_prompt_is_publishable(self, course):
        """ "9 or 13 cm" writes the unit once for both choices: "9" names the
        distractor "9 cm", so the prompt is a warning, not an unpublishable leak."""
        q1 = find(course["questions"], "id", "q1")
        for choice in q1["choices"]:
            choice["en"] = choice["fr"] = f"{choice['en']} cm"
        q1["prompt"] = {
            "en": "Is the side 9 or 13 cm long?",
            "fr": "Le côté mesure-t-il 9 ou 13 cm ?",
        }
        report = validate(course)
        assert report.errors == [], [e.model_dump() for e in report.errors]
        assert report.ok is True
        assert sorted(w.path for w in report.warnings if w.code == "answer_leak_ambiguous") == [
            "questions[q1].prompt.en",
            "questions[q1].prompt.fr",
        ]

    def test_a_hint_naming_only_the_answer_still_leaks_beside_a_comparison_prompt(self, course):
        q1 = _wordy_choice_question(course)
        q1["prompt"]["en"] = "Which is prime: nine or thirteen?"
        q1["hints"] = [{"en": "It is thirteen.", "fr": "Regarde bien."}]
        leaks = [e for e in validate(course).errors if e.code == "answer_leak"]
        assert [e.path for e in leaks] == ["questions[q1].hints[0].en"]

    def test_duplicate_choice_text(self, course):
        q1 = _wordy_choice_question(course)
        find(q1["choices"], "id", "d")["en"] = "thirteen."
        report = validate(course)
        dup = [e for e in report.errors if e.code == "duplicate_options"]
        assert [e.path for e in dup] == ["questions[q1].choices[3].en"]

    def test_short_answers_add_no_warning(self, course):
        """The shipped q1 answer is "13": too short to leak-check, and the
        "unchecked" note stays out of the report so the example stays clean."""
        assert "leak_unchecked_short_answer" not in warning_codes(course)


class TestFrenchTargetLanguageKeying:
    """``en``/``fr`` on narrate/say/concept steps are language-keyed (C1).

    A French-target story still keeps its French text in ``fr``. Reading the
    fields positionally (``en`` = target) would check the French line against
    the English length limit and report a missing English line as missing
    French.
    """

    @pytest.fixture
    def fr_course(self, course):
        course["languages"] = {"target": "fr", "home": "en"}
        return course

    def test_french_target_example_validates_clean(self, fr_course):
        report = validate(fr_course)
        assert report.errors == [], [e.model_dump() for e in report.errors]
        assert report.warnings == [], [w.model_dump() for w in report.warnings]

    def test_french_line_gets_the_french_length_limit(self, fr_course):
        """110 characters is inside French's 118 but over English's 100."""
        fr_course["chapters"][0]["scenes"][0]["steps"][0]["fr"] = "é" * 110
        assert "too_long" not in codes(fr_course)

    def test_english_line_gets_the_english_length_limit(self, fr_course):
        fr_course["chapters"][0]["scenes"][0]["steps"][0]["en"] = "x" * 101
        report = validate(fr_course)
        too_long = [e for e in report.errors if e.code == "too_long"]
        assert [e.path for e in too_long] == ["chapters[ch1].scenes[s1].steps[0].en"]

    def test_missing_line_is_reported_under_its_own_language(self, fr_course):
        fr_course["chapters"][0]["scenes"][0]["steps"][0].pop("fr")
        report = validate(fr_course)
        missing = [e for e in report.errors if e.code == "missing_language"]
        assert [e.path for e in missing] == ["chapters[ch1].scenes[s1].steps[0].fr"]

    def test_concept_rows_are_keyed_by_language(self, fr_course):
        concept = fr_course["chapters"][0]["scenes"][0]["steps"][2]
        concept.pop("fr")
        report = validate(fr_course)
        missing = [e for e in report.errors if e.code == "missing_language"]
        assert [e.path for e in missing] == ["chapters[ch1].scenes[s1].steps[2].fr"]

    def test_english_target_line_still_keyed_the_same_way(self, course):
        """Unchanged for the shipped English-target example."""
        course["chapters"][0]["scenes"][0]["steps"][0]["fr"] = "é" * 110
        assert "too_long" not in codes(course)


class TestSpreadAndCoverage:
    """Appendix C.5."""

    def test_question_never_asked(self, course):
        course["questions"].append(
            {
                "id": "q99",
                "type": "number",
                "objective": "o1",
                "prompt": {"en": "What is 2 + 2?", "fr": "Combien font 2 + 2 ?"},
                "answer": 4,
                "verify": {"fn": "calc", "args": ["2 + 2"]},
            }
        )
        assert "question_never_asked" in codes(course)

    def test_more_than_three_questions_in_a_row(self, course):
        rally = course["chapters"][2]["scenes"][1]
        rally["steps"] = [
            rally["steps"][0],
            {"type": "ask", "ref": "q7"},
            {"type": "ask", "ref": "q1"},
            {"type": "ask", "ref": "q2"},
            {"type": "ask", "ref": "q5"},
        ]
        assert "too_many_questions_in_a_row" in codes(course)

    def test_marked_test_mistake_must_be_practised(self, course):
        """m_sf_as_dp came from her real test; dropping its trap is an error."""
        find(course["questions"], "id", "q7")["traps"] = []
        assert "test_mistake_not_practised" in codes(course)

    def test_thin_coverage_is_only_a_warning(self, course):
        course["objectives"].append({"id": "o4", "en": "Estimate answers", "fr": "Estimer"})
        found = warning_codes(course)
        assert "thin_question_coverage" in found
        assert "no_exercise_for_objective" in found
        assert validate(course).ok is True


class TestMinigames:
    """Appendix C.6 — the rule is recomputed for every target."""

    def test_round_with_no_correct_target(self, course):
        course["minigames"][0]["rounds"][0] = [9, 15, 21, 25, 27, 33]
        assert "round_without_target" in codes(course)

    def test_wrong_target_without_misconception_warns(self, course):
        course["minigames"][0]["traps"].pop("9")
        assert "wrong_target_without_misconception" in warning_codes(course)

    def test_which_first_expression_must_parse(self, course):
        course["minigames"].append(
            {
                "id": "g2",
                "engine": "which_first",
                "objective": "o1",
                "title": {"en": "First Move", "fr": "Premier geste"},
                "instruction": {
                    "en": "Tap what to do first.",
                    "fr": "Touche ce qu'il faut faire d'abord.",
                },
                "rounds": [{"expr": "3 + ("}],
                "points": {"per_correct": 1},
            }
        )
        course["chapters"][0]["scenes"][0]["steps"].append({"type": "game", "ref": "g2"})
        assert "bad_expression" in codes(course)


class TestPhotoChecks:
    """Appendix C.7 — each exercise's own worked solution must pass."""

    def test_check_number_inconsistent_with_answer(self, course):
        """If photo_check.n disagrees with the answer, a correct photo would
        be marked wrong."""
        find(course["exercises"], "id", "D1")["photo_check"]["check"]["n"] = 250
        assert "photo_check_self_test_failed" in codes(course)

    def test_unknown_copy_shape(self, course):
        find(course["exercises"], "id", "D1")["photo_check"]["copy"] = "long_division"
        assert "unknown_copy_shape" in codes(course)

    def test_unknown_check_function(self, course):
        find(course["exercises"], "id", "D1")["photo_check"]["check"]["fn"] = "magic"
        assert "unknown_check_fn" in codes(course)


class TestTutor:
    """Appendix C.8."""

    def test_persona_must_be_in_cast(self, course):
        course["tutor"]["persona"] = "gandalf"
        assert "tutor_persona_not_in_cast" in codes(course)

    def test_persona_must_be_an_ai_tutor(self, course):
        course["tutor"]["persona"] = "kabore"
        assert "tutor_persona_wrong_kind" in codes(course)

    def test_intro_must_say_it_is_an_ai(self, course):
        course["tutor"]["intro"] = {
            "en": "Hi, I'm Margo! I give hints, you do the maths.",
            "fr": "Salut, je suis Margo ! Je donne des indices.",
        }
        assert "tutor_intro_hides_ai" in codes(course)

    def test_intro_must_say_so_in_every_language(self, course):
        """She reads one language; the disclosure has to be in that one."""
        course["tutor"]["intro"]["fr"] = "Salut, je suis Margo ! Je donne des indices."
        assert "tutor_intro_hides_ai" in codes(course)

    def test_off_topic_and_worry_are_required(self, course):
        course["tutor"].pop("off_topic")
        course["tutor"].pop("worry")
        found = codes(course)
        assert "missing_off_topic" in found
        assert "missing_worry" in found

    def test_tutor_scope_objectives_must_exist(self, course):
        course["tutor"]["scope"]["this_week"] = ["o1", "o9"]
        assert "dangling_objective" in codes(course)

    def test_tutor_block_is_required(self, course):
        course.pop("tutor")
        assert "missing_tutor" in codes(course)


class TestScores:
    """Appendix C.9."""

    def test_predicted_typical_must_be_authored(self, course):
        course["checks"] = {}
        assert "missing_predicted_typical" in codes(course)

    def test_authored_max_points_disagreement_warns(self, course):
        course["checks"]["max_points"] = 999
        assert "max_points_mismatch" in warning_codes(course)

    def test_per_correct_zero_awards_no_minigame_points(self, course):
        """``per_correct: 0`` used to be coerced to 1 by ``x or 1``, counting
        points into max_points that the player never awards."""
        course["minigames"][0]["points"] = {"per_correct": 0}
        checks = validate(course).checks
        assert checks.max_points == 29 - 9  # the 9 prime targets now score 0

    def test_per_correct_defaults_to_one_when_absent(self, course):
        course["minigames"][0]["points"] = {}
        assert validate(course).checks.max_points == 29

    def test_per_correct_zero_on_an_items_round(self, course):
        course["minigames"][0]["rule"] = None
        course["minigames"][0]["engine"] = "catch"
        course["minigames"][0]["traps"] = {}
        course["minigames"][0]["rounds"] = [
            {
                "prompt": {"en": "Catch the primes", "fr": "Attrape les premiers"},
                "items": [
                    {"label": {"en": "13", "fr": "13"}, "correct": True},
                    {"label": {"en": "9", "fr": "9"}, "correct": False, "trap": "m_odd_prime"},
                ],
            }
        ]
        course["minigames"][0]["points"] = {"per_correct": 0}
        assert validate(course).checks.max_points == 29 - 9
        course["minigames"][0]["points"] = {"per_correct": 1}
        assert validate(course).checks.max_points == 29 - 9 + 1
