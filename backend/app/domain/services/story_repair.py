"""The deterministic half of lesson-story generation.

A lesson story is a ``story-course/1`` week built from one lesson unit. The
work is split so that zero validator errors is a property of the code rather
than something hoped for from a model:

* the model writes **pedagogy and translations only** — objectives,
  misconceptions, the home-language translation of the unit quiz and a
  misconception plus a targeted hint for each wrong option, a few extra
  questions, paper exercises, mini-game items, concept rows and the tutor's
  prose (the "spine", see :mod:`app.ai.prompts.story_from_lesson`);
* this module builds **everything structural** — format, id, week,
  languages, learner, cast, sources, chapters, scenes and steps, the
  ask/game/photo wiring, rewards and the ``checks`` plan — and normalises the
  spine (:func:`build_story_document` is ``normalise_story_doc`` in the
  design: it runs before every validation).

Two invariants are enforced here, not trusted to the model:

* **Quiz fidelity.** Every stored MCQ of the unit becomes a choice question
  whose target-language prompt, options and correct option are the quiz's own,
  verbatim (:func:`enforce_quiz_fidelity` re-asserts it after assembly). The
  model only ever writes the home-language side.
* **Learner is the hero.** ``learner.first_name`` is the literal ``{child}``
  placeholder; story lines address the learner in the second person and the
  front end substitutes the real name at display time, so one cached story
  serves every learner.

Language keying (cross-track contract C1): the ``en``/``fr`` fields of
``narrate``/``say`` steps and the ``en``/``fr`` row lists of ``concept``
steps hold English and French respectively, whatever the target language.
Story lines are capped at 100 characters in *both* languages (C2) so a story
validates whether a validator reads those fields by language or by position.

When the model leaves one language out, the builder still fills the gap by
copying the other language — a story must always have both keys — but every
such copy is recorded as a ``missing_translation`` issue, with the path of the
model's own field (:attr:`StoryBuild.issues`). The repair loop feeds those back
like any validator error; only after the repair budget does a copy survive,
and then as a warning in the stored report, never silently.
"""

from __future__ import annotations

import copy
import math
import re
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.ai.algorithms import story_maths as maths
from app.api.v1.schemas.story_course import (
    FORMAT_VERSION,
    LENGTH_LIMITS,
    PLACES,
    REWARD_DEFAULTS,
    ValidationIssue,
    ValidationReport,
)

logger = structlog.get_logger(__name__)

LANGS = ("en", "fr")

#: The learner's first name. The front end replaces it before rendering.
CHILD = "{child}"

#: C2 — story lines are kept to the stricter of the two A.2 story limits in
#: both languages.
STORY_LINE_LIMIT = 100
PROMPT_LIMITS: dict[str, int] = dict(LENGTH_LIMITS["prompt"])
HINT_LIMITS: dict[str, int] = dict(LENGTH_LIMITS["hint"])

#: Mirrors the validator's leak floor: shorter answers are not leak-checked.
MIN_LEAK_LENGTH = 3

#: Never more than this many ``ask`` steps in a row (the validator allows 3).
MAX_ASKS_IN_A_ROW = 2

#: A story with fewer questions than this is not worth publishing.
MIN_QUESTIONS = 2

#: The most MCQs a story takes from a quiz unit that covers several lessons.
MAX_PICKED_MCQS = 4

#: The issue code of a copy-fallback: one language copied under the other's key.
MISSING_TRANSLATION = "missing_translation"

