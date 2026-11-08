"""Tests for the shared multiple-choice checks (``mcq_checks``).

The checks run over both MCQ shapes in the codebase — stored course-quiz
questions (flat ``options`` + integer ``correct_answer``) and story-course
``choice`` questions — so every rule is exercised against the real quiz
question shape, and the adapters are tested for the off-by-one traps the two
shapes invite (an int index vs a choice id).
"""

import copy

import pytest

from app.api.v1.schemas.quiz import QuizQuestion
from app.api.v1.schemas.story_course import Question
from app.domain.services import mcq_checks as mcq

CLEAN = {
    "id": "q1",
    "question": "Which disease is transmitted by the Anopheles mosquito?",
    "options": ["Cholera", "Malaria", "Measles", "Tuberculosis"],
    "correct_answer": 1,
    "explanation": "Anopheles mosquitoes carry Plasmodium.",
    "sources_cited": ["WHO fact sheet"],
    "difficulty": "easy",
}


def q(**overrides) -> dict:
    question = copy.deepcopy(CLEAN)
    question.update(overrides)
    return question


def codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def errors(issues) -> set[str]:
    return {issue.code for issue in issues if issue.severity == "error"}


class TestAdapters:
    def test_quiz_question_dict(self):
        view = mcq.from_quiz_question(CLEAN)
        assert view.stem == CLEAN["question"]
        assert view.options == tuple(CLEAN["options"])
        assert view.correct_index == 1
        assert view.correct_option == "Malaria"
        assert view.option_misconceptions is None
        assert view.stem_path == "questions[q1].question"
        assert view.option_at(2) == "questions[q1].options[2]"

    def test_quiz_question_model(self):
        view = mcq.from_quiz_question(QuizQuestion(**CLEAN))
        assert view.correct_option == "Malaria"

    def test_quiz_question_misconceptions_are_aligned(self):
        """Padded/trimmed to the options and forced null on the correct one."""
        view = mcq.from_quiz_question(q(option_misconceptions=["a", "should vanish", "  ", 7, "x"]))
        assert view.option_misconceptions == ("a", None, None, "7")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"options": "Cholera"},
            {"options": []},
            {"options": ["a", 2, "c", "d"]},
            {"correct_answer": 4},
            {"correct_answer": -1},
            {"correct_answer": "1"},
            {"correct_answer": True},
            {"question": None},
        ],
    )
    def test_malformed_question_is_rejected(self, overrides):
        with pytest.raises(mcq.McqShapeError):
            mcq.from_quiz_question(q(**overrides))
        assert codes(mcq.check_quiz_question(q(**overrides))) == {mcq.MALFORMED_QUESTION}

    def test_story_choice_question_maps_answer_id_to_index(self):
        """The story answer is a choice id, not an int; mapping by position
        would misread the correct option as a distractor."""
        question = Question.model_validate(
            {
                "id": "q1",
                "type": "choice",
                "prompt": {"en": "Which is prime?", "fr": "Lequel est premier ?"},
                "answer": "c",
                "choices": [
                    {"id": "a", "en": "1", "fr": "1", "misconception": "m_one"},
                    {"id": "b", "en": "9", "fr": "9", "misconception": "m_odd"},
                    {"id": "c", "en": "13", "fr": "13"},
                ],
                "hints": [{"en": "Test 2 and 3.", "fr": "Teste 2 et 3."}],
            }
        )
        views = mcq.from_story_choice_question(question)
        assert [v.stem_path for v in views] == [
            "questions[q1].prompt.en",
            "questions[q1].prompt.fr",
        ]
        assert all(v.correct_index == 2 for v in views)
        assert views[0].option_misconceptions == ("m_one", "m_odd", None)
        assert views[1].other_texts == (("questions[q1].hints[0].fr", "Teste 2 et 3."),)

    def test_unresolved_story_answer_yields_no_view(self):
        question = Question.model_validate(
            {
                "id": "q1",
                "type": "choice",
                "prompt": {"en": "?", "fr": "?"},
                "answer": "z",
                "choices": [{"id": "a", "en": "x", "fr": "x"}],
            }
        )
        assert mcq.from_story_choice_question(question) == []


