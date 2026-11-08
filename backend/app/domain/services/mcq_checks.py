"""Shared checks for multiple-choice questions.

The platform has two shapes of multiple-choice question:

* course quiz MCQs — one ``generated_content`` row per quiz, each question a
  dict with a flat ``options: list[str]`` and an integer ``correct_answer``
  index (``app/api/v1/schemas/quiz.py``), optionally carrying a positional
  ``option_misconceptions`` array parallel to ``options``;
* story-course ``choice`` questions — bilingual ``Choice`` objects whose
  ``answer`` names the correct choice by id
  (``app/api/v1/schemas/story_course.py``).

Story questions are derived from quiz MCQs, so the two must be judged by the
same rules. Both shapes are lifted into one normalised :class:`McqView` and the
pure check functions below run over that view. They return
:class:`ValidationIssue` findings (``severity``, ``code``, ``path``,
``message``) so the story validator, the quiz generator, the admin edit guard
and the admin MCQ audit all speak one vocabulary.

What these checks can and cannot decide:

* **Answer leak** is judged by the *text of the correct option* (the story
  validator's own leak check uses the answer value, which for a choice
  question is only an id like ``"c"``). Only sentence punctuation and quotes
  are trimmed from the option; value-bearing symbols (``%``, ``°``, currency,
  a leading minus) are part of the answer, so ``"50%"`` is not found in
  "a survey of 50 people" and ``"−12"`` is not found in "12 months". Nor is a
  bare number found inside a larger value: a signed number, a decimal, a
  digit group (``"500"`` in "12,500" or, French style, "12 500"), or a
  quantity whose unit follows, glued or spaced ("50%", "50 %"). A number
  grouped with spaces is the same value ungrouped: ``"12 500"`` is found in
  "12500" and the other way round. The end of a range is a value of its own,
  whichever dash or hyphen joins it: ``"2030"`` is found in "2015-2030" and
  "2015–2030", a signed ``"-12"`` in neither "5-12" nor "5–12". Known gap: a
  decimal comma is not matched against a decimal point (``"3.5 %"`` is not
  found in "3,5 %"), since "1,500" is 1500 in English and 1.5 in French.
  Answers shorter than :data:`MIN_LEAK_LENGTH` characters once
  trimmed are not leak-checked — a bare ``"12"`` shows up in stems for
  innocent reasons — and that skip is reported as
  :data:`LEAK_UNCHECKED_SHORT_ANSWER` so a clean report is never mistaken for
  proof that a numeric quiz is leak-free.
  Severity is tiered on one fact, with no grammar parsed: a text that names
  the correct option and no distractor gives the answer away
  (:data:`ANSWER_LEAK`, an error); a text that also names a distractor may be
  comparing the options ("Is it malaria or cholera?", "aux enfants ou aux
  adultes ?") and gets :data:`ANSWER_LEAK_AMBIGUOUS`, a warning for a person
  to judge. No list of joining words covers the ways an either/or question is
  written, and every miss was a hard error on a valid quiz. A factorised
  either/or ("before or after meals", "5 or 10 mg/kg") writes the words the
  options share once, so a distractor is also named by the words that set it
  apart from the answer ("before", "5"). A stem asking for a verdict ("Is it
  true that…?") names it whatever the answer is, so a True/Vrai/Correct answer
  found only in the stem gets the warning too. An arithmetic answer equal to
  an operand ("250 − 125", answer 125) is a known false-positive error.
* **Duplicate options** are the deterministic form of "more than one correct
  answer": the schema stores one correct index, so two correct options can only
  happen as two options with the same text (case kept: ``"CO"`` and ``"Co"``
  are different options). Two options that *mean* the same thing in different
  words are not decidable here; that belongs to the LLM quality agent, not a
  validator.
* **Distractor without misconception** needs ``option_misconceptions``. Quizzes
  generated before that field existed simply lack it; they get a
  :data:`MISCONCEPTIONS_UNCHECKED` warning rather than an error.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.ai.algorithms.story_maths import MINUS
from app.api.v1.schemas.story_course import ValidationIssue

#: Correct options shorter than this (whitespace, sentence punctuation and
#: quotes removed) are not leak-checked. Mirrors
#: ``story_course_validator._MIN_LEAK_LENGTH``.
MIN_LEAK_LENGTH = 3

#: Bare verdict words (case-folded). A stem asking for a verdict names one
#: ("Is it true that…?", "Est-il vrai que… ?", "Is this correct?") whatever
#: the answer is, so a verdict answer named only in the stem is a warning.
_VERDICT_WORDS = frozenset(
    {
        "true",
        "false",
        "yes",
        "no",
        "correct",
        "incorrect",
        "vrai",
        "vraie",
        "faux",
        "fausse",
        "oui",
        "non",
        "exact",
        "exacte",
        "inexact",
        "inexacte",
    }
)

# -- finding codes -----------------------------------------------------------

ANSWER_LEAK = "answer_leak"
#: The correct option is named beside a distractor: maybe a comparison, maybe
#: a leak. A warning, never a hard code.
ANSWER_LEAK_AMBIGUOUS = "answer_leak_ambiguous"
DUPLICATE_OPTIONS = "duplicate_options"
EMPTY_OPTION = "empty_option"
DISTRACTOR_WITHOUT_MISCONCEPTION = "distractor_without_misconception"
MALFORMED_QUESTION = "malformed_question"
DUPLICATE_QUESTION_ID = "duplicate_question_id"
MISCONCEPTIONS_UNCHECKED = "misconceptions_unchecked"
LEAK_UNCHECKED_SHORT_ANSWER = "leak_unchecked_short_answer"
PARITY_QUESTION_COUNT = "parity_question_count"
PARITY_QUESTION_IDS = "parity_question_ids"
PARITY_CORRECT_ANSWER = "parity_correct_answer"

#: Codes that always mean the question is defective. Callers decide whether a
#: defect blocks (admin edit) or is logged and kept (learner-facing generation).
HARD_CODES = frozenset(
    {
        ANSWER_LEAK,
        DUPLICATE_OPTIONS,
        EMPTY_OPTION,
        DISTRACTOR_WITHOUT_MISCONCEPTION,
        MALFORMED_QUESTION,
        DUPLICATE_QUESTION_ID,
    }
)


class McqShapeError(ValueError):
    """The question cannot be lifted into an :class:`McqView`."""


@dataclass(frozen=True)
class McqView:
    """One multiple-choice question in a single language, shape-independent.

    ``option_misconceptions`` is ``None`` when the source carries no
    misconception metadata at all (legacy quizzes), otherwise a tuple parallel
    to ``options`` with ``None`` at ``correct_index``.

    Findings are addressed with the paths of the source document:
    ``stem_path`` for the stem, ``f"{option_path}[{i}]{option_suffix}"`` for
    option ``i``, and each ``other_texts`` entry carries its own path (hints
    and anything else the learner reads before answering).
    """

    stem: str
    options: tuple[str, ...]
    correct_index: int
    option_misconceptions: tuple[str | None, ...] | None = None
    path: str = ""
    stem_path: str = ""
    option_path: str = ""
    option_suffix: str = ""
    other_texts: tuple[tuple[str, str], ...] = ()

    @property
    def correct_option(self) -> str:
        return self.options[self.correct_index]

    def option_at(self, index: int) -> str:
        return f"{self.option_path}[{index}]{self.option_suffix}"


# -- normalisation -----------------------------------------------------------

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")
#: Sentence punctuation (with the ellipsis), part of :data:`_EDGE_PUNCT`.
_TRAILING_PUNCT = ".,;:!?…"
#: Sentence punctuation and quotes: the only symbols trimmed from the edges of
#: the correct option before leak matching. Everything else — ``%``, ``°``,
#: ``‰``, currency signs, a leading minus — carries the value.
_EDGE_PUNCT = frozenset(_TRAILING_PUNCT + "\"'«»“”„‘’‚‹›")
#: A sign glued to a number makes it a different number ("-12" is not "12").
_SIGNS = frozenset("+-")
#: Between two digits these make one decimal number ("3.125" is not "125").
_DECIMAL_SEPARATORS = frozenset(".,")
#: After a number they make it a different quantity ("50%" is not "50"), glued
#: to it or, in French typography, after a space ("50 %", "38,5 °C").
_UNIT_SUFFIXES = frozenset("%‰°")
#: The spaces French (and SI) typography puts between digit groups ("12 500")
#: and before a unit ("100 %"): plain, no-break, narrow no-break and thin.
_NUMBER_SPACES = frozenset(" \u00a0\u202f\u2009")


#: Characters written for one another, folded to one spelling: the minus sign,
#: the en dash of a range ("2015–2030"), the hyphen, the non-breaking hyphen
#: word processors put in "COVID‑19" and the figure dash to the hyphen-minus;
#: curly quotes, the modifier-letter apostrophe and the acute accent typed for
#: an apostrophe ("l’OMS", "lʼOMS", "l´OMS") to the straight one, since
#: generated French mixes them within one quiz.
_FOLD = str.maketrans(
    {
        MINUS: "-",
        "–": "-",
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "’": "'",
        "‘": "'",
        "ʼ": "'",
        "´": "'",
    }
)


def _normalise(text: Any) -> str:
    """Unicode-compose and fold look-alike characters (:data:`_FOLD`); case is kept.

    NFC rather than NFKC on purpose: NFKC would turn ``2³`` into ``23``.
    """
    return unicodedata.normalize("NFC", str(text)).translate(_FOLD)


#: A number written in digit groups ("12 500", "1 000 000"): a group of one to
#: three digits, then groups of exactly three, each after one number space.
#: "2024 500" (a year, then a count) is not one: its first group has four.
_GROUPED_NUMBER_RE = re.compile(
    "(?<!\\d)\\d{1,3}(?:[" + "".join(sorted(_NUMBER_SPACES)) + "]\\d{3})+(?!\\d)"
)
_NUMBER_SPACE_RE = re.compile("[" + "".join(sorted(_NUMBER_SPACES)) + "]")


def _join_digit_groups(text: str) -> str:
    """Write each grouped number without its spaces: "12 500" as "12500"."""
    return _GROUPED_NUMBER_RE.sub(lambda match: _NUMBER_SPACE_RE.sub("", match.group()), text)


def _fold(text: Any) -> str:
    """:func:`_normalise`, case-folded (leak matching ignores case), with digit
    groups joined, so "12 500" and "12500" are one value as in
    :func:`option_key`, and neither "12" nor "500" is found in it."""
    return _join_digit_groups(_normalise(text).casefold())


_SPACE_RUN_RE = re.compile(r"\s+")
_ELLIPSIS_RE = re.compile(r"\.{3,}")
#: A space next to a symbol ("12,5 %", "2³ × 3²", "Fièvre !", "1, 2").
_SYMBOL_SPACE_RE = re.compile(r" (?=[^\w\s])|(?<=[^\w\s]) ")
#: Sentence punctuation trimmed from the end of an option for duplicates. Not
#: the ellipsis: "1, 2, 3, …" is a sequence that goes on, "1, 2, 3" is not.
_SENTENCE_END = ".,;:!?"


def option_key(text: Any) -> str:
    """Comparison key for duplicate options.

    Spelling that does not change the value is folded: runs of whitespace,
    a space between digit groups ("12 500"), a space next to a symbol
    ("12,5 %", "2³ × 3²", "Fièvre !"), "..." for "…", and sentence
    punctuation at the end ("Cholera."). What does change it is kept: the
    space of a mixed number ("3 1/2" is not "31/2"), the "!" of a factorial
    ("5!" is not "5", "n!" is not "n"), an ellipsis ("1, 2, 3, …" is not
    "1, 2, 3"), and case (``"CO"``, carbon monoxide, is not ``"Co"``,
    cobalt). Calling two of those duplicates would be a hard error on a valid
    question. An option of only punctuation reads as empty.
    """
    key = _SPACE_RUN_RE.sub(" ", _normalise(text)).strip()
    key = _ELLIPSIS_RE.sub("…", key)
    key = _join_digit_groups(key)
    key = _SYMBOL_SPACE_RE.sub("", key)
    while key and key[-1] in _SENTENCE_END:
        if key[-1] == "!" and _is_factorial(key):
            break
        key = key[:-1].rstrip()
    return "" if not key.strip("…") else key


def _is_factorial(key: str) -> bool:
    """Whether the ``"!"`` ending ``key`` follows a number, a bracket or a lone
    letter ("5!", "(n+1)!", "n!"), rather than a word ("Fièvre!")."""
    if len(key) < 2:
        return False
    before = key[-2]
    if before.isdigit() or before == ")":
        return True
    return before.isalpha() and (len(key) == 2 or not key[-3].isalnum())


def _tokens(text: Any) -> list[str]:
    """Words and individual symbols, so ``2³×3²`` and ``2³ × 3²`` agree."""
    return _TOKEN_RE.findall(_fold(text))


def _leak_needle(text: Any) -> list[str]:
    """The tokens of an option, with sentence punctuation and quotes trimmed."""
    tokens = _tokens(text)
    start, end = 0, len(tokens)
    while start < end and tokens[start] in _EDGE_PUNCT:
        start += 1
    while end > start and tokens[end - 1] in _EDGE_PUNCT:
        end -= 1
    return tokens[start:end]


def _at_value_boundary(folded: str, start: int, end: int, needle: Sequence[str]) -> bool:
    """Whether ``folded[start:end]`` stands on its own as the needle's value.

    Token matching already keeps ``"12"`` out of ``"120"`` and, digit groups
    being joined by :func:`_fold`, ``"500"`` out of ``"12 500"``; this keeps a
    number out of a longer number or quantity around it: ``"12"`` is not
    found in ``"-12"``, ``"3.12"``, ``"12.5"``, ``"12%"`` or ``"12 %"``,
    ``"500"`` is not found in ``"12,500"``, and a needle that starts with a
    sign (``"-12"``) is not found in the range ``"5-12"``. A dash after a
    digit joins a range rather than signs a number, so ``"2030"`` is found at
    the end of ``"2015-2030"`` (and of ``"2015–2030"``, folded to the same).
    """
    first, last = needle[0], needle[-1]
    before = folded[start - 1] if start > 0 else ""
    after = folded[end] if end < len(folded) else ""
    if first in _SIGNS and before.isalnum():
        return False
    if first[0].isdigit():
        if before in _SIGNS and not (start >= 2 and folded[start - 2].isdigit()):
            return False
        if before in _DECIMAL_SEPARATORS and start >= 2 and folded[start - 2].isdigit():
            return False
    if last[-1].isdigit():
        unit_at = end
        while unit_at < len(folded) and folded[unit_at] in _NUMBER_SPACES:
            unit_at += 1
        if unit_at < len(folded) and folded[unit_at] in _UNIT_SUFFIXES:
            return False
        if after in _DECIMAL_SEPARATORS and end + 1 < len(folded) and folded[end + 1].isdigit():
            return False
    return True


def _spans(
    needle: Sequence[str], folded: str, matches: Sequence[re.Match]
) -> list[tuple[int, int]]:
    """Token ranges ``[start, end)`` where the needle stands as a whole value."""
    width = len(needle)
    if not width:
        return []
    wanted = list(needle)
    spans: list[tuple[int, int]] = []
    for i in range(len(matches) - width + 1):
        if [m.group() for m in matches[i : i + width]] != wanted:
            continue
        if _at_value_boundary(folded, matches[i].start(), matches[i + width - 1].end(), needle):
            spans.append((i, i + width))
    return spans


def normalise_option_misconceptions(
    raw: Any, option_count: int, correct_index: int | None
) -> list[str | None] | None:
    """Align ``option_misconceptions`` with ``options``.

    Returns ``None`` when ``raw`` is absent or not a list (no metadata).
    Otherwise pads with ``None`` / trims to ``option_count``, turns blank or
    non-string entries into ``None`` (numbers are kept as text), and forces
    ``None`` at ``correct_index`` — the correct option has no misconception.
    """
    if not isinstance(raw, list):
        return None
    aligned: list[str | None] = []
    for index in range(option_count):
        value = raw[index] if index < len(raw) else None
        if isinstance(value, int | float) and not isinstance(value, bool):
            value = str(value)
        text = value.strip() if isinstance(value, str) else ""
        aligned.append(text if text and index != correct_index else None)
    return aligned


# -- adapters ----------------------------------------------------------------


def _get(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def from_quiz_question(question: Any, *, path: str | None = None) -> McqView:
    """Lift a stored quiz question (dict or ``QuizQuestion``) into a view.

    Raises :class:`McqShapeError` when the question is too malformed to check
    (no options list, non-integer or out-of-range ``correct_answer``).
    """
    qid = _get(question, "id")
    path = path if path is not None else f"questions[{qid}]"

    stem = _get(question, "question")
    if not isinstance(stem, str):
        raise McqShapeError("'question' must be a string")

    options = _get(question, "options")
    if not isinstance(options, list | tuple) or not options:
        raise McqShapeError("'options' must be a non-empty list")
    if not all(isinstance(option, str) for option in options):
        raise McqShapeError("every option must be a string")

    correct = _get(question, "correct_answer")
    if isinstance(correct, bool) or not isinstance(correct, int):
        raise McqShapeError("'correct_answer' must be an integer index into 'options'")
    if not 0 <= correct < len(options):
        raise McqShapeError(f"'correct_answer' {correct} is outside the {len(options)} options")

    misconceptions = normalise_option_misconceptions(
        _get(question, "option_misconceptions"), len(options), correct
    )
    return McqView(
        stem=stem,
        options=tuple(options),
        correct_index=correct,
        option_misconceptions=tuple(misconceptions) if misconceptions is not None else None,
        path=path,
        stem_path=f"{path}.question",
        option_path=f"{path}.options",
    )


def from_story_choice_question(question: Any) -> list[McqView]:
    """Lift a story ``choice`` question into one view per language.

    Returns an empty list when the question is not a ``choice`` question or its
    ``answer`` does not name exactly one choice — the story validator reports
    those cases itself (``choice_answer_unresolved``).

    ``Choice`` carries flat ``en``/``fr`` fields, so views are built for those
    two languages; text objects (prompt, hints, trap hints) are read by the same
    language key.
    """
    if getattr(question, "type", None) != "choice" or not question.choices:
        return []
    matches = [i for i, c in enumerate(question.choices) if c.id == str(question.answer)]
    if len(matches) != 1:
        return []
    correct = matches[0]
    path = f"questions[{question.id}]"
    misconceptions = tuple(
        None if index == correct else (choice.misconception or None)
        for index, choice in enumerate(question.choices)
    )

    views: list[McqView] = []
    for lang in ("en", "fr"):
        stem = (question.prompt or {}).get(lang)
        if not isinstance(stem, str):
            continue
        others: list[tuple[str, str]] = []
        for index, hint in enumerate(question.hints):
            if isinstance(hint, dict) and isinstance(hint.get(lang), str):
                others.append((f"{path}.hints[{index}].{lang}", hint[lang]))
        for index, trap in enumerate(question.traps):
            if isinstance(trap.hint, dict) and isinstance(trap.hint.get(lang), str):
                others.append((f"{path}.traps[{index}].hint.{lang}", trap.hint[lang]))
        views.append(
            McqView(
                stem=stem,
                options=tuple(str(getattr(choice, lang, "") or "") for choice in question.choices),
                correct_index=correct,
                option_misconceptions=misconceptions,
                path=path,
                stem_path=f"{path}.prompt.{lang}",
                option_path=f"{path}.choices",
                option_suffix=f".{lang}",
                other_texts=tuple(others),
            )
        )
    return views


# -- checks ------------------------------------------------------------------


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, path=path, message=message)


def _same_word(left: str, right: str) -> bool:
    """Whether two tokens are one word, a plural "s" or "x" aside ("dose", "doses")."""
    if left == right:
        return True
    short, long_ = sorted((left, right), key=len)
    return (
        len(short) >= 3
        and len(long_) == len(short) + 1
        and long_[-1] in "sx"
        and long_.startswith(short)
    )


def _distinctive_part(distractor: Sequence[str], answer: Sequence[str]) -> list[str]:
    """The distractor's tokens with the words it shares with the answer at
    either end removed: "before" from "Before meals" against "After meals",
    "intramusculaire" from "Par voie intramusculaire" against "Par voie
    orale", "5" from "5 mg/kg" against "10 mg/kg". An either/or stem writes
    the shared words once ("before or after meals"), so this part is all of
    the distractor it names. Empty when nothing sets the two apart at an end.
    """
    limit = min(len(distractor), len(answer))
    head = 0
    while head < limit and _same_word(distractor[head], answer[head]):
        head += 1
    tail = 0
    while tail < limit - head and _same_word(distractor[-1 - tail], answer[-1 - tail]):
        tail += 1
    return list(distractor[head : len(distractor) - tail])


def _distractor_needles(view: McqView, needle: Sequence[str], min_length: int) -> list[list[str]]:
    """What counts as naming a distractor in a text, for :func:`check_answer_leak`.

    Each distractor at least ``min_length`` characters long, whole; and, when
    it shares words with the answer at either end, its distinctive part (see
    :func:`_distinctive_part`) if that is at least ``min_length`` characters
    or a number ("5 or 10 mg/kg"). A distractor reading the same as the answer
    is no evidence of a comparison; :func:`check_duplicate_options` reports it.
    """
    needles: list[list[str]] = []
    for index, option in enumerate(view.options):
        tokens = _leak_needle(option)
        if index == view.correct_index or not tokens or tokens == list(needle):
            continue
        if len("".join(tokens)) >= min_length:
            needles.append(tokens)
        part = _distinctive_part(tokens, needle)
        joined = "".join(part)
        if part and part != tokens and (len(joined) >= min_length or joined.isdigit()):
            needles.append(part)
    return needles


def _names_a_distractor(
    distractors: Sequence[Sequence[str]],
    answers: Sequence[tuple[int, int]],
    folded: str,
    matches: Sequence[re.Match],
) -> bool:
    """Whether a distractor stands somewhere in the text other than inside the answer.

    A distractor span contained in an answer span is part of the answer
    ("malaria" in "cerebral malaria"), not a second option named.
    """
    for distractor in distractors:
        for start, end in _spans(distractor, folded, matches):
            if not any(a_start <= start and end <= a_end for a_start, a_end in answers):
                return True
    return False


def check_answer_leak(view: McqView, *, min_length: int = MIN_LEAK_LENGTH) -> list[ValidationIssue]:
    """Report each text a learner reads before answering that names the correct option.

    Matching is on whole words and symbols (case, accents composition, spacing,
    digit groups, dashes and apostrophes normalised), so ``"water"`` does not
    match ``"seawater"`` but ``"2³ × 3²"`` matches ``"2³×3²"``, ``"12 500"``
    matches ``"12500"`` and ``"COVID‑19"`` matches ``"COVID-19"``. Only
    sentence punctuation and quotes are trimmed from the option, and
    ``min_length`` applies to what is left, so ``"50%"`` is checked as
    ``50%`` (never as ``50``) and ``"12."`` is a short answer.

    Each text (the stem, every hint) is judged on its own, and the severity of
    a text that names the correct option is tiered:

    * no distractor named in it: an error, :data:`ANSWER_LEAK`;
    * a distractor named in it too: a warning, :data:`ANSWER_LEAK_AMBIGUOUS` —
      "Which is larger: 3/4 or 2/3?" compares, "Malaria, unlike cholera, …"
      may give the answer away; a person tells them apart, not this check;
    * the stem naming a correct option that is a bare verdict word (True,
      Faux, Correct, …; :data:`_VERDICT_WORDS`): the same warning, since
      "Is it true that…?" names the verdict it asks for. A hint stating the
      verdict is still an error.

    Known false positive: an arithmetic answer equal to one of its operands
    ("Combien font 250 − 125 ?", answer 125) is an error; nothing cheap tells
    it from "the answer is 125".

    A distractor counts as named only when it is at least ``min_length``
    characters long (so "a" or "un" never does; "one" does), does not read the
    same as the answer, and stands as a whole value outside every occurrence
    of the answer. In a factorised either/or ("before or after meals", "5 or
    10 mg/kg", "avant ou après les repas") the distractor never stands whole:
    the words that set it apart from the answer ("before", "5", "avant") name
    it, under the same floor, which a number of any length passes.
    """
    answer = view.correct_option
    needle = _leak_needle(answer)
    if len("".join(needle)) < min_length:
        return [
            _issue(
                "warning",
                LEAK_UNCHECKED_SHORT_ANSWER,
                view.option_at(view.correct_index),
                f"the correct option {answer!r} is shorter than {min_length} characters "
                "(punctuation aside), so it was not checked for leaking into the stem",
            )
        ]

    distractors = _distractor_needles(view, needle, min_length)
    verdict = len(needle) == 1 and needle[0] in _VERDICT_WORDS
    issues: list[ValidationIssue] = []
    for path, text in ((view.stem_path, view.stem), *view.other_texts):
        folded = _fold(text)
        matches = list(_TOKEN_RE.finditer(folded))
        answers = _spans(needle, folded, matches)
        if not answers:
            continue
        if _names_a_distractor(distractors, answers, folded, matches):
            issues.append(
                _issue(
                    "warning",
                    ANSWER_LEAK_AMBIGUOUS,
                    path,
                    f"the correct option {answer!r} appears beside a distractor in the text "
                    "a learner reads before answering: check that it compares the options "
                    "rather than gives the answer away",
                )
            )
            continue
        if verdict and path == view.stem_path:
            issues.append(
                _issue(
                    "warning",
                    ANSWER_LEAK_AMBIGUOUS,
                    path,
                    f"the correct option {answer!r} is a verdict the stem names: check that "
                    'the stem asks for it ("Is it true that…?") rather than gives it',
                )
            )
            continue
        issues.append(
            _issue(
                "error",
                ANSWER_LEAK,
                path,
                f"the correct option {answer!r} appears in the text a learner reads "
                "before answering",
            )
        )
    return issues


def check_duplicate_options(view: McqView) -> list[ValidationIssue]:
    """No two options may read the same; no option may be blank."""
    issues: list[ValidationIssue] = []
    seen: dict[str, int] = {}
    for index, option in enumerate(view.options):
        key = option_key(option)
        if not key:
            issues.append(
                _issue("error", EMPTY_OPTION, view.option_at(index), f"option {index} is empty")
            )
            continue
        if key in seen:
            first = seen[key]
            consequence = (
                "one of them is the correct answer, so two options are correct"
                if view.correct_index in (first, index)
                else "a learner sees the same distractor twice"
            )
            issues.append(
                _issue(
                    "error",
                    DUPLICATE_OPTIONS,
                    view.option_at(index),
                    f"option {index} {option!r} repeats option {first} — {consequence}",
                )
            )
            continue
        seen[key] = index
    return issues


def check_distractor_misconceptions(view: McqView) -> list[ValidationIssue]:
    """Every wrong option must name the misconception it traps.

    Only meaningful when the source carries ``option_misconceptions``; without
    it the question gets one :data:`MISCONCEPTIONS_UNCHECKED` warning.
    """
    if view.option_misconceptions is None:
        return [
            _issue(
                "warning",
                MISCONCEPTIONS_UNCHECKED,
                f"{view.path}.option_misconceptions",
                "no option_misconceptions: whether each wrong option targets a real "
                "misconception cannot be checked",
            )
        ]
    issues: list[ValidationIssue] = []
    for index, misconception in enumerate(view.option_misconceptions):
        if index == view.correct_index:
            continue
        if not (misconception and str(misconception).strip()):
            issues.append(
                _issue(
                    "error",
                    DISTRACTOR_WITHOUT_MISCONCEPTION,
                    f"{view.path}.option_misconceptions[{index}]",
                    f"wrong option {index} ({view.options[index]!r}) needs a misconception — "
                    "wrong choices are traps, never random distractors",
                )
            )
    return issues


def check_mcq(view: McqView, *, misconceptions: bool = True) -> list[ValidationIssue]:
    """Every shared check over one view."""
    issues = [*check_answer_leak(view), *check_duplicate_options(view)]
    if misconceptions:
        issues.extend(check_distractor_misconceptions(view))
    return issues


def check_quiz_question(question: Any, *, path: str | None = None) -> list[ValidationIssue]:
    """Lift and check one stored quiz question; a malformed one is an error."""
    try:
        view = from_quiz_question(question, path=path)
    except McqShapeError as exc:
        where = path if path is not None else f"questions[{_get(question, 'id')}]"
        return [_issue("error", MALFORMED_QUESTION, where, str(exc))]
    return check_mcq(view)


def _question_path(question: Any, index: int) -> str:
    qid = _get(question, "id")
    return f"questions[{qid}]" if isinstance(qid, str) and qid else f"questions[{index}]"


def check_quiz_content(content: Any) -> list[ValidationIssue]:
    """Check every question of one quiz (a stored ``content`` dict or ``QuizContent``)."""
    questions = _get(content, "questions")
    if not isinstance(questions, list | tuple):
        return [_issue("error", MALFORMED_QUESTION, "questions", "'questions' must be a list")]

    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()
    for index, question in enumerate(questions):
        path = _question_path(question, index)
        if not isinstance(question, Mapping) and not hasattr(question, "options"):
            issues.append(_issue("error", MALFORMED_QUESTION, path, "a question must be an object"))
            continue
        qid = _get(question, "id")
        if isinstance(qid, str) and qid:
            if qid in seen_ids:
                issues.append(
                    _issue(
                        "error",
                        DUPLICATE_QUESTION_ID,
                        f"questions[{index}].id",
                        f"question id {qid!r} is used more than once — answers are scored by id",
                    )
                )
            seen_ids.add(qid)
        issues.extend(check_quiz_question(question, path=path))
    return issues


def hard_errors(issues: Iterable[ValidationIssue]) -> list[ValidationIssue]:
    """The findings that mean the question is defective."""
    return [issue for issue in issues if issue.severity == "error"]


# -- cross-language parity ---------------------------------------------------


def _answer_key(content: Any) -> dict[str, Any]:
    questions = _get(content, "questions") or []
    key: dict[str, Any] = {}
    for question in questions if isinstance(questions, list | tuple) else []:
        qid = _get(question, "id")
        if isinstance(qid, str) and qid not in key:
            key[qid] = _get(question, "correct_answer")
    return key


def check_cross_language_parity(
    by_language: Mapping[str, Any], *, path: str = ""
) -> list[ValidationIssue]:
    """Compare one unit's quizzes across languages. Warnings only.

    FR and EN quizzes are independent generations with model-chosen ids, so on
    existing content these routinely differ; this is a report for an admin, not
    a gate.
    """
    if len(by_language) < 2:
        return []
    prefix = f"{path}." if path else ""
    languages = sorted(by_language)
    keys = {lang: _answer_key(by_language[lang]) for lang in languages}
    counts = {lang: len(_get(by_language[lang], "questions") or []) for lang in languages}

    issues: list[ValidationIssue] = []
    if len(set(counts.values())) > 1:
        issues.append(
            _issue(
                "warning",
                PARITY_QUESTION_COUNT,
                f"{prefix}questions",
                f"question counts differ across languages: {counts}",
            )
        )
    id_sets = {lang: set(keys[lang]) for lang in languages}
    if len({frozenset(ids) for ids in id_sets.values()}) > 1:
        issues.append(
            _issue(
                "warning",
                PARITY_QUESTION_IDS,
                f"{prefix}questions",
                "question ids differ across languages: "
                + "; ".join(f"{lang}={sorted(id_sets[lang])}" for lang in languages),
            )
        )
    shared = set.intersection(*id_sets.values())
    for qid in sorted(shared):
        answers = {lang: keys[lang][qid] for lang in languages}
        if len({repr(value) for value in answers.values()}) > 1:
            issues.append(
                _issue(
                    "warning",
                    PARITY_CORRECT_ANSWER,
                    f"{prefix}questions[{qid}].correct_answer",
                    f"correct_answer differs across languages: {answers}",
                )
            )
    return issues
