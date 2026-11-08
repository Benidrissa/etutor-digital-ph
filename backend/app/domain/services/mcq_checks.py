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
  question is only an id like ``"c"``). Answers shorter than
  :data:`MIN_LEAK_LENGTH` characters are not leak-checked — a bare ``"12"``
  shows up in stems for innocent reasons — and that skip is reported as
  :data:`LEAK_UNCHECKED_SHORT_ANSWER` so a clean report is never mistaken for
  proof that a numeric quiz is leak-free.
* **Duplicate options** are the deterministic form of "more than one correct
  answer": the schema stores one correct index, so two correct options can only
  happen as two options with the same text. Two options that *mean* the same
  thing in different words are not decidable here; that belongs to the
  LLM quality agent, not a validator.
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

#: Correct options shorter than this (whitespace removed) are not leak-checked.
#: Mirrors ``story_course_validator._MIN_LEAK_LENGTH``.
MIN_LEAK_LENGTH = 3

# -- finding codes -----------------------------------------------------------

ANSWER_LEAK = "answer_leak"
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
_TRAILING_PUNCT = ".!;:,"


def _fold(text: Any) -> str:
    """Unicode-compose, fold the minus sign and case.

    NFC rather than NFKC on purpose: NFKC would turn ``2³`` into ``23``.
    """
    return unicodedata.normalize("NFC", str(text)).replace(MINUS, "-").casefold()


def compact(text: Any) -> str:
    """Folded text with every whitespace character removed."""
    return re.sub(r"\s+", "", _fold(text))


def option_key(text: Any) -> str:
    """Comparison key for duplicate options: compact, trailing punctuation off."""
    return compact(text).rstrip(_TRAILING_PUNCT)


def _tokens(text: Any) -> list[str]:
    """Words and individual symbols, so ``2³×3²`` and ``2³ × 3²`` agree."""
    return _TOKEN_RE.findall(_fold(text))


def _strip_edge_punctuation(tokens: list[str]) -> list[str]:
    start, end = 0, len(tokens)
    while start < end and not tokens[start][0].isalnum():
        start += 1
    while end > start and not tokens[end - 1][0].isalnum():
        end -= 1
    return tokens[start:end]


def _contains_sequence(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(
        list(haystack[i : i + width]) == list(needle) for i in range(len(haystack) - width + 1)
    )


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


def check_answer_leak(view: McqView, *, min_length: int = MIN_LEAK_LENGTH) -> list[ValidationIssue]:
    """The correct option's text must not appear in the stem or hints.

    Matching is on whole words and symbols (case, accents composition, spacing
    and the minus sign normalised), so ``"water"`` does not match ``"seawater"``
    but ``"2³ × 3²"`` matches ``"2³×3²"``.
    """
    answer = view.correct_option
    needle = _strip_edge_punctuation(_tokens(answer))
    if len(compact(answer)) < min_length or not needle:
        return [
            _issue(
                "warning",
                LEAK_UNCHECKED_SHORT_ANSWER,
                view.option_at(view.correct_index),
                f"the correct option {answer!r} is shorter than {min_length} characters, so "
                "it was not checked for leaking into the stem",
            )
        ]

    issues: list[ValidationIssue] = []
    for path, text in ((view.stem_path, view.stem), *view.other_texts):
        if _contains_sequence(_tokens(text), needle):
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