class TestAnswerLeak:
    def test_clean_question_has_no_leak(self):
        assert mcq.ANSWER_LEAK not in codes(mcq.check_quiz_question(q()))

    def test_correct_option_text_in_stem_is_a_leak(self):
        issues = mcq.check_quiz_question(
            q(question="Malaria is spread by Anopheles. Which disease do they transmit?")
        )
        leak = [i for i in issues if i.code == mcq.ANSWER_LEAK]
        assert leak and leak[0].severity == "error"
        assert leak[0].path == "questions[q1].question"

    def test_leak_ignores_case_spacing_and_trailing_punctuation(self):
        issues = mcq.check_quiz_question(
            q(
                question="The answer is MALARIA, isn't it?",
                options=["Cholera", "malaria.", "Measles", "Tuberculosis"],
            )
        )
        assert mcq.ANSWER_LEAK in errors(issues)

    def test_maths_spacing_is_normalised(self):
        issues = mcq.check_quiz_question(
            q(
                question="Is 360 = 2³×3²×5 in index form?",
                options=["2³ × 3² × 5", "2³ × 3 × 5", "2² × 3² × 5", "6²"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK in errors(issues)

    def test_leak_is_judged_on_whole_words(self):
        """'water' inside 'seawater' is not the answer pasted into the stem."""
        issues = mcq.check_quiz_question(
            q(
                question="What is the main component of seawater?",
                options=["Salt", "Water", "Sand", "Oil"],
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)

    def test_a_distractor_in_the_stem_is_not_a_leak(self):
        issues = mcq.check_quiz_question(q(question="Unlike cholera, which disease do they carry?"))
        assert mcq.ANSWER_LEAK not in codes(issues)

    def test_short_numeric_answer_is_reported_as_unchecked(self):
        """A numeric quiz must not come back as falsely clean: the skip is said."""
        issues = mcq.check_quiz_question(
            q(
                question="How many days are in a fortnight? (Hint: 14 in total)",
                options=["11", "12", "9", "14"],
                correct_answer=3,
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)
        unchecked = [i for i in issues if i.code == mcq.LEAK_UNCHECKED_SHORT_ANSWER]
        assert len(unchecked) == 1
        assert unchecked[0].severity == "warning"
        assert unchecked[0].path == "questions[q1].options[3]"

    def test_min_length_is_configurable(self):
        view = mcq.from_quiz_question(
            q(question="Is it 14?", options=["11", "12", "9", "14"], correct_answer=3)
        )
        assert mcq.ANSWER_LEAK in codes(mcq.check_answer_leak(view, min_length=2))


class TestDuplicateOptions:
    def test_duplicate_of_the_correct_option_means_two_correct_answers(self):
        issues = mcq.check_quiz_question(
            q(
                options=["Fièvre + éruption", "Fièvre + éruption ", "Toux", "Diarrhée"],
                correct_answer=0,
            )
        )
        dup = [i for i in issues if i.code == mcq.DUPLICATE_OPTIONS]
        assert len(dup) == 1
        assert dup[0].severity == "error"
        assert dup[0].path == "questions[q1].options[1]"
        assert "two options are correct" in dup[0].message

    def test_duplicate_distractors_are_an_error_too(self):
        issues = mcq.check_quiz_question(q(options=["Cholera", "Malaria", "cholera.", "Measles"]))
        dup = [i for i in issues if i.code == mcq.DUPLICATE_OPTIONS]
        assert len(dup) == 1
        assert "same distractor" in dup[0].message

    def test_minus_signs_are_distinct_from_plain_numbers(self):
        issues = mcq.check_quiz_question(q(options=["−5", "5", "-6", "6"]))
        assert mcq.DUPLICATE_OPTIONS not in codes(issues)

    def test_unicode_minus_and_hyphen_minus_are_the_same_option(self):
        issues = mcq.check_quiz_question(q(options=["−5", "-5", "6", "7"]))
        assert mcq.DUPLICATE_OPTIONS in codes(issues)

    def test_empty_option(self):
        assert mcq.EMPTY_OPTION in errors(mcq.check_quiz_question(q(options=["A", "B", " ", "D"])))


class TestMisconceptions:
    def test_absent_metadata_is_a_warning_not_an_error(self):
        issues = mcq.check_quiz_question(q())
        unchecked = [i for i in issues if i.code == mcq.MISCONCEPTIONS_UNCHECKED]
        assert len(unchecked) == 1
        assert unchecked[0].severity == "warning"
        assert not errors(issues)

    def test_complete_metadata_is_clean(self):
        issues = mcq.check_quiz_question(
            q(
                option_misconceptions=[
                    "Thinks every fever-and-diarrhoea illness is mosquito-borne",
                    None,
                    "Confuses a rash illness with a vector-borne one",
                    "Thinks any tropical disease is carried by mosquitoes",
                ]
            )
        )
        assert not errors(issues)
        assert mcq.MISCONCEPTIONS_UNCHECKED not in codes(issues)

    def test_missing_misconception_on_a_distractor(self):
        issues = mcq.check_quiz_question(q(option_misconceptions=["a", None, "", "d"]))
        missing = [i for i in issues if i.code == mcq.DISTRACTOR_WITHOUT_MISCONCEPTION]
        assert [i.path for i in missing] == ["questions[q1].option_misconceptions[2]"]

    def test_short_array_is_padded_so_trailing_distractors_are_caught(self):
        issues = mcq.check_quiz_question(q(option_misconceptions=["a"]))
        missing = {i.path for i in issues if i.code == mcq.DISTRACTOR_WITHOUT_MISCONCEPTION}
        assert missing == {
            "questions[q1].option_misconceptions[2]",
            "questions[q1].option_misconceptions[3]",
        }


class TestNormaliseOptionMisconceptions:
    def test_absent_stays_absent(self):
        assert mcq.normalise_option_misconceptions(None, 4, 1) is None
        assert mcq.normalise_option_misconceptions("oops", 4, 1) is None

    def test_pads_trims_and_nulls_the_correct_slot(self):
        assert mcq.normalise_option_misconceptions(["a", "b"], 4, 0) == [None, "b", None, None]
        assert mcq.normalise_option_misconceptions(["a", "b", "c", "d", "e"], 4, 3) == [
            "a",
            "b",
            "c",
            None,
        ]


class TestQuizContent:
    def test_duplicate_question_ids_break_scoring(self):
        content = {"questions": [q(), q()]}
        assert mcq.DUPLICATE_QUESTION_ID in errors(mcq.check_quiz_content(content))

    def test_paths_name_each_question(self):
        content = {"questions": [q(id="q7", question="Malaria: which disease is it?")]}
        leak = [i for i in mcq.check_quiz_content(content) if i.code == mcq.ANSWER_LEAK]
        assert leak[0].path == "questions[q7].question"

    def test_non_list_questions(self):
        assert codes(mcq.check_quiz_content({"questions": "nope"})) == {mcq.MALFORMED_QUESTION}

    def test_hard_errors_filters_warnings(self):
        issues = mcq.check_quiz_content({"questions": [q()]})
        assert mcq.hard_errors(issues) == []


class TestCrossLanguageParity:
    def test_single_language_is_not_compared(self):
        assert mcq.check_cross_language_parity({"fr": {"questions": [q()]}}) == []

    def test_matching_quizzes_are_clean(self):
        assert (
            mcq.check_cross_language_parity(
                {"en": {"questions": [q()]}, "fr": {"questions": [q()]}}
            )
            == []
        )

    def test_divergence_is_warning_only(self):
        en = {"questions": [q(id="q1"), q(id="q2")]}
        fr = {"questions": [q(id="q1", correct_answer=2)]}
        issues = mcq.check_cross_language_parity({"en": en, "fr": fr}, path="unit[1.2]")
        assert {i.severity for i in issues} == {"warning"}
        assert codes(issues) == {
            mcq.PARITY_QUESTION_COUNT,
            mcq.PARITY_QUESTION_IDS,
            mcq.PARITY_CORRECT_ANSWER,
        }
        answer = next(i for i in issues if i.code == mcq.PARITY_CORRECT_ANSWER)
        assert answer.path == "unit[1.2].questions[q1].correct_answer"
