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


class TestLeakKeepsValueSymbols:
    """Only sentence punctuation is trimmed: ``%``, ``°`` and a minus carry the value.

    Trimming them used to turn "50%" into the needle "50", which then "leaked"
    into any stem that mentioned 50 of anything — a hard error on a valid quiz.
    """

    @pytest.mark.parametrize(
        ("stem", "options"),
        [
            (
                "A survey of 50 people found that 25 smoke. What share of them smoke?",
                ["50%", "25%", "10%", "75%"],
            ),
            (
                "Over 12 months the balance fell by 12 each month. What is the final change?",
                ["−12", "12", "0", "144"],
            ),
            (
                "Water is liquid at 12°C. At what reading is it colder than the freezer?",
                ["−12°C", "12°C", "4°C", "20°C"],
            ),
        ],
    )
    def test_a_number_in_the_stem_is_not_the_signed_or_unit_answer(self, stem, options):
        issues = mcq.check_quiz_question(q(question=stem, options=options, correct_answer=0))
        assert mcq.ANSWER_LEAK not in codes(issues)
        # Long enough with its symbol, so it WAS checked — not skipped as short.
        assert mcq.LEAK_UNCHECKED_SHORT_ANSWER not in codes(issues)

    def test_a_signed_answer_is_not_found_inside_a_range(self):
        issues = mcq.check_quiz_question(
            q(
                question="Children aged 5-12 attend this clinic. What was the coldest day?",
                options=["-12", "12", "5", "-5"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)

    def test_an_unsigned_answer_is_not_found_in_a_negative_number(self):
        """The reverse of −12°C vs 12°C: "12°C" is not in "−12°C" either."""
        issues = mcq.check_quiz_question(
            q(
                question="It fell to −12°C overnight. What was the afternoon high?",
                options=["12°C", "0°C", "4°C", "-4°C"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)

    def test_a_number_inside_a_decimal_is_not_the_answer(self):
        issues = mcq.check_quiz_question(
            q(
                question="The sample weighs 3.125 kg. How many grams over 3 kg is that?",
                options=["125", "250", "500", "1000"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)

    @pytest.mark.parametrize(
        ("stem", "answer"),
        [
            ("Exactly 50% of cases were treated. What share were treated?", "50%"),
            ("50 % des patients sont traités. Quelle part est traitée ?", "50 %"),
            ("It fell to −12°C. What was the low?", "-12°C"),
            ("The share was −12 points. By how much did it change?", "−12"),
        ],
    )
    def test_the_full_value_in_the_stem_is_still_a_leak(self, stem, answer):
        issues = mcq.check_quiz_question(
            q(
                question=stem,
                options=[answer, "Other one", "Third one", "Fourth one"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK in errors(issues)

    def test_min_length_applies_after_trimming_punctuation(self):
        """ "12." is two characters of answer: reported short, not checked."""
        issues = mcq.check_quiz_question(
            q(question="Is it 12?", options=["12.", "13", "14", "15"], correct_answer=0)
        )
        assert mcq.ANSWER_LEAK not in codes(issues)
        assert mcq.LEAK_UNCHECKED_SHORT_ANSWER in codes(issues)

    def test_quotes_are_trimmed_like_sentence_punctuation(self):
        issues = mcq.check_quiz_question(
            q(
                question="Is malaria transmitted by mosquitoes?",
                options=["Cholera", "« Malaria »", "Measles", "Tuberculosis"],
            )
        )
        assert mcq.ANSWER_LEAK in errors(issues)


#: The spaces French typography puts between digit groups and before a unit:
#: plain, no-break (U+00A0), narrow no-break (U+202F) and thin (U+2009).
FRENCH_SPACES = [" ", "\u00a0", "\u202f", "\u2009"]
SPACE_IDS = ["space", "nbsp", "narrow-nbsp", "thin"]


class TestFrenchNumberTypography:
    """French groups digits with a space ("12 500") and spaces units ("100 %").

    The leak check found "500" in "12 500" and "100" in "100 %", while the
    English twins ("12,500", "100%") passed: a hard error on valid French
    quizzes, an admin edit of them refused, a French story unpublishable.
    """

    @pytest.mark.parametrize("space", FRENCH_SPACES, ids=SPACE_IDS)
    def test_a_digit_group_is_not_the_answer(self, space):
        stem = (
            f"Un district compte 12{space}500 enfants. La prévalence de la malnutrition "
            f"est de 4{space}%. Combien d'enfants sont malnutris ?"
        )
        issues = mcq.check_quiz_question(
            q(question=stem, options=["50", "500", f"5{space}000", "125"], correct_answer=1)
        )
        assert mcq.ANSWER_LEAK not in codes(issues)
        assert mcq.LEAK_UNCHECKED_SHORT_ANSWER not in codes(issues)

    def test_the_english_twin_agrees(self):
        stem = "A district has 12,500 children. Prevalence is 4%. How many are malnourished?"
        issues = mcq.check_quiz_question(
            q(question=stem, options=["50", "500", "5,000", "125"], correct_answer=1)
        )
        assert mcq.ANSWER_LEAK not in codes(issues)

    @pytest.mark.parametrize("space", FRENCH_SPACES, ids=SPACE_IDS)
    def test_the_leading_group_is_not_the_answer_either(self, space):
        issues = mcq.check_quiz_question(
            q(
                question=f"La ville compte 125{space}000 habitants. Combien de districts ?",
                options=["125", "12", "250", "1000"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)

    @pytest.mark.parametrize("space", FRENCH_SPACES, ids=SPACE_IDS)
    @pytest.mark.parametrize(
        ("stem", "answer"),
        [
            (
                "Pour atteindre 100{s}% de couverture, sur 400 enfants dont 300 vaccinés, "
                "combien reste-t-il à vacciner ?",
                "100",
            ),
            ("La fièvre est à 38,5{s}°C. Quelle était la température la veille ?", "38,5"),
            ("Le taux est de 250{s}‰. Combien de cas pour 1000 ?", "250"),
        ],
        ids=["percent", "celsius", "per-mille"],
    )
    def test_a_number_with_a_spaced_unit_is_not_the_bare_answer(self, space, stem, answer):
        issues = mcq.check_quiz_question(
            q(
                question=stem.format(s=space),
                options=[answer, "Autre réponse", "Troisième", "Quatrième"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)

    @pytest.mark.parametrize(
        "stem",
        [
            # The answer itself, after a comma: not a digit group.
            "Sur 12 500 enfants, 500 sont malnutris. Combien sont malnutris ?",
            # A year is not a group of three digits.
            "En 2024 500 enfants ont été vaccinés. Combien d'enfants vaccinés ?",
            "Il y a 500 enfants dans ce district. Combien d'enfants y a-t-il ?",
        ],
    )
    def test_a_standalone_number_still_leaks(self, stem):
        issues = mcq.check_quiz_question(
            q(question=stem, options=["50", "500", "5 000", "125"], correct_answer=1)
        )
        assert mcq.ANSWER_LEAK in errors(issues)

    def test_a_spaced_percentage_answer_still_leaks(self):
        issues = mcq.check_quiz_question(
            q(
                question="100 % des enfants sont vaccinés. Quelle est la couverture ?",
                options=["100 %", "50 %", "75 %", "25 %"],
                correct_answer=0,
            )
        )
        assert mcq.ANSWER_LEAK in errors(issues)

    def test_story_choice_prompt_with_grouped_digits(self):
        question = Question.model_validate(
            {
                "id": "q1",
                "type": "choice",
                "prompt": {
                    "en": "A district has 12,500 children; 4% are malnourished. How many?",
                    "fr": "Un district compte 12\u202f500 enfants ; 4\u202f% sont malnutris. "
                    "Combien ?",
                },
                "answer": "b",
                "choices": [
                    {"id": "a", "en": "50", "fr": "50", "misconception": "m_shift"},
                    {"id": "b", "en": "500", "fr": "500"},
                    {"id": "c", "en": "5,000", "fr": "5\u202f000", "misconception": "m_tenth"},
                    {"id": "d", "en": "125", "fr": "125", "misconception": "m_divide"},
                ],
            }
        )
        issues = [
            i for view in mcq.from_story_choice_question(question) for i in mcq.check_mcq(view)
        ]
        assert mcq.ANSWER_LEAK not in codes(issues)


def warnings_at(issues, code) -> list[str]:
    return [i.path for i in issues if i.code == code and i.severity == "warning"]


def leak_view(stem: str, options, correct: int, hints=()) -> mcq.McqView:
    return mcq.McqView(
        stem=stem,
        options=tuple(options),
        correct_index=correct,
        path="questions[q1]",
        stem_path="questions[q1].question",
        option_path="questions[q1].options",
        other_texts=tuple((f"questions[q1].hints[{i}]", hint) for i, hint in enumerate(hints)),
    )


#: Legitimate either/or stems, each naming the correct option beside a
#: distractor. Every one of them was a hard ``answer_leak`` at some point, and
#: a hard error refuses an admin's edit of the quiz and blocks a story.
EITHER_OR_STEMS = [
    ("Which is larger: three quarters or two thirds?", ["three quarters", "two thirds"], 0),
    ("Is this disease more severe in children or in adults?", ["children", "adults"], 0),
    ("Is rabies transmitted to humans or to cattle mostly?", ["humans", "cattle"], 0),
    ("Is artemether used for malaria or for cholera?", ["malaria", "cholera"], 0),
    ("Is this a case of malaria or of dengue?", ["malaria", "dengue"], 0),
    ("Does the infection come from water or from mosquitoes?", ["mosquitoes", "water"], 0),
    ("Compare malaria to cholera: which is vector-borne?", ["malaria", "cholera"], 0),
    ("Is it malaria? Or cholera?", ["malaria", "cholera"], 0),
    ("Which is vector-borne: malaria; cholera; typhoid?", ["malaria", "cholera", "typhoid"], 0),
    (
        "Which is vector-borne? (a) malaria (b) cholera (c) typhoid",
        ["malaria", "cholera", "typhoid"],
        0,
    ),
    ("Ce symptôme est-il lié à la dengue ou au paludisme ?", ["paludisme", "dengue"], 0),
    ("Ce vaccin est-il destiné aux enfants ou aux adultes ?", ["enfants", "adultes"], 0),
    (
        "Utilise-t-on l'artéméther pour le paludisme ou pour le choléra ?",
        ["paludisme", "choléra"],
        0,
    ),
    (
        "La maladie est-elle plus grave chez l'enfant ou chez l'adulte ?",
        ["enfant", "adulte"],
        0,
    ),
    (
        "Le pic survient-il en saison sèche ou en saison des pluies ?",
        ["saison sèche", "saison des pluies"],
        0,
    ),
    ("Faut-il traiter des enfants ou des adultes en priorité ?", ["enfants", "adultes"], 0),
]


class TestLeakSeverityIsTiered:
    """Where the correct option is found, the severity depends on one fact.

    No distractor named in that text: the answer is given away, an ERROR
    ``answer_leak``. A distractor named there too: the text may be comparing
    the options, so it is a WARNING ``answer_leak_ambiguous`` for a person to
    look at. No grammar is parsed — a list of joining words never covers the
    ways authors write an either/or question, and every miss was a hard error
    on a valid quiz.
    """

    @pytest.mark.parametrize(("stem", "options", "correct"), EITHER_OR_STEMS)
    def test_either_or_stem_is_a_warning_not_an_error(self, stem, options, correct):
        issues = mcq.check_answer_leak(leak_view(stem, options, correct))
        assert not errors(issues)
        assert warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS) == ["questions[q1].question"]

    @pytest.mark.parametrize(
        ("stem", "options", "correct"),
        [
            ("Which is larger: 3/4 or 2/3?", ["3/4", "2/3", "They are equal", "It depends"], 0),
            (
                "Which test confirms malaria fastest at the bedside, the RDT or microscopy?",
                ["Culture", "Microscopy", "RDT", "PCR"],
                1,
            ),
            (
                "Lequel est le plus grand : 0,75 ou 0,7 ?",
                ["0,75", "0,7", "Ils sont égaux", "On ne peut pas savoir"],
                0,
            ),
            (
                "Which is prime: nine, thirteen or twenty-one?",
                ["one", "nine", "thirteen", "twenty-one"],
                2,
            ),
            ("Is it the RDT or the microscopy?", ["Culture", "Microscopy", "RDT", "PCR"], 1),
            ("Which is larger: 3/4 vs. 2/3?", ["3/4", "2/3", "They are equal", "It depends"], 0),
            (
                "Le paludisme est-il transmis par l'eau ou par le moustique Anopheles ?",
                ["Par l'eau", "Par le moustique Anopheles", "Par l'air", "Par contact"],
                1,
            ),
            (
                "Lequel est premier : « neuf » ou « treize » ?",
                ["un", "neuf", "treize", "vingt et un"],
                2,
            ),
            # A distractor mentioned in passing: a person decides.
            (
                "Malaria, unlike cholera, is spread by mosquitoes. Which disease is it?",
                ["Cholera", "Malaria", "Measles", "Tuberculosis"],
                1,
            ),
            (
                "Nine and thirteen are odd; thirteen is prime. Which number is prime?",
                ["one", "nine", "thirteen", "twenty-one"],
                2,
            ),
        ],
    )
    def test_a_named_distractor_makes_it_a_warning(self, stem, options, correct):
        issues = mcq.check_quiz_question(q(question=stem, options=options, correct_answer=correct))
        assert mcq.ANSWER_LEAK not in codes(issues)
        assert warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS) == ["questions[q1].question"]

    def test_the_ambiguous_leak_is_not_a_hard_code(self):
        assert mcq.ANSWER_LEAK_AMBIGUOUS not in mcq.HARD_CODES
        assert mcq.ANSWER_LEAK in mcq.HARD_CODES

    def test_the_answer_named_with_no_distractor_is_an_error(self):
        view = leak_view(
            "Which disease is vector-borne?",
            ["malaria", "cholera"],
            0,
            hints=["The answer is malaria."],
        )
        issues = mcq.check_answer_leak(view)
        leaks = [i for i in issues if i.code == mcq.ANSWER_LEAK]
        assert [(i.path, i.severity) for i in leaks] == [("questions[q1].hints[0]", "error")]
        assert mcq.ANSWER_LEAK_AMBIGUOUS not in codes(issues)

    def test_a_plain_leak_in_the_stem_is_an_error(self):
        issues = mcq.check_answer_leak(
            leak_view(
                "Malaria is vector-borne. Which disease is vector-borne?", ["malaria", "cholera"], 0
            )
        )
        assert [i.path for i in issues if i.code == mcq.ANSWER_LEAK] == ["questions[q1].question"]
        assert mcq.ANSWER_LEAK in errors(issues)

    @pytest.mark.parametrize(
        "hint",
        [
            "The answer is malaria, and cholera is not.",
            "It is malaria and not cholera.",
            "Pick malaria or you lose; cholera is wrong.",
        ],
    )
    def test_a_hint_naming_a_distractor_beside_the_answer_is_a_warning(self, hint):
        view = leak_view("Which disease is vector-borne?", ["malaria", "cholera"], 0, hints=[hint])
        issues = mcq.check_answer_leak(view)
        assert not errors(issues)
        assert warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS) == ["questions[q1].hints[0]"]

    @pytest.mark.parametrize(
        "hint, options",
        [
            (
                "Nine is 3 × 3, so the prime one is thirteen.",
                ("one", "nine", "thirteen", "twenty-one"),
            ),
            (
                "Neuf = 3 × 3, donc le nombre premier est treize.",
                ("un", "neuf", "treize", "vingt et un"),
            ),
        ],
    )
    def test_a_hint_naming_a_distractor_then_the_answer_is_a_warning(self, hint, options):
        issues = mcq.check_answer_leak(leak_view("Which number is prime?", options, 2, [hint]))
        assert not errors(issues)
        assert warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS) == ["questions[q1].hints[0]"]

    def test_each_text_is_judged_on_its_own(self):
        """The stem names both; a hint that names only the answer still leaks."""
        view = leak_view(
            "Which is larger: 3/4 or 2/3?",
            ("3/4", "2/3", "They are equal", "It depends"),
            0,
            hints=["Hint: it is 3/4."],
        )
        issues = mcq.check_answer_leak(view)
        assert [i.path for i in issues if i.code == mcq.ANSWER_LEAK] == ["questions[q1].hints[0]"]
        assert warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS) == ["questions[q1].question"]

    @pytest.mark.parametrize(
        ("stem", "options"),
        [
            # "a" and "un" are under the leak-length floor: never evidence.
            (
                "Malaria is a disease spread by Anopheles. Which disease is it?",
                ["a", "Malaria", "Measles", "Tuberculosis"],
            ),
            (
                "Treize est un nombre premier. Lequel de ces nombres est un nombre premier ?",
                ["un", "neuf", "treize", "vingt et un"],
            ),
        ],
    )
    def test_a_distractor_under_the_length_floor_is_no_evidence(self, stem, options):
        correct = 1 if options[0] == "a" else 2
        issues = mcq.check_quiz_question(q(question=stem, options=options, correct_answer=correct))
        assert mcq.ANSWER_LEAK in errors(issues)
        assert mcq.ANSWER_LEAK_AMBIGUOUS not in codes(issues)

    def test_a_three_letter_distractor_counts(self):
        """ "one" is as long as the leak floor, so it counts as named, even as
        a pronoun. A higher floor would make "the RDT or the PCR" an error."""
        issues = mcq.check_quiz_question(
            q(
                question="Thirteen is prime. Which one of these is a prime number?",
                options=["one", "nine", "thirteen", "twenty-one"],
                correct_answer=2,
            )
        )
        assert mcq.ANSWER_LEAK not in codes(issues)
        assert warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS) == ["questions[q1].question"]

    def test_a_duplicate_of_the_answer_is_no_evidence(self):
        issues = mcq.check_quiz_question(
            q(
                question="Malaria is spread by Anopheles. Which disease is it?",
                options=["Malaria.", "Malaria", "Measles", "Tuberculosis"],
            )
        )
        assert {mcq.ANSWER_LEAK, mcq.DUPLICATE_OPTIONS} <= errors(issues)

    def test_a_distractor_inside_the_answer_is_no_evidence(self):
        """ "malaria" in "cerebral malaria" is the answer, not a second option."""
        issues = mcq.check_answer_leak(
            leak_view(
                "Cerebral malaria needs IV artesunate. Which form is it?",
                ["cerebral malaria", "malaria", "dengue", "typhoid"],
                0,
            )
        )
        assert [i.path for i in issues if i.code == mcq.ANSWER_LEAK] == ["questions[q1].question"]
        assert mcq.ANSWER_LEAK_AMBIGUOUS not in codes(issues)

    def test_the_answer_inside_a_distractor_counts_as_naming_it(self):
        """The reverse: answer "malaria" sits inside the distractor "cerebral
        malaria", which is named as a whole, so the text names a distractor."""
        issues = mcq.check_answer_leak(
            leak_view(
                "Is it cerebral malaria?",
                ["malaria", "cerebral malaria", "dengue", "typhoid"],
                0,
            )
        )
        assert not errors(issues)
        assert warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS) == ["questions[q1].question"]

    def test_story_choice_comparison_prompt_and_hint_are_warnings_only(self):
        question = Question.model_validate(
            {
                "id": "q1",
                "type": "choice",
                "prompt": {
                    "en": "Which is larger: three quarters or two thirds?",
                    "fr": "Lequel est le plus grand : trois quarts ou deux tiers ?",
                },
                "answer": "a",
                "choices": [
                    {"id": "a", "en": "three quarters", "fr": "trois quarts"},
                    {"id": "b", "en": "two thirds", "fr": "deux tiers", "misconception": "m"},
                    {"id": "c", "en": "they are equal", "fr": "égaux", "misconception": "m"},
                ],
                "hints": [
                    {
                        "en": "Compare three quarters with two thirds over twelfths.",
                        "fr": "Compare trois quarts et deux tiers en douzièmes.",
                    }
                ],
            }
        )
        issues = [
            i for view in mcq.from_story_choice_question(question) for i in mcq.check_mcq(view)
        ]
        assert not errors(issues)
        assert sorted(warnings_at(issues, mcq.ANSWER_LEAK_AMBIGUOUS)) == [
            "questions[q1].hints[0].en",
            "questions[q1].hints[0].fr",
            "questions[q1].prompt.en",
            "questions[q1].prompt.fr",
        ]


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
        issues = mcq.check_quiz_question(q(options=["Cholera", "Malaria", "Cholera.", "Measles"]))
        dup = [i for i in issues if i.code == mcq.DUPLICATE_OPTIONS]
        assert len(dup) == 1
        assert "same distractor" in dup[0].message

    def test_minus_signs_are_distinct_from_plain_numbers(self):
        issues = mcq.check_quiz_question(q(options=["−5", "5", "-6", "6"]))
        assert mcq.DUPLICATE_OPTIONS not in codes(issues)

    def test_unicode_minus_and_hyphen_minus_are_the_same_option(self):
        issues = mcq.check_quiz_question(q(options=["−5", "-5", "6", "7"]))
        assert mcq.DUPLICATE_OPTIONS in codes(issues)

    @pytest.mark.parametrize(
        "options",
        [
            ["CO", "Co", "CO2", "C"],  # carbon monoxide vs cobalt
            ["mg", "Mg", "mL", "g"],  # milligram vs magnesium
            ["Malaria", "malaria", "Measles", "Tuberculosis"],
        ],
    )
    def test_options_differing_only_by_case_are_not_duplicates(self, options):
        issues = mcq.check_quiz_question(q(options=options, correct_answer=0))
        assert mcq.DUPLICATE_OPTIONS not in codes(issues)

    def test_composition_spacing_and_trailing_punctuation_still_match(self):
        """NFC: a precomposed é and e + combining accent are one option."""
        issues = mcq.check_quiz_question(
            q(options=["Fièvre", "Fièvre !", "Toux", "Diarrhée"], correct_answer=2)
        )
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
