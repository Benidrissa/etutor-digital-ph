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
  range, a digit group (``"500"`` in "12,500" or, French style, "12 500"), or
  a quantity whose unit follows, glued or spaced ("50%", "50 %"). Answers
  shorter than :data:`MIN_LEAK_LENGTH` characters once trimmed are not
  leak-checked — a bare ``"12"`` shows up in stems for innocent reasons — and
  that skip is reported as :data:`LEAK_UNCHECKED_SHORT_ANSWER` so a clean
  report is never mistaken for proof that a numeric quiz is leak-free.
  Severity is tiered on one fact, with no grammar parsed: a text that names
  the correct option and no distractor gives the answer away
  (:data:`ANSWER_LEAK`, an error); a text that also names a distractor may be
  comparing the options ("Is it malaria or cholera?", "aux enfants ou aux
  adultes ?") and gets :data:`ANSWER_LEAK_AMBIGUOUS`, a warning for a person
  to judge. No list of joining words covers the ways an either/or question is
  written, and every miss was a hard error on a valid quiz.
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
#: Sentence punctuation, trimmed from the end of an option for duplicates.
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


def _normalise(text: Any) -> str:
    """Unicode-compose and fold the minus sign; case is kept.

    NFC rather than NFKC on purpose: NFKC would turn ``2³`` into ``23``.
    """
    return unicodedata.normalize("NFC", str(text)).replace(MINUS, "-")


def _fold(text: Any) -> str:
    """:func:`_normalise`, then case-folded (leak matching ignores case)."""
    return _normalise(text).casefold()


def option_key(text: Any) -> str:
    """Comparison key for duplicate options.

    Whitespace removed and trailing sentence punctuation off, but case kept:
    ``"CO"`` (carbon monoxide) and ``"Co"`` (cobalt) are different options,
    and calling them duplicates would be a hard error on a valid question.
    """
    return re.sub(r"\s+", "", _normalise(text)).rstrip(_TRAILING_PUNCT)


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


def _digits_before(text: str, index: int) -> int:
    """How many digits run back from ``text[index - 1]``."""
    count = 0
    while index - count > 0 and text[index - count - 1].isdigit():
        count += 1
    return count


def _digits_from(text: str, index: int) -> int:
    """How many digits run forward from ``text[index]``."""
    count = 0
    while index + count < len(text) and text[index + count].isdigit():
        count += 1
    return count


def _at_value_boundary(folded: str, start: int, end: int, needle: Sequence[str]) -> bool:
    """Whether ``folded[start:end]`` stands on its own as the needle's value.

    Token matching already keeps ``"12"`` out of ``"120"``; this keeps a number
    out of a longer number or quantity around it: ``"12"`` is not found in
    ``"-12"``, ``"3.12"``, ``"12.5"``, ``"12%"`` or ``"12 %"``, ``"500"`` is not
    found in ``"12 500"`` (a space between digit groups, French style) any
    more than in ``"12,500"``, and a needle that starts with a sign
    (``"-12"``) is not found in the range ``"5-12"``.
    """
    first, last = needle[0], needle[-1]
    before = folded[start - 1] if start > 0 else ""
    after = folded[end] if end < len(folded) else ""
    if first in _SIGNS and before.isalnum():
        return False
    if first[0].isdigit():
        if before in _SIGNS:
            return False
        if before in _DECIMAL_SEPARATORS and start >= 2 and folded[start - 2].isdigit():
            return False
        # "12 500": a three-digit group after a group of one to three digits and
        # one space is the tail of a larger number.
        if (
            before in _NUMBER_SPACES
            and _digits_from(first, 0) == 3
            and 1 <= _digits_before(folded, start - 1) <= 3
        ):
            return False
    if last[-1].isdigit():
        unit_at = end
        while unit_at < len(folded) and folded[unit_at] in _NUMBER_SPACES:
            unit_at += 1
        if unit_at < len(folded) and folded[unit_at] in _UNIT_SUFFIXES:
            return False
        if after in _DECIMAL_SEPARATORS and end + 1 < len(folded) and folded[end + 1].isdigit():
            return False
        # "12 500": a group of one to three digits followed by one space and a
        # group of exactly three digits is the head of a larger number.
        if (
            after in _NUMBER_SPACES
            and 1 <= _digits_before(last, len(last)) <= 3
            and _digits_from(folded, end + 1) == 3
        ):
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

    Matching is on whole words and symbols (case, accents composition, spacing
    and the minus sign normalised), so ``"water"`` does not match ``"seawater"``
    but ``"2³ × 3²"`` matches ``"2³×3²"``. Only sentence punctuation and quotes
    are trimmed from the option, and ``min_length`` applies to what is left,
    so ``"50%"`` is checked as ``50%`` (never as ``50``) and ``"12."`` is a
    short answer.

    Each text (the stem, every hint) is judged on its own, and the severity of
    a text that names the correct option is tiered:

    * no distractor named in it: an error, :data:`ANSWER_LEAK`;
    * a distractor named in it too: a warning, :data:`ANSWER_LEAK_AMBIGUOUS` —
      "Which is larger: 3/4 or 2/3?" compares, "Malaria, unlike cholera, …"
      may give the answer away; a person tells them apart, not this check.

    A distractor counts as named only when it is at least ``min_length``
    characters long (so "a" or "un" never does; "one" does), does not read the
    same as the answer, and stands as a whole value outside every occurrence
    of the answer.
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

    # A distractor reading the same as the answer is no evidence of a
    # comparison; check_duplicate_options reports it.
    distractors: list[list[str]] = []
    for index, option in enumerate(view.options):
        tokens = _leak_needle(option)
        if index != view.correct_index and tokens != needle and len("".join(tokens)) >= min_length:
            distractors.append(tokens)

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