CHOICE_IDS = "abcdef"
MAX_OBJECTIVES = 3
MINIGAME_ID = "g1"
TUTOR_ID = "margo"
MENTOR_ID = "mentor"
PEER_ID = "peer"

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_DERIVED_ID_RE = re.compile(r"^q\d+$")
_FIGURE_MARKER_RE = re.compile(r"\{\{\s*source_image:[^}]*\}\}|⟦FIG\d+⟧")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|`)")
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.MULTILINE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ0-9«\"(])")
_AI_DISCLOSURE_RE = re.compile(r"\b(ai|ia|robot|intelligence artificielle)\b", re.IGNORECASE)


# --------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------


def other_language(language: str) -> str:
    return "en" if language == "fr" else "fr"


def language_pair(language: str) -> dict[str, str]:
    """C1: a story generated for ``language`` teaches in it, the other is home."""
    return {"target": language, "home": other_language(language)}


def story_slug(module_unit_id: uuid.UUID, language: str) -> str:
    """C8: a reserved namespace that can never collide with authored weeks."""
    return f"lesson-{module_unit_id.hex}-{language}"


def norm(text: Any) -> str:
    """The validator's leak normaliser: lowercase, no spaces, folded minus."""
    return re.sub(r"\s+", "", str(text)).lower().replace(maths.MINUS, "-")


def clean_text(text: Any) -> str:
    """Lesson prose as plain text: no figure markers, no markdown, one line."""
    if text is None:
        return ""
    value = str(text)
    value = _FIGURE_MARKER_RE.sub("", value)
    value = _MD_LINK_RE.sub(r"\1", value)
    value = _MD_HEADING_RE.sub("", value)
    value = _MD_BULLET_RE.sub("", value)
    value = _MD_EMPHASIS_RE.sub("", value)
    return " ".join(value.split())


def split_sentences(text: str, max_rows: int = 4) -> list[str]:
    """Split prose into at most ``max_rows`` rows, merging the overflow."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    if len(sentences) <= max_rows:
        return sentences
    head = sentences[: max_rows - 1]
    head.append(" ".join(sentences[max_rows - 1 :]))
    return head


def truncate(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters at a word boundary.

    Never splits the ``{child}`` placeholder: a cut that would leave a dangling
    ``{`` backs up to before it.
    """
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    if cut.rfind("{") > cut.rfind("}"):
        cut = cut[: cut.rfind("{")]
    return cut.rstrip(" ,;:-–—(«\"'") + "…"


def _as_str(value: Any) -> str:
    if value is None or isinstance(value, dict | list):
        return ""
    return " ".join(str(value).split())


def _items(value: Any) -> list[Any]:
    """A model value that should be a list, whatever shape it came in.

    A lone object or string is one item; anything else that is not a list
    (a number, ``null``, ``true``) is no items. The builders iterate, slice
    and index what this returns, so a model that writes ``"hints": {...}``
    instead of ``"hints": [{...}]`` costs a hint, not the whole story.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, dict) or (isinstance(value, str) and value.strip()):
        return [value]
    return []


def _get(value: Any, key: str) -> Any:
    """``value[key]`` when ``value`` is an object, else ``None``."""
    return value.get(key) if isinstance(value, dict) else None


# --------------------------------------------------------------------------
# Copy-fallbacks (C1): recorded, never silent
# --------------------------------------------------------------------------


class _Translations:
    """The copy-fallbacks seen while one story is being built."""

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add(self, path: str, message: str) -> None:
        if not any(i.path == path for i in self.issues):
            self.issues.append(
                ValidationIssue(
                    severity="error", code=MISSING_TRANSLATION, path=path, message=message
                )
            )

    def mark(self) -> int:
        return len(self.issues)

    def rollback(self, mark: int) -> None:
        """Forget what was recorded for an item that was then left out."""
        del self.issues[mark:]


_SINK: ContextVar[_Translations | None] = ContextVar("story_translation_sink", default=None)

_LANGUAGE_NAMES = {"en": "English", "fr": "French"}


def note_missing(path: str | None, lang: str, detail: str = "") -> None:
    """Record that ``lang`` was copied from the other language at ``path``.

    ``path`` names the field of the model's JSON, so the repair loop can say
    exactly what to write. A ``None`` path (lesson data the model does not
    write) is not recorded.
    """
    sink = _SINK.get()
    if sink is None or path is None:
        return
    message = detail or (
        f"no {_LANGUAGE_NAMES[lang]} text: the {_LANGUAGE_NAMES[other_language(lang)]}"
        " text was copied in its place"
    )
    sink.add(f"{path}.{lang}" if lang else path, message)


@contextmanager
def _unless_kept() -> Iterator[list[bool]]:
    """Drop what was recorded inside the block unless the item was kept.

    Usage: ``with _unless_kept() as kept: ...; kept.append(True)``.
    """
    sink = _SINK.get()
    mark = sink.mark() if sink is not None else 0
    kept: list[bool] = []
    yield kept
    if sink is not None and not kept:
        sink.rollback(mark)


def _text_parts(value: Any) -> tuple[dict[str, str], bool]:
    """The non-empty languages of a model text value, and whether it was a bare string."""
    if isinstance(value, dict):
        out = {lang: _as_str(value.get(lang)) for lang in LANGS}
        return {lang: text for lang, text in out.items() if text}, False
    if isinstance(value, str) and value.strip():
        return {lang: " ".join(value.split()) for lang in LANGS}, True
    return {}, False


def text_object(
    value: Any,
    fallback: dict[str, str] | None = None,
    *,
    path: str | None = None,
) -> dict[str, str] | None:
    """Coerce a model value into ``{"en": ..., "fr": ...}``.

    A missing language is filled from ``fallback``, then from the other
    language (the player hides a home line identical to the target line).
    Returns ``None`` when there is no text at all. A copy from the other
    language, or a bare string standing for both, is recorded at ``path``.
    """
    out, bare = _text_parts(value)
    if bare and path is not None:
        sink = _SINK.get()
        if sink is not None:
            sink.add(path, 'one string instead of an {"en": ..., "fr": ...} object')
    if fallback:
        for lang in LANGS:
            if not out.get(lang) and fallback.get(lang):
                out[lang] = fallback[lang]
    if not out:
        return None
    for lang in LANGS:
        if not out.get(lang):
            out[lang] = out[other_language(lang)]
            note_missing(path, lang)
    return {lang: out[lang] for lang in LANGS}


def capped(obj: dict[str, str] | None, limits: dict[str, int] | int) -> dict[str, str] | None:
    if obj is None:
        return None
    return {
        lang: truncate(obj[lang], limits if isinstance(limits, int) else limits[lang])
        for lang in LANGS
    }


def _row_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [_as_str(v) for v in value if _as_str(v)]


def parallel_rows(en: Any, fr: Any, *, path: str | None = None) -> dict[str, list[str]] | None:
    """Two row lists of equal length (C.3), or ``None`` when both are empty.

    A language with no rows gets a copy of the other's, recorded at ``path``.
    """
    rows = {"en": _row_list(en), "fr": _row_list(fr)}
    if not rows["en"] and not rows["fr"]:
        return None
    for lang in LANGS:
        if not rows[lang]:
            rows[lang] = list(rows[other_language(lang)])
            note_missing(path, lang)
    size = min(len(rows["en"]), len(rows["fr"]))
    return {lang: rows[lang][:size] for lang in LANGS}


def _slug(value: str, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40]
    return slug if slug.startswith(prefix) else f"{prefix}{slug}" if slug else ""


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@dataclass
class QuizMcq:
    """One stored quiz MCQ, as the story uses it."""

    ref: str  # the story question id, "q1", "q2", ...
    source_id: str  # the quiz's own question id
    stem: str
    options: list[str]
    correct_index: int
    explanation: str = ""
    #: Track A's ``option_misconceptions``: why each wrong option is wrong,
    #: positional, ``None`` at the correct index. Absent on older quizzes.
    option_misconceptions: list[str | None] = field(default_factory=list)

    @property
    def correct_text(self) -> str:
        return self.options[self.correct_index]

    def letter(self, index: int) -> str:
        return CHOICE_IDS[index]


@dataclass
class LessonStoryContext:
    """Everything the builder needs about the unit; no database access."""

    module_unit_id: uuid.UUID
    language: str
    unit_number: str
    unit_title: dict[str, str]
    module_title: dict[str, str]
    course_title: dict[str, str]
    module_number: int
    lesson: dict[str, Any]
    mcqs: list[QuizMcq] = field(default_factory=list)
    has_quiz: bool = False
    is_kids: bool = False
    #: Where ``mcqs`` come from. ``"unit"``: the lesson unit's own quiz, every
    #: MCQ of which becomes a question. ``"covering"``: the quiz of the quiz
    #: unit that covers several lessons; its MCQs are *candidates*, and only
    #: those the model picks as testing this lesson (at most
    #: :data:`MAX_PICKED_MCQS`) become questions.
    quiz_scope: str = "unit"
    #: The unit number of the quiz unit the MCQs come from, for ``sources``.
    quiz_unit_number: str | None = None

    @property
    def picks_from_quiz(self) -> bool:
        return self.quiz_scope == "covering" and bool(self.mcqs)

    @property
    def target(self) -> str:
        return self.language

    @property
    def home(self) -> str:
        return other_language(self.language)

    @property
    def slug(self) -> str:
        return story_slug(self.module_unit_id, self.language)

    def lesson_list(self, key: str) -> list[str]:
        return [clean_text(v) for v in _row_list(self.lesson.get(key)) if clean_text(v)]

    def lesson_text(self, key: str) -> str:
        return clean_text(self.lesson.get(key))


def _options_duplicate(options: Iterable[str]) -> bool:
    seen: set[str] = set()
    for option in options:
        key = norm(option)
        if key in seen:
            return True
        seen.add(key)
    return False


def _leaks(answer_text: str, haystack: str) -> bool:
    needle = norm(answer_text)
    return len(needle) >= MIN_LEAK_LENGTH and needle in norm(haystack)


def parse_quiz_mcqs(raw_questions: Any) -> tuple[list[QuizMcq], list[dict[str, str]]]:
    """Lift a unit quiz's stored questions into :class:`QuizMcq` views.

    Reads the stored JSON directly rather than through ``QuizQuestion`` so the
    optional ``option_misconceptions`` field survives whether or not the
    schema declares it yet.

    A stored MCQ is dropped — and reported, never shipped — when it is
    malformed, when two of its options are the same text (the honest,
    deterministic form of "more than one correct answer"), or when its correct
    option's text appears in its own stem.
    """
    kept: list[QuizMcq] = []
    dropped: list[dict[str, str]] = []
    if not isinstance(raw_questions, list):
        return kept, dropped

    for index, raw in enumerate(raw_questions):
        source_id = str((raw or {}).get("id") or f"#{index + 1}") if isinstance(raw, dict) else ""
        if not isinstance(raw, dict):
            dropped.append({"question": f"#{index + 1}", "reason": "not_an_object"})
            continue
        stem = _as_str(raw.get("question"))
        options = raw.get("options")
        answer = raw.get("correct_answer")
        if isinstance(answer, str) and answer.strip().isdigit():
            answer = int(answer.strip())
        if (
            not stem
            or not isinstance(options, list)
            or not 2 <= len(options) <= len(CHOICE_IDS)
            or not all(isinstance(o, str | int | float) and _as_str(o) for o in options)
            or not isinstance(answer, int)
            or isinstance(answer, bool)
            or not 0 <= answer < len(options)
        ):
            dropped.append({"question": source_id, "reason": "malformed"})
            continue
        option_texts = [_as_str(o) for o in options]
        if _options_duplicate(option_texts):
            dropped.append({"question": source_id, "reason": "duplicate_options"})
            continue
        if _leaks(option_texts[answer], stem):
            dropped.append({"question": source_id, "reason": "answer_in_stem"})
            continue
        misconceptions_raw = raw.get("option_misconceptions")
        option_misconceptions: list[str | None] = []
        if isinstance(misconceptions_raw, list):
            option_misconceptions = [
                (_as_str(m) or None) if i != answer else None
                for i, m in enumerate(misconceptions_raw[: len(option_texts)])
            ]
        kept.append(
            QuizMcq(
                ref=f"q{len(kept) + 1}",
                source_id=source_id,
                stem=stem,
                options=option_texts,
                correct_index=answer,
                explanation=_as_str(raw.get("explanation")),
                option_misconceptions=option_misconceptions,
            )
        )

    if dropped:
        logger.warning("Stored quiz MCQs left out of the story", dropped=dropped)
    return kept, dropped


# --------------------------------------------------------------------------
# Misconceptions
# --------------------------------------------------------------------------


class _Misconceptions:
    """The declared misconceptions, with id hygiene and on-demand synthesis.

    Every misconception id a choice, trap or mini-game item uses must be
    declared (C.1 ``dangling_misconception``). Model ids are slugged and
    de-duplicated; a reference to an undeclared id is resolved by declaring
    it from the text it was attached to, as the design's Layer 1 prescribes.
    """

    def __init__(self, raw: Any) -> None:
        self.entries: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._alias: dict[str, str] = {}
        #: Copy-fallbacks per declared id, reported only for the ids a story
        #: ends up using: ``(path, language copied into, detail)``.
        self._missing: dict[str, list[tuple[str, str, str]]] = {}
        for index, item in enumerate(_items(raw)):
            if not isinstance(item, dict):
                continue
            parts, _bare = _text_parts({"en": item.get("en"), "fr": item.get("fr")})
            text = text_object(parts)
            raw_id = _as_str(item.get("id"))
            if text is None:
                continue
            path = f"misconceptions[{raw_id or index}]"
            missing = [(path, lang, "") for lang in LANGS if lang not in parts]
            self._declare(raw_id or text["en"], text, missing)

    def _declare(
        self,
        raw_id: str,
        text: dict[str, str],
        missing: list[tuple[str, str, str]] | None = None,
    ) -> str:
        base = _slug(raw_id, "m_") or "m_misconception"
        new_id, n = base, 2
        while new_id in self._by_id:
            new_id, n = f"{base}_{n}", n + 1
        entry = {"id": new_id, "en": text["en"], "fr": text["fr"], "from_test": False}
        self.entries.append(entry)
        self._by_id[new_id] = entry
        if missing:
            self._missing[new_id] = list(missing)
        if raw_id and raw_id not in self._alias:
            self._alias[raw_id] = new_id
        return new_id

    def resolve(
        self,
        raw_id: Any,
        fallback: dict[str, str] | None = None,
        missing: list[tuple[str, str, str]] | None = None,
    ) -> str | None:
        """The declared id for ``raw_id``; declares it from ``fallback`` if new.

        ``missing`` records the copy-fallbacks in ``fallback`` itself, if any.
        """
        key = _as_str(raw_id)
        if not key:
            return None
        if key in self._alias:
            return self._alias[key]
        if key in self._by_id:
            return key
        if fallback is None:
            return None
        return self._declare(key, fallback, missing)

    def declare(
        self,
        raw_id: str,
        text: dict[str, str],
        missing: list[tuple[str, str, str]] | None = None,
    ) -> str:
        return self.resolve(raw_id, text, missing) or self._declare(raw_id, text, missing)

    def used_only(self, used: set[str]) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["id"] in used]

    def report_missing(self, used: set[str]) -> None:
        """Record the copy-fallbacks of the misconceptions the story uses."""
        for entry in self.used_only(used):
            for path, lang, detail in self._missing.get(entry["id"], []):
                note_missing(path, lang, detail)


def _wrong_choice_statement(option: dict[str, str]) -> dict[str, str]:
    """A misconception worded from the wrong option it is attached to."""
    return {
        "en": f"Believes that “{option['en']}” is the right answer.",
        "fr": f"Pense que « {option['fr']} » est la bonne réponse.",
    }


# --------------------------------------------------------------------------
# Questions
# --------------------------------------------------------------------------

_SITUATION_PROMPT = {
    "en": "Read the situation above, then choose the best answer.",
    "fr": "Lis la situation ci-dessus, puis choisis la meilleure réponse.",
}
_SITUATION_TITLE = {"en": "The situation", "fr": "La situation"}


def situation_step_id(question_id: str) -> str:
    return f"situation-{question_id}"


@dataclass
class _BuiltQuestion:
    doc: dict[str, Any]
    derived: bool
    #: A long verbatim quiz stem, shown in a concept step just before the ask
    #: because the prompt itself is length-capped.
    situation: dict[str, str] | None = None


def _index_for_option(value: Any, options: list[str], ids: list[str]) -> int | None:
    """Turn a model's reference to an option (id, letter, index, text) into an index."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value < len(options) else None
    text = _as_str(value)
    if not text:
        return None
    if text in ids:
        return ids.index(text)
    lowered = text.lower()
    if len(lowered) == 1 and lowered in CHOICE_IDS[: len(options)]:
        return CHOICE_IDS.index(lowered)
    if text.isdigit() and int(text) < len(options):
        return int(text)
    for index, option in enumerate(options):
        if norm(option) == norm(text):
            return index
    return None


def _hint(value: Any, path: str | None = None) -> dict[str, str] | None:
    return capped(text_object(value, path=path), HINT_LIMITS)


def _leak_free(obj: dict[str, str] | None, answers: list[str]) -> bool:
    if obj is None:
        return True
    return not any(_leaks(a, v) for a in answers for v in obj.values())


def _kept_hint(value: Any, path: str, answers: list[str]) -> dict[str, str] | None:
    """A hint that does not give the answer away; its copy-fallbacks only if kept."""
    with _unless_kept() as kept:
        hint = _hint(value, path)
        if hint is None or not _leak_free(hint, answers):
            return None
        kept.append(True)
        return hint


def _home_options(spec: dict[str, Any], mcq: QuizMcq, home: str, path: str) -> list[str]:
    """The model's home-language options, else the quiz's own (recorded)."""
    count = len(mcq.options)
    raw = spec.get("options_home")
    home_options = _row_list(raw) if isinstance(raw, list) else []
    if len(home_options) != count:
        note_missing(
            f"{path}.options_home",
            "",
            f"expected {count} options translated into {_LANGUAGE_NAMES[home]};"
            f" the {_LANGUAGE_NAMES[other_language(home)]} options were copied",
        )
        return list(mcq.options)
    if _options_duplicate(home_options):
        note_missing(
            f"{path}.options_home",
            "",
            "two translated options are the same; the quiz's own options were copied",
        )
        return list(mcq.options)
    return home_options


def _derived_question(
    mcq: QuizMcq,
    spec: dict[str, Any],
    ctx: LessonStoryContext,
    registry: _Misconceptions,
    objective_map: dict[str, str],
) -> _BuiltQuestion | None:
    """One stored quiz MCQ as a story choice question, verbatim in the target language.

    The model only writes the home-language side; every gap there is copied
    from the quiz and recorded as ``missing_translation`` at the spine path
    ``derived[<ref>]...``.

    A stem too long for a prompt keeps the generic lead-in as ``prompt``, is
    shown in full by a "situation" concept step just before the ask, and is
    also carried verbatim on the question as ``stem`` (contract X5), a text
    object. ``stem`` is text the learner reads before answering, so the shared
    MCQ checks run their answer-leak check against it like the prompt;
    :func:`publishable` already does so here.
    """
    target, home = ctx.target, ctx.home
    count = len(mcq.options)
    ids = list(CHOICE_IDS[:count])
    path = f"derived[{mcq.ref}]"

    # Home-language side: the only part the model writes.
    home_options = _home_options(spec, mcq, home, path)
    choices: list[dict[str, Any]] = []
    for index in range(count):
        choices.append({"id": ids[index], target: mcq.options[index], home: home_options[index]})
    correct = choices[mcq.correct_index]
    correct_texts = [correct["en"], correct["fr"]]

    stem = {target: mcq.stem, home: _as_str(spec.get("prompt_home"))}
    if not stem[home]:
        note_missing(f"{path}.prompt_home", "", f"no {_LANGUAGE_NAMES[home]} translation")
        stem[home] = mcq.stem
    elif _leaks(correct["en"], stem[home]) or _leaks(correct["fr"], stem[home]):
        note_missing(
            f"{path}.prompt_home",
            "",
            "the translation names the correct answer; the quiz's own stem was used",
        )
        stem[home] = mcq.stem
    if not _leak_free(stem, correct_texts):
        return None

    situation = None
    prompt = {lang: stem[lang] for lang in LANGS}
    if any(len(prompt[lang]) > PROMPT_LIMITS[lang] for lang in LANGS):
        situation, prompt = stem, dict(_SITUATION_PROMPT)

    # Wrong options: a misconception and, when written, a targeted hint.
    distractors: dict[int, dict[str, Any]] = {}
    for item in _items(spec.get("distractors")):
        if isinstance(item, dict):
            index = _index_for_option(item.get("option"), mcq.options, ids)
            if index is not None and index != mcq.correct_index:
                distractors.setdefault(index, item)

    traps: list[dict[str, Any]] = []
    for index, choice in enumerate(choices):
        if index == mcq.correct_index:
            continue
        item = distractors.get(index, {})
        option_text = {"en": choice["en"], "fr": choice["fr"]}
        known = mcq.option_misconceptions[index] if index < len(mcq.option_misconceptions) else None
        # The course's own misconception text exists in the target language
        # only: declaring it copies that text under the home key too.
        known_missing = [
            (
                f"{path}.distractors[{ids[index]}].misconception",
                home,
                f"no misconception for this wrong option; the course's"
                f" {_LANGUAGE_NAMES[target]} wording was copied",
            )
        ]
        misconception = registry.resolve(
            item.get("misconception"),
            {lang: known for lang in LANGS} if known else _wrong_choice_statement(option_text),
            known_missing if known else None,
        )
        if misconception is None and known:
            misconception = registry.declare(
                f"m_{mcq.ref}_{ids[index]}", {"en": known, "fr": known}, known_missing
            )
        if misconception:
            choice["misconception"] = misconception
        if misconception:
            hint = _kept_hint(
                item.get("hint"), f"{path}.distractors[{ids[index]}].hint", correct_texts
            )
            if hint:
                traps.append({"answer": ids[index], "misconception": misconception, "hint": hint})

    hints = [h for h in [_kept_hint(spec.get("hint"), f"{path}.hint", correct_texts)] if h]
    question: dict[str, Any] = {
        "id": mcq.ref,
        "type": "choice",
        "objective": objective_map.get(_as_str(spec.get("objective"))),
        "calculator": False,
        "prompt": prompt,
        "answer": correct["id"],
        "choices": choices,
        "traps": traps,
        "hints": hints,
        "derived_from": mcq.source_id,
    }
    if situation is not None:
        question["stem"] = {lang: situation[lang] for lang in LANGS}
    if mcq.explanation:
        explanation_home = _as_str(spec.get("explanation_home"))
        if not explanation_home:
            note_missing(f"{path}.explanation_home", "", f"no {_LANGUAGE_NAMES[home]} translation")
        question["explanation"] = {
            target: mcq.explanation,
            home: explanation_home or mcq.explanation,
        }
    return _BuiltQuestion(doc=question, derived=True, situation=situation)


def _extra_choice(
    raw: dict[str, Any], registry: _Misconceptions, path: str
) -> dict[str, Any] | None:
    raw_choices = raw.get("choices")
    if not isinstance(raw_choices, list) or not 2 <= len(raw_choices) <= len(CHOICE_IDS):
        return None
    texts: list[dict[str, str]] = []
    raw_ids: list[str] = []
    raw_misconceptions: list[Any] = []
    for index, item in enumerate(raw_choices):
        if isinstance(item, dict):
            text = text_object(
                {"en": item.get("en"), "fr": item.get("fr")}, path=f"{path}.choices[{index}]"
            )
            raw_ids.append(_as_str(item.get("id")))
            raw_misconceptions.append(item.get("misconception"))
        else:
            text = text_object(item, path=f"{path}.choices[{index}]")
            raw_ids.append("")
            raw_misconceptions.append(None)
        if text is None:
            return None
        texts.append(text)
    if _options_duplicate(t["en"] for t in texts) or _options_duplicate(t["fr"] for t in texts):
        return None

    ids = list(CHOICE_IDS[: len(texts)])
    lookup_ids = [r or ids[i] for i, r in enumerate(raw_ids)]
    answer_index = _index_for_option(raw.get("answer"), [t["en"] for t in texts], lookup_ids)
    if answer_index is None:
        answer_index = _index_for_option(raw.get("answer"), [t["fr"] for t in texts], lookup_ids)
    if answer_index is None:
        return None
    answers = [texts[answer_index]["en"], texts[answer_index]["fr"]]

    choices: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        choice: dict[str, Any] = {"id": ids[index], "en": text["en"], "fr": text["fr"]}
        if index != answer_index:
            misconception = registry.resolve(
                raw_misconceptions[index], _wrong_choice_statement(text)
            )
            if misconception:
                choice["misconception"] = misconception
        choices.append(choice)

    traps: list[dict[str, Any]] = []
    for number, trap in enumerate(_items(raw.get("traps"))):
        if not isinstance(trap, dict):
            continue
        index = _index_for_option(trap.get("answer"), [t["en"] for t in texts], lookup_ids)
        if index is None or index == answer_index:
            continue
        misconception = choices[index].get("misconception") or registry.resolve(
            trap.get("misconception"), _wrong_choice_statement(texts[index])
        )
        if not misconception:
            continue
        hint = _kept_hint(trap.get("hint"), f"{path}.traps[{number}].hint", answers)
        if hint:
            traps.append({"answer": ids[index], "misconception": misconception, "hint": hint})
    return {"answer": ids[answer_index], "choices": choices, "traps": traps, "answers": answers}


def _extra_exact_text(
    raw: dict[str, Any], registry: _Misconceptions, path: str
) -> dict[str, Any] | None:
    answer = _as_str(raw.get("answer"))
    if not answer or len(answer) > 60:
        return None
    traps: list[dict[str, Any]] = []
    for number, trap in enumerate(_items(raw.get("traps"))):
        if not isinstance(trap, dict):
            continue
        wrong = _as_str(trap.get("answer"))
        if not wrong or norm(wrong) == norm(answer):
            continue
        misconception = registry.resolve(
            trap.get("misconception"),
            {
                "en": f"Answers “{wrong}” instead of the right term.",
                "fr": f"Répond « {wrong} » au lieu du bon terme.",
            },
        )
        if not misconception:
            continue
        hint = _kept_hint(trap.get("hint"), f"{path}.traps[{number}].hint", [answer])
        if hint:
            traps.append({"answer": wrong, "misconception": misconception, "hint": hint})
    return {"answer": answer, "traps": traps, "answers": [answer]}


def _extra_question(
    raw: Any,
    qid: str,
    registry: _Misconceptions,
    objective_map: dict[str, str],
) -> _BuiltQuestion | None:
    """A model-authored question, kept only if it is a choice or exact_text.

    Its copy-fallbacks are recorded at ``questions[<qid>]...`` only if the
    question is kept.
    """
    if not isinstance(raw, dict):
        return None
    with _unless_kept() as kept:
        question = _extra_question_body(raw, qid, registry, objective_map)
        if question is not None:
            kept.append(True)
        return question


def _extra_question_body(
    raw: dict[str, Any],
    qid: str,
    registry: _Misconceptions,
    objective_map: dict[str, str],
) -> _BuiltQuestion | None:
    path = f"questions[{qid}]"
    kind = _as_str(raw.get("type"))
    if kind not in ("choice", "exact_text"):
        return None
    prompt = capped(text_object(raw.get("prompt"), path=f"{path}.prompt"), PROMPT_LIMITS)
    if prompt is None:
        return None
    body = (
        _extra_choice(raw, registry, path)
        if kind == "choice"
        else _extra_exact_text(raw, registry, path)
    )
    if body is None:
        return None

    answers = body["answers"]
    if not _leak_free(prompt, answers):
        return None
    hints = [
        hint
        for hint in (
            _kept_hint(value, f"{path}.hints[{index}]", answers)
            for index, value in enumerate(_items(raw.get("hints"))[:2])
        )
        if hint
    ]

    question: dict[str, Any] = {
        "id": qid,
        "type": kind,
        "objective": objective_map.get(_as_str(raw.get("objective"))),
        "calculator": False,
        "prompt": prompt,
        "answer": body["answer"],
        "traps": body["traps"],
        "hints": hints,
    }
    if kind == "choice":
        question["choices"] = body["choices"]
    explanation = text_object(raw.get("explanation"), path=f"{path}.explanation")
    if explanation:
        question["explanation"] = explanation
    return _BuiltQuestion(doc=question, derived=False)


# --------------------------------------------------------------------------
# Objectives, exercises and coverage
# --------------------------------------------------------------------------


def _objectives(raw: Any, ctx: LessonStoryContext) -> tuple[list[dict], dict[str, str]]:
    objectives: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for index, item in enumerate(_items(raw)):
        if not isinstance(item, dict) or len(objectives) >= MAX_OBJECTIVES:
            continue
        text = text_object(
            {"en": item.get("en"), "fr": item.get("fr")}, path=f"objectives[{index}]"
        )
        if text is None:
            continue
        new_id = f"o{len(objectives) + 1}"
        objectives.append({"id": new_id, "en": text["en"], "fr": text["fr"]})
        raw_id = _as_str(item.get("id"))
        if raw_id:
            mapping.setdefault(raw_id, new_id)
        mapping.setdefault(new_id, new_id)
    if not objectives:
        objectives.append(
            {
                "id": "o1",
                "en": f"Understand: {ctx.unit_title['en']}",
                "fr": f"Comprendre : {ctx.unit_title['fr']}",
            }
        )
        mapping["o1"] = "o1"
    return objectives, mapping


def _exercise(
    raw: Any, exercise_id: str, objective_map: dict[str, str], path: str
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    with _unless_kept() as kept:
        exercise = _exercise_body(raw, exercise_id, objective_map, path)
        if exercise is not None:
            kept.append(True)
        return exercise


def _exercise_body(
    raw: dict[str, Any], exercise_id: str, objective_map: dict[str, str], path: str
) -> dict[str, Any] | None:
    prompt = capped(text_object(raw.get("prompt"), path=f"{path}.prompt"), PROMPT_LIMITS)
    if prompt is None:
        return None
    working_raw = raw.get("working") if isinstance(raw.get("working"), dict) else {}
    working = parallel_rows(working_raw.get("en"), working_raw.get("fr"), path=f"{path}.working")
    scheme = text_object(raw.get("mark_scheme"), path=f"{path}.mark_scheme") or {
        "en": "A clear answer that matches the lesson",
        "fr": "Une réponse claire et fidèle à la leçon",
    }
    exercise: dict[str, Any] = {
        "id": exercise_id,
        "part": "A",
        "objective": objective_map.get(_as_str(raw.get("objective"))),
        "marks": 1,
        "calculator": False,
        "prompt": prompt,
        "mark_scheme": [{"code": "B1", "en": scheme["en"], "fr": scheme["fr"]}],
    }
    if working:
        exercise["working"] = working
    return exercise


def _fallback_exercise(
    objective: dict[str, Any], key_points: dict[str, list[str]] | None
) -> dict[str, Any]:
    """A reflection exercise for an objective the model left without one."""
    exercise: dict[str, Any] = {
        "id": f"R{objective['id']}",
        "part": "A",
        "objective": objective["id"],
        "marks": 1,
        "calculator": False,
        "prompt": {
            "en": truncate(f"On paper, explain in your own words: {objective['en']}", 160),
            "fr": truncate(f"Sur papier, explique avec tes mots : {objective['fr']}", 190),
        },
        "mark_scheme": [
            {
                "code": "B1",
                "en": "A clear explanation that matches the lesson",
                "fr": "Une explication claire et fidèle à la leçon",
            }
        ],
    }
    if key_points:
        exercise["working"] = copy.deepcopy(key_points)
    return exercise


def _rebalance(
    objectives: list[dict[str, Any]],
    questions: list[_BuiltQuestion],
    exercises: list[dict[str, Any]],
    key_points: dict[str, list[str]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Give every objective at least 2 questions and 1 exercise (C.5 warnings).

    Questions move from objectives with a surplus; an objective that cannot be
    covered is merged away. Objectives without an exercise borrow a surplus
    one, else get a reflection exercise.
    """
    objectives = list(objectives)
    ids = [o["id"] for o in objectives]

    def counts() -> dict[str, int]:
        out = dict.fromkeys(ids, 0)
        for q in questions:
            out[q.doc["objective"]] = out.get(q.doc["objective"], 0) + 1
        return out

    for q in questions:
        if q.doc.get("objective") not in ids:
            current = counts()
            q.doc["objective"] = min(ids, key=lambda i: (current[i], ids.index(i)))

    while True:
        current = counts()
        poor = [i for i in ids if current[i] < 2]
        if not poor or len(ids) == 1:
            break
        rich = [i for i in ids if current[i] > 2]
        target = poor[0]
        if rich:
            donor = max(rich, key=lambda i: current[i])
            mover = next(q for q in reversed(questions) if q.doc["objective"] == donor)
            mover.doc["objective"] = target
            continue
        # Nothing to borrow: merge the poorest objective into its neighbour.
        victim = min(poor, key=lambda i: (current[i], -ids.index(i)))
        ids.remove(victim)
        heir = min(ids, key=lambda i: (current[i], ids.index(i)))
        for q in questions:
            if q.doc["objective"] == victim:
                q.doc["objective"] = heir
        for exercise in exercises:
            if exercise.get("objective") == victim:
                exercise["objective"] = heir

    objectives = [o for o in objectives if o["id"] in ids]
    # Renumber o1..oN so ids stay tidy after a merge.
    renumber = {o["id"]: f"o{n + 1}" for n, o in enumerate(objectives)}
    for o in objectives:
        o["id"] = renumber[o["id"]]
    for q in questions:
        q.doc["objective"] = renumber[q.doc["objective"]]

    final_ids = [o["id"] for o in objectives]
    kept: list[dict[str, Any]] = []
    for exercise in exercises:
        exercise["objective"] = renumber.get(exercise.get("objective") or "")
        kept.append(exercise)
    for exercise in kept:
        if exercise["objective"] not in final_ids:
            covered = {e["objective"] for e in kept}
            missing = [i for i in final_ids if i not in covered]
            exercise["objective"] = missing[0] if missing else final_ids[0]
    for objective_id in final_ids:
        if not any(e["objective"] == objective_id for e in kept):
            per = {i: sum(1 for e in kept if e["objective"] == i) for i in final_ids}
            donors = [e for e in kept if per[e["objective"]] > 1]
            if donors:
                donors[-1]["objective"] = objective_id
            else:
                objective = next(o for o in objectives if o["id"] == objective_id)
                kept.append(_fallback_exercise(objective, key_points))
    return objectives, kept


# --------------------------------------------------------------------------
# Mini-game (C5: engine "catch", items rounds)
# --------------------------------------------------------------------------


def _minigame(
    raw: Any, registry: _Misconceptions, key_points: dict[str, list[str]] | None
) -> dict[str, Any] | None:
    raw = raw if isinstance(raw, dict) else {}
    rounds: list[dict[str, Any]] = []
    for round_index, raw_round in enumerate(_items(raw.get("rounds"))):
        if not isinstance(raw_round, dict):
            continue
        round_path = f"minigame.rounds[{round_index}]"
        with _unless_kept() as round_kept:
            items: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item_index, raw_item in enumerate(_items(raw_round.get("items"))):
                if not isinstance(raw_item, dict):
                    continue
                with _unless_kept() as item_kept:
                    label = text_object(
                        raw_item.get("label"), path=f"{round_path}.items[{item_index}].label"
                    )
                    if label is None or norm(label["en"]) in seen:
                        continue
                    if raw_item.get("correct") is True:
                        items.append({"label": label, "correct": True})
                    else:
                        trap = registry.resolve(
                            raw_item.get("trap"),
                            {"en": f"Believes: {label['en']}", "fr": f"Croit que : {label['fr']}"},
                        )
                        if not trap:
                            continue  # a wrong item must name the trap it represents
                        items.append({"label": label, "correct": False, "trap": trap})
                    seen.add(norm(label["en"]))
                    item_kept.append(True)
            if any(item["correct"] for item in items):
                prompt = text_object(raw_round.get("prompt"), path=f"{round_path}.prompt") or {
                    "en": "Catch the statements that are true.",
                    "fr": "Attrape les affirmations justes.",
                }
                rounds.append({"prompt": prompt, "items": items})
                round_kept.append(True)
        if len(rounds) >= 4:
            break

    if not rounds and key_points and key_points["en"]:
        # Fallback: the lesson's own takeaways, every one of them true.
        for start in range(0, min(len(key_points["en"]), 6), 3):
            rounds.append(
                {
                    "prompt": {
                        "en": "Catch the key points of the lesson.",
                        "fr": "Attrape les points clés de la leçon.",
                    },
                    "items": [
                        {"label": {"en": en, "fr": fr}, "correct": True}
                        for en, fr in zip(
                            key_points["en"][start : start + 3],
                            key_points["fr"][start : start + 3],
                            strict=True,
                        )
                    ],
                }
            )
    if not rounds:
        return None

    return {
        "id": MINIGAME_ID,
        "engine": "catch",
        "title": text_object(raw.get("title"), path="minigame.title")
        or {"en": "Quick catch", "fr": "Attrape rapide"},
        "instruction": text_object(raw.get("instruction"), path="minigame.instruction")
        or {
            "en": "Catch only the right items. Let the traps fall!",
            "fr": "Attrape seulement les bonnes réponses. Laisse tomber les pièges !",
        },
        "hint_after_wrong": _hint(raw.get("hint_after_wrong"), "minigame.hint_after_wrong")
        or {
            "en": "Think back to the lesson before you catch.",
            "fr": "Repense à la leçon avant d'attraper.",
        },
        "rounds": rounds,
        "points": {"per_correct": 1},
    }


# --------------------------------------------------------------------------
# Cast, lines and layout
# --------------------------------------------------------------------------


def _character_name(raw: Any, default: str) -> str:
    name = _as_str(raw)
    if not name or len(name) > 40 or "{" in name or "}" in name:
        return default
    return name


def _cast(spine: dict[str, Any], ctx: LessonStoryContext) -> list[dict[str, Any]]:
    names = spine.get("characters") if isinstance(spine.get("characters"), dict) else {}
    if ctx.is_kids:
        mentor = {
            "id": MENTOR_ID,
            "name": _character_name(
                names.get("mentor"), "M. Kaboré" if ctx.target == "fr" else "Mr Kaboré"
            ),
            "kind": "adult",
            "art": "mr_kabore",
        }
        peer = {
            "id": PEER_ID,
            "name": _character_name(names.get("peer"), "Awa"),
            "kind": "child",
            "art": "friend",
        }
    else:
        mentor = {
            "id": MENTOR_ID,
            "name": _character_name(names.get("mentor"), "Dr Kaboré"),
            "kind": "adult",
            "art": "mr_kabore",
        }
        peer = {
            "id": PEER_ID,
            "name": _character_name(names.get("peer"), "Awa"),
            "kind": "adult",
            "art": "maman_olivia",
        }
    margo = {"id": TUTOR_ID, "name": "Margo", "kind": "ai_tutor", "art": "margo"}
    return [margo, mentor, peer]


def _line(kind: str, value: dict[str, str] | None, who: str | None = None) -> dict | None:
    """A narrate/say step, capped at C2's 100 characters in both languages."""
    if value is None:
        return None
    step: dict[str, Any] = {"type": kind}
    if who:
        step["who"] = who
    step["en"] = truncate(value["en"], STORY_LINE_LIMIT)
    step["fr"] = truncate(value["fr"], STORY_LINE_LIMIT)
    return step


_BRIDGES = (
    (
        {
            "en": "Keep going, {child}. Here is the next one.",
            "fr": "Continue, {child}. Voici la suivante.",
        }
    ),
    ({"en": "Take a breath. One more question.", "fr": "Respire un coup. Encore une question."}),
    ({"en": "Good work so far, {child}.", "fr": "Beau travail jusqu'ici, {child}."}),
)


class _Layout:
    """Builds chapters while keeping asks spread out (C.5)."""

    def __init__(self, ctx: LessonStoryContext) -> None:
        self.ctx = ctx
        self.chapters: list[dict[str, Any]] = []
        self._scene_count = 0
        self._concept_count = 0
        self._bridge = 0

    def chapter(self, title: dict[str, str]) -> dict[str, Any]:
        chapter = {"id": f"ch{len(self.chapters) + 1}", "title": title, "scenes": []}
        self.chapters.append(chapter)
        return chapter

    def scene(self, chapter: dict[str, Any], place: str) -> dict[str, Any]:
        self._scene_count += 1
        scene: dict[str, Any] = {"id": f"s{self._scene_count}", "place": place, "steps": []}
        chapter["scenes"].append(scene)
        return scene

    def concept(self, title: dict[str, str], rows: dict[str, list[str]]) -> dict[str, Any]:
        self._concept_count += 1
        return {
            "type": "concept",
            "id": f"c{self._concept_count}",
            "title": title,
            "en": list(rows["en"]),
            "fr": list(rows["fr"]),
        }

    def situation(self, question: _BuiltQuestion) -> dict[str, Any]:
        """The full quiz stem, shown just before a question whose prompt is capped."""
        assert question.situation is not None
        return {
            "type": "concept",
            "id": situation_step_id(question.doc["id"]),
            "title": dict(_SITUATION_TITLE),
            "en": [question.situation["en"]],
            "fr": [question.situation["fr"]],
        }

    def bridge(self) -> dict[str, Any]:
        text = _BRIDGES[self._bridge % len(_BRIDGES)]
        self._bridge += 1
        return _line("say", text, TUTOR_ID) or {}

    def enforce_spacing(self) -> None:
        """Insert a bridge line before any ask that would make the run too long.

        The run is counted over the flattened story, across scene and chapter
        boundaries, exactly as the validator counts it.
        """
        run = 0
        for chapter in self.chapters:
            for scene in chapter["scenes"]:
                steps: list[dict[str, Any]] = []
                for step in scene["steps"]:
                    if step["type"] == "ask":
                        if run >= MAX_ASKS_IN_A_ROW:
                            steps.append(self.bridge())
                            run = 0
                        run += 1
                    else:
                        run = 0
                    steps.append(step)
                scene["steps"] = steps


def _image_step(ctx: LessonStoryContext) -> dict[str, Any] | None:
    """At most one ``show`` step, and only a real lesson figure (``image``)."""
    for ref in _items(ctx.lesson.get("source_image_refs")):
        if not isinstance(ref, dict) or not _as_str(ref.get("id")):
            continue
        params: dict[str, Any] = {"source_image_id": _as_str(ref.get("id"))}
        if ref.get("figure_number"):
            params["figure_number"] = _as_str(ref.get("figure_number"))
        alt = text_object({"en": ref.get("alt_text_en"), "fr": ref.get("alt_text_fr")})
        if alt:
            params["alt"] = alt
        step: dict[str, Any] = {"type": "show", "visual": "image", "params": params}
        caption = text_object(
            {"en": ref.get("caption_en"), "fr": ref.get("caption_fr")},
            fallback={"en": _as_str(ref.get("caption")), "fr": _as_str(ref.get("caption"))},
        )
        if caption:
            step["caption"] = caption
        return step
    return None


def _concept_blocks(spine: dict[str, Any], ctx: LessonStoryContext) -> list[dict[str, Any]]:
    """One block per lesson concept: model rows, else the lesson's own prose.

    The lesson's prose exists in the target language only, so falling back to
    it copies that language under the home key: recorded at ``concepts``.
    """
    blocks: list[dict[str, Any]] = []
    for index, raw in enumerate(_items(spine.get("concepts"))):
        if not isinstance(raw, dict):
            continue
        path = f"concepts[{index}]"
        with _unless_kept() as kept:
            rows = parallel_rows(raw.get("en"), raw.get("fr"), path=path)
            if rows is None:
                continue
            title = text_object(raw.get("title"), path=f"{path}.title") or {
                "en": f"Key idea {len(blocks) + 1}",
                "fr": f"Idée clé {len(blocks) + 1}",
            }
            blocks.append({"title": title, "rows": rows})
            kept.append(True)
    if blocks:
        return blocks
    for number, paragraph in enumerate(ctx.lesson_list("concepts"), start=1):
        rows = split_sentences(paragraph)
        if rows:
            blocks.append(
                {
                    "title": {"en": f"Key idea {number}", "fr": f"Idée clé {number}"},
                    "rows": {"en": rows, "fr": list(rows)},
                }
            )
    if blocks:
        note_missing(
            "concepts",
            "",
            f"no concept rows: the lesson's {_LANGUAGE_NAMES[ctx.target]} text was used for"
            " both languages",
        )
    return blocks


def _key_points(spine: dict[str, Any], ctx: LessonStoryContext) -> dict[str, list[str]] | None:
    """The lesson's takeaways, verbatim in the target language.

    Read from ``content["key_points"]`` directly — ``extract_lesson_text``
    silently drops them.
    """
    target_rows = ctx.lesson_list("key_points")
    if not target_rows:
        return None
    home_rows = _row_list(spine.get("key_points_home"))
    if len(home_rows) != len(target_rows):
        note_missing(
            "key_points_home",
            "",
            f"expected {len(target_rows)} key points translated into"
            f" {_LANGUAGE_NAMES[ctx.home]}; the lesson's own were copied",
        )
        home_rows = list(target_rows)
    return {ctx.target: target_rows, ctx.home: home_rows}


def _example_block(spine: dict[str, Any], ctx: LessonStoryContext) -> dict[str, Any] | None:
    raw = spine.get("example") if isinstance(spine.get("example"), dict) else {}
    rows = parallel_rows(raw.get("en"), raw.get("fr"), path="example")
    if rows is None:
        target_rows = split_sentences(ctx.lesson_text("aof_example"))
        if not target_rows:
            return None
        note_missing(
            "example",
            "",
            f"no example rows: the lesson's {_LANGUAGE_NAMES[ctx.target]} field example was"
            " used for both languages",
        )
        rows = {"en": target_rows, "fr": list(target_rows)}
    place = _as_str(raw.get("place"))
    if place not in PLACES:
        place = "school_yard" if ctx.is_kids else "market"
    title = text_object(raw.get("title"), path="example.title") or {
        "en": "An example from the field",
        "fr": "Un exemple de terrain",
    }
    return {"title": title, "rows": rows, "place": place}


def _story_lines(spine: dict[str, Any]) -> dict[str, Any]:
    raw = spine.get("story") if isinstance(spine.get("story"), dict) else {}
    lines: dict[str, Any] = {
        key: text_object(raw.get(key), path=f"story.{key}")
        for key in ("opening", "mentor_intro", "example_intro", "wrap_up")
    }
    dialogue = []
    for index, item in enumerate(_items(raw.get("example_dialogue"))):
        if len(dialogue) >= 3:
            break
        if isinstance(item, dict):
            text = text_object(
                {"en": item.get("en"), "fr": item.get("fr")},
                path=f"story.example_dialogue[{index}]",
            )
            speaker = _as_str(item.get("who")).lower()
            who = PEER_ID if speaker in (PEER_ID, "colleague", "friend") else MENTOR_ID
            if text:
                dialogue.append((who, text))
    lines["example_dialogue"] = dialogue
    return lines


def _chapter_titles(spine: dict[str, Any], ctx: LessonStoryContext) -> list[dict[str, str]]:
    defaults = [
        {"en": "Your mission", "fr": "Ta mission"},
        {"en": "In the field", "fr": "Sur le terrain"},
        {"en": "Your turn", "fr": "À toi de jouer"},
    ]
    raw = spine.get("chapter_titles")
    titles = []
    for index, default in enumerate(defaults):
        value = raw[index] if isinstance(raw, list) and index < len(raw) else None
        titles.append(text_object(value, path=f"chapter_titles[{index}]") or default)
    return titles


def _distribute(items: list[Any], slots: int) -> list[list[Any]]:
    """Split ``items`` into ``slots`` consecutive groups, earliest groups fullest."""
    if slots <= 0:
        return []
    size = math.ceil(len(items) / slots) if items else 0
    return [items[i * size : (i + 1) * size] for i in range(slots)]


def _layout(
    ctx: LessonStoryContext,
    spine: dict[str, Any],
    objectives: list[dict[str, Any]],
    questions: list[_BuiltQuestion],
    exercises: list[dict[str, Any]],
    minigame: dict[str, Any] | None,
    key_points: dict[str, list[str]] | None,
) -> list[dict[str, Any]]:
    layout = _Layout(ctx)
    lines = _story_lines(spine)
    titles = _chapter_titles(spine, ctx)
    study_place = "classroom" if ctx.is_kids else "desk"

    def ask_steps(group: list[_BuiltQuestion]) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for q in group:
            if q.situation:
                steps.append(layout.situation(q))
            steps.append({"type": "ask", "ref": q.doc["id"]})
        return steps

    def scene_objective(scene: dict[str, Any], group: list[_BuiltQuestion]) -> None:
        if group and group[0].doc.get("objective"):
            scene["objective"] = group[0].doc["objective"]

    concepts = _concept_blocks(spine, ctx)
    example = _example_block(spine, ctx)
    # Teaching blocks, in lesson order; questions follow the blocks.
    blocks: list[tuple[str, Any]] = [("concept", c) for c in concepts]
    if example:
        blocks.append(("example", example))
    if key_points:
        blocks.append(("key_points", key_points))
    groups = _distribute(questions, max(len(blocks), 1))
    first_half = math.ceil(len(concepts) / 2)
    your_turn: dict[str, Any] | None = None

    # Chapter 1 — the mission: who you are, what you will learn.
    ch1 = layout.chapter(titles[0])
    intro = layout.scene(ch1, study_place)
    intro["objective"] = objectives[0]["id"]
    opener = _line(
        "narrate",
        {
            "en": "This story is about you, {child}.",
            "fr": "Cette histoire parle de toi, {child}.",
        },
    )
    intro_steps = [
        opener,
        _line("narrate", lines["opening"]),
        _line(
            "say",
            lines["mentor_intro"]
            or {
                "en": "Welcome, {child}. Today we work on this lesson together.",
                "fr": "Bienvenue, {child}. Aujourd'hui, on travaille cette leçon ensemble.",
            },
            MENTOR_ID,
        ),
        _image_step(ctx),
        layout.concept(
            {"en": "What you will learn", "fr": "Ce que tu vas apprendre"},
            {lang: [o[lang] for o in objectives] for lang in LANGS},
        ),
    ]
    intro["steps"] = [s for s in intro_steps if s]

    chapter = ch1
    for index, (kind, block) in enumerate(blocks):
        group = groups[index] if index < len(groups) else []
        if kind == "concept":
            if index == first_half and len(layout.chapters) == 1:
                chapter = layout.chapter(titles[1])
            scene = layout.scene(chapter, study_place)
            scene["steps"] = [layout.concept(block["title"], block["rows"]), *ask_steps(group)]
            scene_objective(scene, group)
        elif kind == "example":
            if len(layout.chapters) == 1:
                chapter = layout.chapter(titles[1])
            scene = layout.scene(chapter, block["place"])
            steps = [
                _line(
                    "narrate",
                    lines["example_intro"]
                    or {
                        "en": "Now picture yourself in the field, {child}.",
                        "fr": "Imagine-toi maintenant sur le terrain, {child}.",
                    },
                ),
                layout.concept(block["title"], block["rows"]),
            ]
            steps += [_line("say", text, who) for who, text in lines["example_dialogue"]]
            steps += ask_steps(group)
            if minigame:
                steps.append({"type": "game", "ref": minigame["id"]})
            scene["steps"] = [s for s in steps if s]
            scene_objective(scene, group)
        else:  # key points
            chapter = your_turn = layout.chapter(titles[2])
            scene = layout.scene(chapter, study_place)
            scene["steps"] = [
                layout.concept({"en": "Key points", "fr": "Points clés"}, block),
                *ask_steps(group),
            ]
            scene_objective(scene, group)

    if not blocks and questions:
        scene = layout.scene(chapter, study_place)
        scene["steps"] = ask_steps(questions)

    # Mini-game, if no example scene hosted it.
    if minigame and not any(
        step.get("ref") == minigame["id"]
        for c in layout.chapters
        for s in c["scenes"]
        for step in s["steps"]
    ):
        scene = layout.scene(layout.chapters[-1], study_place)
        scene["steps"] = [{"type": "game", "ref": minigame["id"]}]

    # Closing scene: paper exercises, then the wrap-up.
    if your_turn is None:
        your_turn = layout.chapter(titles[2])
    closing = layout.scene(your_turn, study_place)
    closing_steps: list[dict[str, Any] | None] = []
    if exercises:
        closing_steps.append(
            _line(
                "say",
                {
                    "en": "Now take a sheet of paper, {child}. Work it out yourself.",
                    "fr": "Prends maintenant une feuille, {child}. À toi de le faire.",
                },
                MENTOR_ID,
            )
        )
        closing_steps += [{"type": "photo", "ref": e["id"]} for e in exercises]
    closing_steps.append(_line("narrate", lines["wrap_up"]))
    closing_steps.append(
        _line(
            "narrate",
            {
                "en": "Well done, {child}: you have finished this story.",
                "fr": "Bravo, {child} : tu as terminé cette histoire.",
            },
        )
    )
    closing_steps.append(
        _line(
            "say",
            {
                "en": "Questions about this lesson? Ask me any time, {child}.",
                "fr": "Une question sur cette leçon ? Demande-moi quand tu veux, {child}.",
            },
            TUTOR_ID,
        )
    )
    closing["steps"] = [s for s in closing_steps if s]

    layout.enforce_spacing()
    return layout.chapters


# --------------------------------------------------------------------------
# Tutor, rewards and the predicted typical run
# --------------------------------------------------------------------------

_DISCLOSURE = {
    "en": "I am an AI, not a real person.",
    "fr": "Je suis une IA, pas une vraie personne.",
}


def _tutor(spine: dict[str, Any], ctx: LessonStoryContext, objectives: list[dict]) -> dict:
    raw = spine.get("tutor") if isinstance(spine.get("tutor"), dict) else {}
    intro = text_object(raw.get("intro"), path="tutor.intro") or {
        "en": "Hi {child}! I'm Margo. I give hints; you do the thinking.",
        "fr": "Bonjour {child} ! Je suis Margo. Je donne des indices, c'est toi qui réfléchis.",
    }
    # C.8: every language the intro carries must say the tutor is an AI.
    for lang in LANGS:
        if not _AI_DISCLOSURE_RE.search(intro[lang]):
            intro[lang] = f"{intro[lang]} {_DISCLOSURE[lang]}"
    who_to_ask = (
        {"en": "your teacher or your family", "fr": "ton enseignant ou ta famille"}
        if ctx.is_kids
        else {"en": "your supervisor or a colleague", "fr": "ton encadrant ou un collègue"}
    )
    off_topic = text_object(raw.get("off_topic"), path="tutor.off_topic") or {
        "en": f"Let's stay on this lesson. Ask {who_to_ask['en']} about that.",
        "fr": f"Restons sur cette leçon. Pose cette question à {who_to_ask['fr']}.",
    }
    worry = text_object(raw.get("worry"), path="tutor.worry") or {
        "en": "That sounds important. Please talk to someone you trust now.",
        "fr": "Cela semble important. Parles-en tout de suite à une personne de confiance.",
    }
    earlier = _as_str(raw.get("earlier_weeks")) or (
        f"Module {ctx.module_number}: {ctx.module_title[ctx.target]}"
    )
    return {
        "persona": TUTOR_ID,
        "intro": intro,
        "scope": {"this_week": [o["id"] for o in objectives], "earlier_weeks": earlier},
        "style": [
            "Reply in the language the learner used.",
            "At most 3 short sentences, then one question back.",
            "One hint at a time, starting from the learner's own words.",
            "Speak to the learner as 'you'; in French use 'tu' and stay gender-neutral.",
        ],
        "never": [
            "Give the answer to a question or exercise before the app shows the explanation.",
            "Decide whether an answer is right: the app does that.",
            "Ask for or repeat personal information (surname, address, phone).",
            "Talk about anything other than this lesson.",
        ],
        "off_topic": off_topic,
        "worry": worry,
        "max_turns_per_item": 6,
    }


def _rewards(ctx: LessonStoryContext) -> dict[str, Any]:
    rewards = copy.deepcopy(REWARD_DEFAULTS)
    if not ctx.is_kids:
        rewards["unit"] = {"en": "points", "fr": "points"}
    return rewards


def _predicted_typical(
    questions: list[dict], exercises: list[dict], minigame: dict | None
) -> dict[str, Any]:
    """C.9's typical run: two thirds right first time, the rest on the retry."""
    count = len(questions)
    first = round(count * 2 / 3)
    targets = (
        sum(1 for r in minigame["rounds"] for i in r["items"] if i.get("correct"))
        if minigame
        else 0
    )
    caught = max(targets - 1, 0)
    marks = sum(e.get("marks", 0) for e in exercises)
    points = first * 2 + (count - first) + caught + marks
    return {
        "plan": (
            f"{first} of {count} questions right first time (2 each), the other "
            f"{count - first} right on the second try (1 each); {caught} of {targets} "
            f"mini-game targets caught; paper exercises self-checked ({marks} marks)."
        ),
        "points": points,
    }


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


@dataclass
class StoryBuild:
    doc: dict[str, Any]
    derived_ids: list[str]
    extra_ids: list[str]
    #: The builder's own findings — every copy-fallback (``missing_translation``)
    #: for an item the story kept. Errors while the repair loop runs; see
    #: :func:`with_generator_issues` and :func:`settle_translations`.
    issues: list[ValidationIssue] = field(default_factory=list)


def picked_mcqs(ctx: LessonStoryContext, spine: Any) -> list[QuizMcq]:
    """The quiz MCQs that become questions of this story.

    For the lesson unit's own quiz, all of them. For a covering quiz unit's
    quiz, only the candidates the model picked — those it wrote a
    ``derived`` entry for — in quiz order, at most :data:`MAX_PICKED_MCQS`
    (the first ones it picked). A ref that is not a candidate is ignored.
    """
    if not ctx.picks_from_quiz:
        return list(ctx.mcqs)
    known = {m.ref for m in ctx.mcqs}
    picked: list[str] = []
    for item in _items(_get(spine, "derived")):
        ref = _as_str(_get(item, "ref"))
        if ref in known and ref not in picked:
            picked.append(ref)
    unknown = [
        _as_str(_get(item, "ref"))
        for item in _items(_get(spine, "derived"))
        if _as_str(_get(item, "ref")) not in known
    ]
    if unknown:
        logger.info("Story spine picked unknown quiz questions (ignored)", refs=unknown[:10])
    chosen = set(picked[:MAX_PICKED_MCQS])
    return [m for m in ctx.mcqs if m.ref in chosen]


def _issue_applies(issue: ValidationIssue, question_ids: set[str], exercise_ids: set[str]) -> bool:
    """Whether a copy-fallback is about something the finished story contains."""
    if match := re.match(r"^(?:derived|questions)\[([^\]]+)\]", issue.path):
        return match.group(1) in question_ids
    if match := re.match(r"^exercises\[(\d+)\]", issue.path):
        return f"E{int(match.group(1)) + 1}" in exercise_ids
    return True


def build_story_document(
    ctx: LessonStoryContext,
    spine: Any,
    *,
    drop_question_ids: Iterable[str] = (),
    drop_exercise_ids: Iterable[str] = (),
    drop_minigame: bool = False,
) -> StoryBuild:
    """Normalise a model spine and assemble the whole story-course/1 week.

    Deterministic and side-effect free: the same context and spine always
    give the same document, so the repair loop can rebuild after every model
    call and the salvage pass can rebuild without the items it drops. Every
    copy-fallback is returned in :attr:`StoryBuild.issues`.
    """
    sink = _Translations()
    token = _SINK.set(sink)
    try:
        build = _assemble(
            ctx,
            spine if isinstance(spine, dict) else {},
            drop_q=set(drop_question_ids),
            drop_e=set(drop_exercise_ids),
            drop_minigame=drop_minigame,
        )
    finally:
        _SINK.reset(token)
    question_ids = {q["id"] for q in build.doc["questions"]}
    exercise_ids = {e["id"] for e in build.doc["exercises"]}
    build.issues = [i for i in sink.issues if _issue_applies(i, question_ids, exercise_ids)]
    return build


def _assemble(
    ctx: LessonStoryContext,
    spine: dict[str, Any],
    *,
    drop_q: set[str],
    drop_e: set[str],
    drop_minigame: bool,
) -> StoryBuild:
    registry = _Misconceptions(spine.get("misconceptions"))
    objectives, objective_map = _objectives(spine.get("objectives"), ctx)
    key_points = _key_points(spine, ctx)

    specs: dict[str, dict[str, Any]] = {}
    for item in _items(spine.get("derived")):
        if isinstance(item, dict) and _as_str(item.get("ref")):
            specs.setdefault(_as_str(item.get("ref")), item)

    built: list[_BuiltQuestion] = []
    for mcq in picked_mcqs(ctx, spine):
        if mcq.ref in drop_q:
            continue
        question = _derived_question(mcq, specs.get(mcq.ref, {}), ctx, registry, objective_map)
        if question is None:
            logger.warning("Derived question dropped: answer leak", question=mcq.source_id)
            continue
        built.append(question)
    derived_count = len(built)

    used_ids = {q.doc["id"] for q in built} | {m.ref for m in ctx.mcqs}
    for number, raw in enumerate(_items(spine.get("questions")), start=1):
        raw_id = _as_str(raw.get("id")) if isinstance(raw, dict) else ""
        qid = raw_id if _ID_RE.match(raw_id) and not _DERIVED_ID_RE.match(raw_id) else ""
        if not qid or qid in used_ids:
            qid = f"x{number}"
            while qid in used_ids:
                qid += "_"
        used_ids.add(qid)
        if qid in drop_q:
            continue
        question = _extra_question(raw, qid, registry, objective_map)
        if question is not None:
            built.append(question)

    # Exercise ids follow the spine's positions so a salvage pass can name
    # the same exercise again on a rebuild.
    exercises = []
    for number, raw in enumerate(_items(spine.get("exercises")), start=1):
        if f"E{number}" in drop_e:
            continue
        exercise = _exercise(raw, f"E{number}", objective_map, f"exercises[{number - 1}]")
        if exercise is not None:
            exercises.append(exercise)
    objectives, exercises = _rebalance(objectives, built, exercises, key_points)

    minigame = None if drop_minigame else _minigame(spine.get("minigame"), registry, key_points)
    if minigame is None and key_points:
        minigame = _minigame({}, registry, key_points)
    if minigame is not None:
        minigame["objective"] = objectives[0]["id"]

    chapters = _layout(ctx, spine, objectives, built, exercises, minigame, key_points)
    questions = [q.doc for q in built]

    used_misconceptions: set[str] = set()
    for q in questions:
        used_misconceptions.update(
            c["misconception"] for c in q.get("choices", []) if c.get("misconception")
        )
        used_misconceptions.update(t["misconception"] for t in q["traps"])
    if minigame:
        used_misconceptions.update(
            i["trap"] for r in minigame["rounds"] for i in r["items"] if i.get("trap")
        )
    registry.report_missing(used_misconceptions)

    lesson_sources = ctx.lesson_list("sources_cited")[:10]
    sources = [
        {
            "kind": "lesson",
            "ref": f"Lesson {ctx.unit_number} — {ctx.unit_title[ctx.target]}",
            "used_for": "story, concepts and key points",
        },
        *({"kind": "lesson", "ref": ref, "used_for": "concepts"} for ref in lesson_sources),
    ]
    if ctx.has_quiz and derived_count:
        sources.append(
            {
                "kind": "test",
                "ref": f"Unit {ctx.quiz_unit_number or ctx.unit_number} quiz",
                "used_for": "questions, derived verbatim",
            }
        )

    doc: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "id": ctx.slug,
        "course": ctx.course_title[ctx.target] or ctx.module_title[ctx.target] or "Sira",
        "unit": f"{ctx.unit_number} · {ctx.unit_title[ctx.target]}",
        "week": max(int(ctx.module_number or 1), 1),
        "title": dict(ctx.unit_title),
        "languages": language_pair(ctx.language),
        "learner": {"first_name": CHILD},
        "sources": sources,
        "objectives": objectives,
        "glossary": [],
        "calibration": [],
        "misconceptions": registry.used_only(used_misconceptions),
        "cast": _cast(spine, ctx),
        "facts": [],
        "chapters": chapters,
        "questions": questions,
        "exercises": exercises,
        "minigames": [minigame] if minigame else [],
        "videos": [],
        "tutor": _tutor(spine, ctx, objectives),
        "rewards": _rewards(ctx),
        "art_requests": [],
        "engine_requests": [],
        "checks": {"predicted_typical": _predicted_typical(questions, exercises, minigame)},
    }
    enforce_quiz_fidelity(doc, ctx)
    return StoryBuild(
        doc=doc,
        derived_ids=[q.doc["id"] for q in built if q.derived],
        extra_ids=[q.doc["id"] for q in built if not q.derived],
    )


def minimal_document(ctx: LessonStoryContext) -> dict[str, Any]:
    """The bare header of the unit's story: what is stored when nothing could be built.

    It parses as ``story-course/1`` (so it can be stored as a draft with its
    report) but has no chapters, so it can never validate or be served.
    """
    return {
        "format": FORMAT_VERSION,
        "id": ctx.slug,
        "course": ctx.course_title.get(ctx.target) or "Sira",
        "unit": f"{ctx.unit_number} · {ctx.unit_title.get(ctx.target, '')}",
        "week": max(int(ctx.module_number or 1), 1),
        "title": dict(ctx.unit_title),
        "languages": language_pair(ctx.language),
        "learner": {"first_name": CHILD},
        "sources": [],
        "objectives": [],
        "misconceptions": [],
        "cast": [],
        "chapters": [],
        "questions": [],
        "exercises": [],
        "minigames": [],
        "checks": {},
    }


def enforce_quiz_fidelity(doc: dict[str, Any], ctx: LessonStoryContext) -> None:
    """Re-assert that every derived question carries the quiz's own text.

    The model never writes the target-language side of a derived question,
    but this runs after assembly regardless, so no later normalisation step
    — or a model that echoed back an edited stem — can change what the
    course's quiz says. For a long stem moved into its situation step, the
    step's rows and the question's ``stem`` are re-asserted instead of the
    (generic) prompt.
    """
    target = ctx.target
    by_ref = {m.ref: m for m in ctx.mcqs}
    situations: dict[str, dict[str, Any]] = {}
    for chapter in doc.get("chapters", []):
        for scene in chapter.get("scenes", []):
            for step in scene.get("steps", []):
                if step.get("type") == "concept" and str(step.get("id", "")).startswith(
                    "situation-"
                ):
                    situations[str(step["id"]).removeprefix("situation-")] = step

    for question in doc.get("questions", []):
        mcq = by_ref.get(question.get("id"))
        if mcq is None:
            continue
        question["type"] = "choice"
        ids = list(CHOICE_IDS[: len(mcq.options)])
        choices = question.get("choices") or []
        if [c.get("id") for c in choices] != ids:
            raise AssertionError(f"derived question {mcq.ref} lost its choices")
        for index, choice in enumerate(choices):
            choice[target] = mcq.options[index]
        question["answer"] = ids[mcq.correct_index]
        choices[mcq.correct_index].pop("misconception", None)
        situation = situations.get(mcq.ref)
        if situation is not None:
            situation[target] = [mcq.stem]
            stem = question.get("stem") if isinstance(question.get("stem"), dict) else {}
            home_rows = situation.get(ctx.home) or [mcq.stem]
            question["stem"] = {target: mcq.stem, ctx.home: stem.get(ctx.home) or home_rows[0]}
        else:
            question["prompt"][target] = mcq.stem
            question.pop("stem", None)
        if mcq.explanation and isinstance(question.get("explanation"), dict):
            question["explanation"][target] = mcq.explanation


# --------------------------------------------------------------------------
# Publishability and salvage
# --------------------------------------------------------------------------


def stem_leaks(doc: dict[str, Any]) -> list[ValidationIssue]:
    """The correct option's text inside a choice question's ``stem`` (X5).

    ``stem`` is read before answering, exactly like the prompt, but the
    format's validator only leak-checks ``prompt``, ``hints`` and trap hints —
    and for a choice question it compares the answer *id*, not the option
    text. This is the same check, run on ``stem`` against the correct
    option's text in every language.
    """
    issues: list[ValidationIssue] = []
    for question in doc.get("questions") or []:
        stem = question.get("stem")
        if not isinstance(stem, dict):
            continue
        correct = next(
            (c for c in question.get("choices") or [] if c.get("id") == question.get("answer")),
            None,
        )
        answers = [correct[lang] for lang in LANGS if correct and correct.get(lang)]
        for lang, text in stem.items():
            if any(_leaks(answer, _as_str(text)) for answer in answers):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="answer_leak",
                        path=f"questions[{question.get('id')}].stem.{lang}",
                        message="the answer appears in the stem a learner reads before answering",
                    )
                )
    return issues


def with_issues(report: ValidationReport, issues: Iterable[ValidationIssue]) -> ValidationReport:
    """``report`` with extra errors appended (and its ``checks`` counts kept true)."""
    extra = list(issues)
    if not extra:
        return report
    errors = [*report.errors, *extra]
    checks = report.checks.model_copy(update={"errors": len(errors)})
    return report.model_copy(update={"ok": False, "errors": errors, "checks": checks})


def publishable(report: ValidationReport, doc: dict[str, Any]) -> ValidationReport:
    """The validator's verdict, plus the generator's own checks.

    The format does not require questions, but a lesson story with fewer than
    :data:`MIN_QUESTIONS` is not worth showing a learner, so it is reported as
    an error and the story stays unpublished. A ``stem`` that gives the answer
    away is an error too (:func:`stem_leaks`).
    """
    issues = stem_leaks(doc)
    if len(doc.get("questions") or []) < MIN_QUESTIONS:
        issues.append(
            ValidationIssue(
                severity="error",
                code="too_few_questions",
                path="questions",
                message=f"a lesson story needs at least {MIN_QUESTIONS} questions",
            )
        )
    return with_issues(report, issues)


def with_generator_issues(report: ValidationReport, build: StoryBuild) -> ValidationReport:
    """Fold the builder's own findings (copy-fallbacks) into the report as errors.

    That is what makes the repair loop ask the model for the missing
    translation, exactly as it asks for anything the validator found.
    """
    return with_issues(report, build.issues)


def settle_translations(report: ValidationReport) -> ValidationReport:
    """After the repair budget: keep each copied translation, as a warning.

    A copy is the last resort — a story with a line in the wrong language is
    still better than none — but it is never silent: it stays in the stored
    report. Every other error keeps the story unpublished.
    """
    moved = [e for e in report.errors if e.code == MISSING_TRANSLATION]
    if not moved:
        return report
    errors = [e for e in report.errors if e.code != MISSING_TRANSLATION]
    warnings = [
        *report.warnings,
        *(issue.model_copy(update={"severity": "warning"}) for issue in moved),
    ]
    checks = report.checks.model_copy(update={"errors": len(errors), "warnings": len(warnings)})
    return report.model_copy(
        update={"ok": not errors, "errors": errors, "warnings": warnings, "checks": checks}
    )


_PATH_QUESTION_RE = re.compile(r"^questions\[([^\]]+)\]")
_PATH_EXERCISE_RE = re.compile(r"^exercises\[([^\]]+)\]")
_PATH_MINIGAME_RE = re.compile(r"^minigames\[")


def implicated_items(report: ValidationReport) -> tuple[set[str], set[str], bool]:
    """Question ids, exercise ids and whether the mini-game carry an error."""
    questions: set[str] = set()
    exercises: set[str] = set()
    minigame = False
    for issue in report.errors:
        if match := _PATH_QUESTION_RE.match(issue.path):
            questions.add(match.group(1))
        elif match := _PATH_EXERCISE_RE.match(issue.path):
            exercises.add(match.group(1))
        elif _PATH_MINIGAME_RE.match(issue.path):
            minigame = True
    return questions, exercises, minigame
