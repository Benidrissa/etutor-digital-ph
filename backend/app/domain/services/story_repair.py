"""The deterministic half of story generation: checking the model's screenplay.

A chapter of a module story is a ``story-course/1`` week built from one
lesson unit (or, for the module's final rally, from its quizzes). Since
#2674 the model writes the **screenplay** itself — the scenes, each at one of
the course's places with the characters on stage, and their steps: dialogue
(``say`` with a speaker and a mood), narration, the concept card of each
lesson concept, the questions (``ask``), figures (``show``), the mini-game
and the paper exercises — plus the pedagogy around it: objectives,
misconceptions, the home-language side of the quiz MCQs with a misconception
and a targeted hint for each wrong option, extra questions, paper exercises,
mini-game items and the tutor's prose (see
:mod:`app.ai.prompts.story_from_lesson`).

This module **checks, numbers and resolves**; it never writes story lines:

* every step is checked against the course bible (:mod:`story_bible`): a
  ``say`` speaker and a scene's ``cast`` are cast ids, a mood is one of
  :data:`MOODS`, a place is one of the bible's places;
* every line is both languages, without a "Name:" label, within the
  :data:`STORY_LINE_LIMITS`; a line told twice is dropped;
* ids are numbered (scenes ``s1..``, concept cards ``c1..``, questions,
  exercises) and every ``ask``/``photo``/``game`` ref is resolved;
* every lesson concept must be taught by a concept card that names it
  (``teaches``), never more than :data:`MAX_ASKS_IN_A_ROW` questions in a row,
  2 to 4 scenes.

Whatever the builder has to fix in the model's JSON — a copied translation,
a label stripped, a line cut, a question the model never asked placed after
a concept card, a speaker who is not in the cast left out — is recorded as an
issue at the path of the model's own field (:attr:`StoryBuild.issues`). The
repair loop feeds them back like any validator error; only after the repair
budget does a fix survive, and then as a warning in the stored report, never
silently (:func:`settle_translations`).

Two invariants are enforced here, not trusted to the model:

* **Quiz fidelity.** Every stored MCQ the story uses becomes a choice question
  whose target-language prompt, options and correct option are the quiz's own,
  verbatim (:func:`enforce_quiz_fidelity` re-asserts it after assembly). The
  model only ever writes the home-language side; a quiz's
  ``option_misconceptions`` are prompt input and never reach a story.
* **Learner is the hero.** ``learner.first_name`` is the literal ``{child}``
  placeholder and the hero's name; the best friend is ``{friend}``. The front
  end substitutes both at display time, so one cached story serves every
  learner.

Language keying (C1): the ``en``/``fr`` fields of ``narrate``/``say`` steps
and the ``en``/``fr`` row lists of ``concept`` steps hold English and French
respectively, whatever the target language.

A lesson story is one chapter of its module's story, which
:mod:`app.domain.services.story_module_assembly` joins without a model call.
Every chapter carries the bible's cast and places; ``sira_builder`` and
``sira_chapter`` (the bible digest and the chapter's part in the module's
mission) say what it was built with, so a chapter of an older generator or
another bible is stale.
"""

from __future__ import annotations

import copy
import re
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.api.v1.schemas.story_course import (
    FORMAT_VERSION,
    LENGTH_LIMITS,
    MOODS,
    REWARD_DEFAULTS,
    ValidationIssue,
    ValidationReport,
)
from app.domain.services import mcq_checks
from app.domain.services.story_bible import (
    FAMILY,
    FRIEND,
    HERO,
    MENTOR,
    TUTOR,
    StoryBible,
    default_place,
    doc_cast,
    doc_places,
    normalise_bible,
)
from app.domain.services.story_course_validator import (
    MIN_REPEAT_LENGTH,
    drawn_visual_problem,
    line_key,
    speaker_label,
    speaker_prefix_pattern,
)

logger = structlog.get_logger(__name__)

LANGS = ("en", "fr")

#: The learner's first name. The front end replaces it before rendering.
CHILD = "{child}"

#: A story line's length limit per language (A.2): 100 in English, 118 in French.
STORY_LINE_LIMITS: dict[str, int] = dict(LENGTH_LIMITS["story"])
#: The English limit, the stricter one.
STORY_LINE_LIMIT = STORY_LINE_LIMITS["en"]
PROMPT_LIMITS: dict[str, int] = dict(LENGTH_LIMITS["prompt"])
HINT_LIMITS: dict[str, int] = dict(LENGTH_LIMITS["hint"])
#: A figure's caption, as the stage shows it under the picture.
CAPTION_LIMIT = 140

#: Mirrors the validator's leak floor: shorter answers are not leak-checked.
MIN_LEAK_LENGTH = 3

#: Never more than this many ``ask`` steps in a row (the validator's limit).
MAX_ASKS_IN_A_ROW = 3

#: A story with fewer questions than this is not worth publishing.
MIN_QUESTIONS = 2

#: The most MCQs a lesson chapter takes from a quiz unit covering several lessons.
MAX_PICKED_MCQS = 4
#: The most MCQs the module's rally takes from its quizzes.
MAX_RALLY_PICKS = 6

#: Issue codes of the builder's fixes. Each is an error while the repair loop
#: runs and a warning once its budget is spent (:func:`settle_translations`).
#: None is a validator code, so settling never touches a validator error.
MISSING_TRANSLATION = "missing_translation"
SPEAKER_PREFIX = "line_labelled"
LINE_TOO_LONG = "line_cut"
UNKNOWN_SPEAKER = "speaker_not_in_cast"
UNKNOWN_MOOD = "mood_not_in_list"
UNKNOWN_PLACE = "place_not_in_bible"
UNKNOWN_VISUAL = "visual_not_usable"
UNKNOWN_STEP = "step_type_unknown"
DANGLING_REF = "ref_not_found"
ASKED_TWICE = "question_asked_twice"
REPEATED_LINE = "line_told_twice"
QUESTION_NOT_ASKED = "question_not_asked"
TOO_MANY_ASKS = "ask_run_too_long"
UNPLACED_ITEM = "item_not_placed"
CONCEPT_NOT_COVERED = "concept_not_covered"
CONCEPT_TOO_LONG = "concept_card_too_long"
SCENE_COUNT = "scene_count"
SCENE_CAST = "scene_cast_size"
#: #2697: a say line that narrates its own speaker's action ("{friend} lève la
#: carte. …"): the stage direction is made a narrate step. A fix of the
#: builder that, like a prop's, never costs a repair call on its own.
SELF_NARRATED = "line_self_narrated"
#: v4 (#2680): the story checks of a chapter told from the episode plan.
ASK_NOT_SET_UP = "ask_not_set_up"
ASK_NOT_FOLLOWED = "ask_not_followed"
LEAD_IN_GIVES_ANSWER = "lead_in_gives_answer"
STORY_TOO_THIN = "story_too_thin"
ENDING_NOT_STORY = "ending_not_story"
MARGO_SELF_INTRO = "margo_self_intro"
META_LINE = "meta_line"
NAME_FROM_LESSON = "name_from_lesson"
STORY_CODES = frozenset(
    {
        ASK_NOT_SET_UP,
        ASK_NOT_FOLLOWED,
        LEAD_IN_GIVES_ANSWER,
        STORY_TOO_THIN,
        ENDING_NOT_STORY,
        MARGO_SELF_INTRO,
        META_LINE,
        NAME_FROM_LESSON,
    }
)
#: #2681: what the builder settles about props. A prop issue never costs a
#: repair call on its own: it is a warning of the build, listed in a repair
#: only when the chapter needs one for another reason.
PROP_CODES = frozenset(
    {
        "prop_invalid",
        "prop_query_people",
        "duplicate_prop",
        "prop_ref_unknown",
        "prop_named_unreferenced",
        "prop_put_in_scene",
        "scene_props_cut",
        "line_props_too_many",
        "chapter_props_too_many",
        "prop_unused",
        "figure_prop_dangling",
        "closeup_missing",
        "closeup_invalid",
    }
)
#: The builder's fixes that are warnings of the build: never a repair call on
#: their own, listed in a repair only when the chapter needs one anyway.
QUIET_CODES = frozenset({*PROP_CODES, SELF_NARRATED})
SETTLEABLE = frozenset(
    {
        *STORY_CODES,
        *QUIET_CODES,
        MISSING_TRANSLATION,
        SPEAKER_PREFIX,
        LINE_TOO_LONG,
        UNKNOWN_SPEAKER,
        UNKNOWN_MOOD,
        UNKNOWN_PLACE,
        UNKNOWN_VISUAL,
        UNKNOWN_STEP,
        DANGLING_REF,
        ASKED_TWICE,
        REPEATED_LINE,
        QUESTION_NOT_ASKED,
        TOO_MANY_ASKS,
        UNPLACED_ITEM,
        CONCEPT_NOT_COVERED,
        CONCEPT_TOO_LONG,
        SCENE_COUNT,
        SCENE_CAST,
    }
)
#: Never settled: a chapter the model wrote no readable scene for.
NO_SCENES = "no_scenes"

CHOICE_IDS = "abcdef"
MAX_OBJECTIVES = 3
MINIGAME_ID = "g1"

#: Cast ids (the course bible's).
HERO_ID, FRIEND_ID, MENTOR_ID, FAMILY_ID, TUTOR_ID = HERO, FRIEND, MENTOR, FAMILY, TUTOR

#: Written as the document's top-level ``sira_builder``. A lesson story is one
#: chapter of its module's story; a cached chapter whose ``sira_builder``
#: differs was built by an older generator and is stale. 3: the model writes
#: the screenplay, with the course bible's cast and places (#2674). 4: the
#: chapter is told from the module's episode plan, after the chapter before
#: it, its practice items written apart (#2680), and it shows its props (#2681).
CHAPTER_BUILDER_VERSION = 4

#: The episode plan's own version (``story_module_plans.version``); a plan of
#: another version is made again, which makes every chapter stale.
PLAN_VERSION = 1
#: A practice pack's version, part of its cache key (``pack_inputs``).
PACK_VERSION = 1
#: Extra model calls of a chapter's story after its first one (scenes only).
STORY_REPAIR_CALLS = 1
#: Extra model calls of a practice pack after its first one.
PACK_REPAIR_CALLS = 2

#: The ``model`` of a plan made in code because no answer could be used.
PLAN_DEFAULTED = "DEFAULTED"

#: A chapter's part in its module's mission (``sira_chapter.arc``).
ARC_OPENS = "opens"
ARC_CONTINUES = "continues"
ARC_CLOSES = "closes"
ARC_OPENS_CLOSES = "opens_closes"

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_DERIVED_ID_RE = re.compile(r"^q\d+$")
_FIGURE_MARKER_RE = re.compile(r"\{\{\s*source_image:[^}]*\}\}|⟦FIG\d+⟧")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|`)")
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.MULTILINE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ0-9«\"(])")
_AI_DISCLOSURE_RE = re.compile(r"\b(ai|ia|robot|intelligence artificielle)\b", re.IGNORECASE)


def mission_arc(position: int, lessons: int, *, has_rally: bool) -> str:
    """The part the ``position``-th of ``lessons`` lesson chapters plays in the mission.

    The first lesson sets the module's mission; the module's rally resolves
    it, or, in a module without a quiz unit, the last lesson does.
    """
    first = position == 0
    last = position == lessons - 1 and not has_rally
    if first and last:
        return ARC_OPENS_CLOSES
    if first:
        return ARC_OPENS
    if last:
        return ARC_CLOSES
    return ARC_CONTINUES


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
    """Text folded as the validator's MCQ checks fold it (case, dashes and
    apostrophes, digit groups; see :func:`mcq_checks._fold`), with no spaces.

    The generator's own leak and duplicate tests (:func:`_leaks`,
    :func:`_options_duplicate`) compare these keys as substrings, so they flag
    at least everything the validator does: model text they accept never
    fails validation on the same rule and costs a repair call.
    """
    return re.sub(r"\s+", "", mcq_checks._fold(text))


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

    def add(self, path: str, message: str, code: str = MISSING_TRANSLATION) -> None:
        if not any((i.path, i.code, i.message) == (path, code, message) for i in self.issues):
            self.issues.append(
                ValidationIssue(severity="error", code=code, path=path, message=message)
            )

    def mark(self) -> int:
        return len(self.issues)

    def rollback(self, mark: int) -> None:
        """Forget what was recorded for an item that was then left out."""
        del self.issues[mark:]

    def restore(self, issues: Iterable[ValidationIssue]) -> None:
        """Record issues that were held back (see :class:`_Held`)."""
        for issue in issues:
            if not any(
                (i.path, i.code, i.message) == (issue.path, issue.code, issue.message)
                for i in self.issues
            ):
                self.issues.append(issue)


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


def builder_issue(code: str, path: str, message: str) -> None:
    """Record a fix the builder made to the model's JSON (one of :data:`SETTLEABLE`)."""
    sink = _SINK.get()
    if sink is not None:
        sink.add(path, message, code)


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


class _Held:
    """Copy-fallbacks of items whose place in the story is only known later.

    An objective may be merged away by :func:`_rebalance`.
    ``with held.item(key): ...`` keeps what the block records
    under ``key`` instead of in the story's sink, and :meth:`report` passes on
    those of the keys the finished story uses — as
    :meth:`_Misconceptions.report_missing` does for misconceptions — so the
    model is never asked to translate, and no warning names, an item the story
    does not contain.
    """

    def __init__(self) -> None:
        self._issues: dict[Any, list[ValidationIssue]] = {}

    @contextmanager
    def item(self, key: Any) -> Iterator[None]:
        sink = _SINK.get()
        if sink is None:
            yield
            return
        mark = sink.mark()
        try:
            yield
        finally:
            self._issues.setdefault(key, []).extend(sink.issues[mark:])
            sink.rollback(mark)

    def report(self, keys: Iterable[Any]) -> None:
        sink = _SINK.get()
        if sink is None:
            return
        for key in keys:
            sink.restore(self._issues.get(key, []))


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
    #: Prompt input only: never copied into a story a learner receives.
    option_misconceptions: list[str | None] = field(default_factory=list)
    #: The quiz unit the MCQ comes from, when a story draws on several (a rally).
    quiz_unit: str | None = None
    #: A rally: an earlier chapter already asked it (a review question if picked).
    asked_before: bool = False

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
    #: ``"lesson"``: a lesson unit's chapter. ``"rally"``: the module's final
    #: chapter, which mixes questions of its quizzes and resolves the mission.
    kind: str = "lesson"
    #: The course bible's content (:mod:`story_bible`); ``None``: the default
    #: bible of the audience (a module without a course).
    bible: dict[str, Any] | None = None
    #: The module's mission and this chapter's part in it (``ARC_*``).
    mission: dict[str, str] | None = None
    arc: str = ARC_CONTINUES
    #: Where the course is set, for the prompt ("CI").
    country: str = ""
    #: A rally: the module's lesson chapters it looks back on, in order
    #: (``{"unit_number", "title", "objectives"}``).
    lessons_recap: list[dict[str, Any]] = field(default_factory=list)
    #: How many candidate MCQs the model may pick.
    max_picks: int = MAX_PICKED_MCQS

    # -- v4 (#2680): a chapter told from the episode plan ---------------------
    #: The module's episode plan (:mod:`story_plan`) and this chapter's entry in
    #: it (``chapters[k]``, or ``rally``). ``None``: a chapter told without a
    #: plan (direct callers and older tests): none of the story checks apply.
    plan: dict[str, Any] | None = None
    plan_entry: dict[str, Any] | None = None
    #: The plan was made in code (no answer could be used): the fallback card
    #: of an idea is then the lesson's own paragraph.
    plan_defaulted: bool = False
    #: This chapter's place among the lesson chapters (1-based) and their number.
    chapter_index: int = 1
    chapter_count: int = 1
    #: The chapters told before this one: ``{"unit", "title", "recap"}``.
    story_so_far: list[dict[str, Any]] = field(default_factory=list)
    #: The plan's props as the last chapter left them: ``{"id", "state"}``.
    props_now: list[dict[str, Any]] = field(default_factory=list)
    #: The previous chapter's last scene, as it was told:
    #: ``{"place": title, "lines": ["narrator: ...", ...]}``; ``None`` for the
    #: first chapter, or when ``previous_missing``.
    previous_scene: dict[str, Any] | None = None
    #: The previous chapter could not be told: open on the plan's OPENS ON.
    previous_missing: bool = False
    #: The next chapter's first scene, when it is already told (a re-tell).
    next_scene: dict[str, Any] | None = None
    #: Lines of earlier chapters (``repeat_keys``) → the unit that told them.
    earlier_line_keys: dict[tuple[str, str], str] = field(default_factory=dict)
    #: Refrain lines told by earlier chapters (at most 4 in a module).
    refrains_before: int = 0
    #: The quiz refs the plan gave this chapter (``quiz_scope`` ``"assigned"``).
    assigned_refs: list[str] = field(default_factory=list)
    #: Whether the plan gives this chapter the episode's one game.
    has_game: bool = True
    #: The plan's catchphrases: ``{"who", "en", "fr"}``.
    catchphrases: list[dict[str, Any]] = field(default_factory=list)
    #: Names of the lesson's own examples, sent in the prompt as forbidden.
    blocklist: list[str] = field(default_factory=list)
    #: Digests the chapter is told with (``sira_chapter``).
    fact_sheet_digest: str = ""
    plan_global_digest: str = ""
    beat_digest: str = ""
    prev_digest: str = ""
    pack_digest: str = ""
    #: #2681: the props already in the story (the plan's, then earlier
    #: chapters'), full shape, each with ``origin`` ("module" or "1.2").
    known_props: list[dict[str, Any]] = field(default_factory=list)
    #: The lesson's figures that still exist (row and binary), with their facts
    #: (``image_hash``, ``figure_kind``...); ``None``: not checked, use the
    #: lesson's own refs.
    figures: list[dict[str, Any]] | None = None
    #: The rally: each lesson chapter's cards, ``{"unit", "title", "cards":
    #: [{"title", "rows"}]}`` — the only facts it may use.
    episode_ideas: list[dict[str, Any]] = field(default_factory=list)
    #: The rally: each prop id → the units whose chapter pointed at it.
    props_seen: dict[str, list[str]] = field(default_factory=dict)
    #: #2698: the course questions' story stems that passed every check and
    #: the judge (ref → ``{"en", "fr"}``): asked in the story's voice, the
    #: answer key locked (:mod:`story_stems`).
    story_stems: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def picks_from_quiz(self) -> bool:
        return self.quiz_scope == "covering" and bool(self.mcqs)

    @property
    def is_v4(self) -> bool:
        """Told from the episode plan: the story checks apply."""
        return self.plan_entry is not None

    @property
    def beats(self) -> list[dict[str, Any]]:
        entry = self.plan_entry or {}
        beats = entry.get("beats") if not self.is_rally else None
        return [b for b in beats or [] if isinstance(b, dict)]

    def figure_refs(self) -> list[dict[str, Any]]:
        """The figures a chapter may show, numbered from 1 in this order."""
        if self.figures is not None:
            return list(self.figures)
        refs = [r for r in _items(self.lesson.get("source_image_refs")) if isinstance(r, dict)]
        return [r for r in refs if _as_str(r.get("id"))]

    @property
    def is_rally(self) -> bool:
        return self.kind == "rally"

    @property
    def bible_content(self) -> dict[str, Any]:
        if self.bible is not None:
            return self.bible
        return normalise_bible({}, is_kids=self.is_kids)

    @property
    def bible_digest_value(self) -> str:
        return StoryBible.of(self.bible_content).digest

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
    """Two options the same under :func:`norm` or the validator's
    :func:`mcq_checks.option_key` ("In the morning" / "In the morning.")."""
    seen: set[str] = set()
    for option in options:
        keys = {("norm", norm(option)), ("key", mcq_checks.option_key(option))}
        if keys & seen:
            return True
        seen |= keys
    return False


def _leaks(answer_text: str, haystack: str) -> bool:
    """The answer's text inside ``haystack``, as a substring of the folded
    text — a superset of what :func:`mcq_checks.check_answer_leak` finds,
    with the answer's edge punctuation trimmed as the validator trims it."""
    needle = "".join(mcq_checks._leak_needle(answer_text))
    return len(needle) >= MIN_LEAK_LENGTH and needle in norm(haystack)


def _stored_mcq_defect(source_id: str, stem: str, options: list[str], answer: int) -> str | None:
    """Why a stored MCQ cannot be shown verbatim in a story, by the very
    rules the story validator applies (:mod:`mcq_checks`), or ``None``.

    A question kept here is copied word for word, so it must not carry a hard
    error the model cannot repair; one the checks only warn about (an either/or
    comparison) is kept, since a warning does not block publication.
    """
    view = mcq_checks.from_quiz_question(
        {"id": source_id, "question": stem, "options": options, "correct_answer": answer}
    )
    # Stricter than the validator on duplicates, on purpose: options equal but
    # for case ("Fever and rash" / "fever and RASH") read as one to a learner;
    # dropping the odd "CO" / "Co" pair costs a question, never a repair call.
    if _options_duplicate(options) or mcq_checks.hard_errors(
        mcq_checks.check_duplicate_options(view)
    ):
        return "duplicate_options"
    if mcq_checks.hard_errors(mcq_checks.check_answer_leak(view)):
        return "answer_in_stem"
    return None


def parse_quiz_mcqs(raw_questions: Any) -> tuple[list[QuizMcq], list[dict[str, str]]]:
    """Lift a unit quiz's stored questions into :class:`QuizMcq` views.

    Reads the stored JSON directly rather than through ``QuizQuestion`` so the
    optional ``option_misconceptions`` field survives whether or not the
    schema declares it yet.

    A stored MCQ is dropped — and reported, never shipped — when it is
    malformed, or when the story validator's MCQ checks find a hard error in
    it (:func:`_stored_mcq_defect`): two options that read the same (the
    honest, deterministic form of "more than one correct answer"), or its
    correct option given away by its own stem.
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
        defect = _stored_mcq_defect(source_id, stem, option_texts, answer)
        if defect:
            dropped.append({"question": source_id, "reason": defect})
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

#: A long quiz stem is shown on a card a character holds up (#2680: the
#: in-world written card of the story, "the teacher's riddle card").
_SITUATION_PROMPT = {
    "en": "Read the card, then choose the best answer.",
    "fr": "Lis la carte, puis choisis la meilleure réponse.",
}
_SITUATION_TITLE = {"en": "On the card", "fr": "Sur la carte"}


def situation_step_id(question_id: str) -> str:
    return f"situation-{question_id}"


@dataclass
class _BuiltQuestion:
    doc: dict[str, Any]
    derived: bool
    #: A long verbatim quiz stem, shown in a concept step just before the ask
    #: because the prompt itself is length-capped.
    situation: dict[str, str] | None = None
    #: v4: the lesson IDEA the question tests (the pack's ``idea``).
    idea: int | None = None


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


def usable_story_stem(
    ctx: LessonStoryContext, ref: str, correct_texts: list[str]
) -> dict[str, str] | None:
    """The approved story stem of question ``ref`` (#2698), if it can be asked as it is.

    Only ``ctx.story_stems`` decides — the approved stems, checked in code and
    by the judge — never a key of the document: written in both languages,
    within the prompt's length, without the correct answer.
    """
    story = ctx.story_stems.get(ref)
    if (
        isinstance(story, dict)
        and all(isinstance(story.get(lang), str) and story[lang] for lang in LANGS)
        and all(len(story[lang]) <= PROMPT_LIMITS[lang] for lang in LANGS)
        and _leak_free(story, correct_texts)
    ):
        return {lang: story[lang] for lang in LANGS}
    return None


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
    # #2698: the question asked in the story's voice, when its rewrite passed
    # every check and the judge. Only this sentence changes; the original is
    # kept next to it, and no card is needed (it fits the prompt).
    story = usable_story_stem(ctx, mcq.ref, correct_texts)
    if story is not None:
        prompt = dict(story)
    elif any(len(prompt[lang]) > PROMPT_LIMITS[lang] for lang in LANGS):
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
        # The course's option_misconceptions are prompt input only: they never
        # fill a gap the model left, or they would reach the learner. An
        # undeclared id is declared from the wrong option itself; a wrong
        # option without one is left to the repair loop
        # (distractor_without_misconception), as for a quiz that has none.
        misconception = registry.resolve(
            item.get("misconception"), _wrong_choice_statement(option_text)
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
        # C-1: which quiz unit and which of its questions this one copies.
        # The module assembler de-duplicates on the pair across chapters.
        "derived_from": {
            "quiz_unit": mcq.quiz_unit or ctx.quiz_unit_number or ctx.unit_number,
            "question_id": mcq.source_id,
        },
    }
    if situation is not None:
        question["stem"] = {lang: situation[lang] for lang in LANGS}
    if story is not None:
        # The quiz's own question, for the record: the quiz page shows it.
        question["original_stem"] = {lang: stem[lang] for lang in LANGS}
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


def _objectives(
    raw: Any, ctx: LessonStoryContext, held: _Held
) -> tuple[list[dict], dict[str, str], list[tuple[dict[str, Any], int]]]:
    """The spine's objectives (at most :data:`MAX_OBJECTIVES`), renumbered o1..oN.

    Also returns each objective with its index in the spine: its copy-fallbacks
    are held under that index, to be reported only if the objective survives
    :func:`_rebalance`.
    """
    objectives: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    origins: list[tuple[dict[str, Any], int]] = []
    for index, item in enumerate(_items(raw)):
        if not isinstance(item, dict) or len(objectives) >= MAX_OBJECTIVES:
            continue
        with held.item(("objective", index)):
            text = text_object(
                {"en": item.get("en"), "fr": item.get("fr")}, path=f"objectives[{index}]"
            )
        if text is None:
            continue
        new_id = f"o{len(objectives) + 1}"
        objective = {"id": new_id, "en": text["en"], "fr": text["fr"]}
        objectives.append(objective)
        origins.append((objective, index))
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
    return objectives, mapping, origins


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


def _fallback_exercise(objective: dict[str, Any]) -> dict[str, Any]:
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
    return exercise


def _rebalance(
    objectives: list[dict[str, Any]],
    questions: list[_BuiltQuestion],
    exercises: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Give every objective at least 2 questions and 1 exercise (C.5 warnings).

    Questions move from objectives with a surplus; an objective that cannot be
    covered is merged away. Objectives without an exercise borrow a surplus
    one, else get a reflection exercise. Also returns where each objective id
    went (merged and renumbered), for the scenes that name one.
    """
    objectives = list(objectives)
    ids = [o["id"] for o in objectives]
    merged: dict[str, str] = {}

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
        merged[victim] = heir
        for q in questions:
            if q.doc["objective"] == victim:
                q.doc["objective"] = heir
        for exercise in exercises:
            if exercise.get("objective") == victim:
                exercise["objective"] = heir

    objectives = [o for o in objectives if o["id"] in ids]
    # Renumber o1..oN so ids stay tidy after a merge.
    renumber = {o["id"]: f"o{n + 1}" for n, o in enumerate(objectives)}

    def where(objective_id: str) -> str:
        while objective_id in merged:
            objective_id = merged[objective_id]
        return renumber.get(objective_id, "")

    moved = {old: where(old) for old in [*renumber, *merged]}
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
                kept.append(_fallback_exercise(objective))
    return objectives, kept, moved


# --------------------------------------------------------------------------
# Mini-game (C5: engine "catch", items rounds)
# --------------------------------------------------------------------------


def _minigame(
    raw: Any, registry: _Misconceptions, fallback_rows: dict[str, list[str]] | None
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

    if not rounds and fallback_rows and fallback_rows["en"]:
        # Fallback: the chapter's own concept rows, every one of them true.
        for start in range(0, min(len(fallback_rows["en"]), 6), 3):
            rounds.append(
                {
                    "prompt": {
                        "en": "Catch the ideas you just learned.",
                        "fr": "Attrape les idées que tu viens d'apprendre.",
                    },
                    "items": [
                        {"label": {"en": en, "fr": fr}, "correct": True}
                        for en, fr in zip(
                            fallback_rows["en"][start : start + 3],
                            fallback_rows["fr"][start : start + 3],
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
# The screenplay: scenes and steps the model wrote, checked and numbered
# --------------------------------------------------------------------------

#: Spoken-name aliases the model may use in ``who`` / ``cast`` for each role.
_WHO_ALIASES: dict[str, str] = {
    "hero": HERO_ID,
    "learner": HERO_ID,
    "child": HERO_ID,
    "you": HERO_ID,
    "{child}": HERO_ID,
    "friend": FRIEND_ID,
    "peer": FRIEND_ID,
    "colleague": FRIEND_ID,
    "{friend}": FRIEND_ID,
    "mentor": MENTOR_ID,
    "teacher": MENTOR_ID,
    "supervisor": MENTOR_ID,
    "family": FAMILY_ID,
    "parent": FAMILY_ID,
    "mother": FAMILY_ID,
    "father": FAMILY_ID,
    "margo": TUTOR_ID,
    "tutor": TUTOR_ID,
    "ai_tutor": TUTOR_ID,
}

#: Moods a model writes that mean one of :data:`MOODS`.
_MOOD_ALIASES: dict[str, str] = {
    "neutral": "idle",
    "calm": "idle",
    "speaking": "talk",
    "explaining": "talk",
    "curious": "think",
    "thinking": "think",
    "confused": "think",
    "puzzled": "think",
    "excited": "happy",
    "proud": "happy",
    "laughing": "happy",
    "joyful": "happy",
    "worried": "sad",
    "upset": "sad",
    "disappointed": "sad",
    "shocked": "surprised",
    "amazed": "surprised",
    "walking": "walk",
}

#: A step the model wrote with a mood the stage has no pose for gets this one.
DEFAULT_MOOD = "talk"

#: A chapter tells its lesson in this many scenes (a rally in 2 or 3).
MIN_SCENES, MAX_SCENES = 2, 5
#: Characters on stage in one scene.
MIN_ON_STAGE, MAX_ON_STAGE = 2, 3
#: Rows of a concept card.
MAX_CONCEPT_ROWS = 4
#: An episode has at most this many catchphrases, told at most this often.
MAX_CATCHPHRASES, MAX_REFRAINS = 2, 4


@dataclass
class _Cast:
    """The bible's cast as a story uses it: ids, and every name a line may label."""

    members: list[dict[str, Any]]

    @property
    def ids(self) -> list[str]:
        return [m["id"] for m in self.members]

    def resolve(self, value: Any) -> str | None:
        """A cast id for what the model wrote in ``who`` or ``cast``."""
        key = _as_str(value).strip().lower()
        if not key:
            return None
        if key in self.ids:
            return key
        alias = _WHO_ALIASES.get(key)
        if alias in self.ids:
            return alias
        for member in self.members:
            names = {
                _as_str(member.get("name")).lower(),
                _as_str(member.get("default_name")).lower(),
            }
            if key in names - {""}:
                return member["id"]
        return None

    def own_names(self, who: str) -> list[str]:
        """What a line may call cast member ``who``: its placeholder and its names."""
        names = {HERO_ID: [CHILD], FRIEND_ID: ["{friend}"]}.get(who, [])
        for member in self.members:
            if member["id"] == who:
                names += [_as_str(member.get("name")), _as_str(member.get("default_name"))]
        return [name for name in names if name]

    def names(self) -> list[str]:
        out: list[str] = []
        for member in self.members:
            out += [member["id"], _as_str(member.get("name")), _as_str(member.get("default_name"))]
        return [name for name in out if name]


def _prefix_re(cast: _Cast) -> re.Pattern[str] | None:
    """The validator's own speaker-label pattern: what it flags, the builder strips."""
    return speaker_prefix_pattern(cast.names())


def _strip_prefix(text: str, pattern: re.Pattern[str] | None) -> str | None:
    """``text`` without its "Name: " / "Name dit : « »" label, or ``None`` if it has none.

    Exactly what the validator flags (:func:`speaker_label`). Reported speech
    ("Kaboré dit que…", "Kaboré says 'prime' means…") is not a label and is
    left alone; quotes are removed only as a pair.
    """
    return speaker_label(text, pattern)


def _story_line(
    kind: str,
    raw: dict[str, Any],
    path: str,
    *,
    who: str | None = None,
    mood: str | None = None,
    prefix: re.Pattern[str] | None = None,
) -> dict[str, Any] | None:
    """A ``narrate``/``say`` step: both languages, no name label, within the limits."""
    text = text_object({"en": raw.get("en"), "fr": raw.get("fr")}, path=path)
    if text is None:
        return None
    step: dict[str, Any] = {"type": kind}
    if who:
        step["who"] = who
    if mood:
        step["mood"] = mood
    for lang in LANGS:
        value = text[lang]
        if prefix is not None and (stripped := _strip_prefix(value, prefix)) is not None:
            builder_issue(
                SPEAKER_PREFIX,
                f"{path}.{lang}",
                "the line starts with the speaker's name: 'who' already says who speaks,"
                " so write only the words they say",
            )
            value = stripped
        limit = STORY_LINE_LIMITS[lang]
        if len(value) > limit:
            builder_issue(
                LINE_TOO_LONG,
                f"{path}.{lang}",
                f"{len(value)} characters: a story line is at most {limit} in {_LANGUAGE_NAMES[lang]}",
            )
            value = truncate(value, limit)
        step[lang] = value
    return step


def _wordset(words: str) -> frozenset[str]:
    """The words of a space-separated list."""
    return frozenset(words.split())


#: Where a sentence may end: ".", "!", "?" or "…" followed by a capital, a
#: placeholder or a quote, or by nothing — "fig. 3" never ends one.
_SENTENCE_END_RE = re.compile(r"[.!?…](?=\s+[A-ZÀ-ÖØ-Þ{«\"“¿¡]|\s*$)")
#: Abbreviations a sentence never ends on ("M. Kaboré", "Dr. Diallo").
_ABBREVIATIONS = frozenset({"m", "mme", "mlle", "mr", "mrs", "ms", "dr", "st", "fig", "p", "no"})


def _first_sentence(text: str) -> tuple[str, str]:
    """``(first sentence, the rest)`` of ``text``; the whole text when it has one sentence."""
    for match in _SENTENCE_END_RE.finditer(text):
        before = re.findall(r"[\w]+$", text[: match.start()])
        if match.group(0) == "." and before and before[0].casefold() in _ABBREVIATIONS:
            continue
        return text[: match.end()].strip(), text[match.end() :].strip()
    return text.strip(), ""


#: The word after the speaker's name that makes the line speech, not a stage
#: direction: an intent, a saying, a feeling, a state ("Mamie va te montrer",
#: "Kaboré dit que…", "Kofi is tired").
_NOT_AN_ACTION = _wordset(
    "va vais vas allons allez vont veut veux voudrait voudrais peut peux doit dois"
    " dit dis demande demandes repond reponds explique pense crois croit sait sais"
    " aime adore deteste prefere est es suis a as ai etait sera serait n ne"
    " will would wants want can could must should says say asks ask answers tells"
    " explains thinks believes knows loves likes hates prefers is am was has had"
    " does doesn did didn isn wasn hasn won"
)
#: Words of a first sentence that speak to someone: it is speech.
_ADDRESSING = _wordset("te tu toi t vous ton ta tes votre vos you your yours yourself")


def _own_action(text: str, names: Sequence[str]) -> tuple[str, str] | None:
    """``(stage direction, the rest)`` when ``text`` opens on its speaker doing something.

    "{friend} lève la carte. Quel est l'ordre ?" → ("{friend} lève la carte.",
    "Quel est l'ordre ?"). Only a clear stage direction: one of the speaker's
    own ``names``, then an action (a lower-case verb that is not an intent, a
    saying, a feeling or a state), a sentence ending on a period, followed by
    the spoken words or by nothing. Speech about oneself stays speech: "Mamie
    va te montrer…", "Kaboré dit que…", a first sentence that speaks to someone
    or names another character ("…, {child} : …"), or one that ends on "!"/"?".
    """
    stripped = text.strip()
    for name in names:
        if not stripped.startswith(name):
            continue
        after = stripped[len(name) :]
        verb = re.match(r"\s+([a-zà-öø-ÿ][\wà-öø-ÿ'’-]*)", after)
        if verb is None:
            continue
        word = re.split(r"['’]", fold_word(verb.group(1)))[0]
        if word in _NOT_AN_ACTION:
            return None
        first, rest = _first_sentence(stripped)
        if not first.endswith("."):
            return None
        others = [p for p in re.findall(r"\{[a-z]+\}", first) if p != name]
        words = set(re.findall(r"[a-z]+", fold_word(first)))
        if others or words & _ADDRESSING:
            return None
        return first, rest.strip()
    return None


def fold_word(text: str) -> str:
    """Lower case, no accents, straight apostrophes (how the split reads a word)."""
    value = unicodedata.normalize("NFKD", text).casefold()
    return "".join(c for c in value if not unicodedata.combining(c)).replace("’", "'")


def _split_self_narration(
    step: dict[str, Any], names: Sequence[str], path: str
) -> list[dict[str, Any]]:
    """A say line that narrates its own speaker's action, as a narrate step and the words.

    The stage direction becomes a ``narrate`` step before the ``say`` step,
    which keeps only what is said. When it is the whole line, the line becomes
    a narrate step — kept as the say it was when it turns out to be a
    question's lead-in (see :meth:`_ScreenplayBuilder.scene`). When only one
    language narrates, its stage direction is left out of that language (the
    other never had it). Reported under a quiet code: never a repair call.
    """
    found = {lang: _own_action(str(step.get(lang) or ""), names) for lang in LANGS}
    if not any(found.values()):
        return [step]
    builder_issue(
        SELF_NARRATED,
        f"{path}.{next(lang for lang in LANGS if found[lang])}",
        "a character's line narrates their own action: write the action as a"
        ' "narrate" step and keep only the spoken words in the "say" step',
    )
    narrate = {
        "type": "narrate",
        **{k: v for k, v in step.items() if k in ("props", "_src")},
    }
    whole = {**narrate, **{lang: step[lang] for lang in LANGS}, "_was_say": step}
    if all(found.values()):
        rests = {lang: found[lang][1] for lang in LANGS}
        if all(rests.values()):
            said = {**step, **rests}
            said.pop("props", None)
            return [{**narrate, **{lang: found[lang][0] for lang in LANGS}}, said]
        return [whole]
    lang = next(lang for lang in LANGS if found[lang])
    rest = found[lang][1]
    if not rest:
        return [whole]
    return [{**step, lang: rest}]


def _mood(value: Any, path: str) -> str:
    mood = _as_str(value).lower()
    if not mood:
        return DEFAULT_MOOD
    if mood in MOODS:
        return mood
    if mood in _MOOD_ALIASES:
        return _MOOD_ALIASES[mood]
    builder_issue(
        UNKNOWN_MOOD, f"{path}.mood", f"{mood!r} is not a mood: use one of {', '.join(MOODS)}"
    )
    return DEFAULT_MOOD


def _figure_step(ctx: LessonStoryContext, raw: dict[str, Any]) -> dict[str, Any] | None:
    """A lesson figure by its number in the prompt (1-based) or its id.

    The numbering is that of the FIGURES the prompt listed
    (:meth:`LessonStoryContext.figure_refs`): figures whose row or binary is
    gone were left out of it.
    """
    refs = ctx.figure_refs()
    wanted = raw.get("figure")
    ref: dict[str, Any] | None = None
    if isinstance(wanted, int) and not isinstance(wanted, bool) and 1 <= wanted <= len(refs):
        ref = refs[wanted - 1]
    elif _as_str(wanted).isdigit() and 1 <= int(_as_str(wanted)) <= len(refs):
        ref = refs[int(_as_str(wanted)) - 1]
    else:
        source_id = _as_str(
            _get(raw.get("params"), "source_image_id") or raw.get("source_image_id")
        )
        ref = (
            next((r for r in refs if _as_str(r.get("id")) == source_id), None)
            if source_id
            else None
        )
    if ref is None:
        return None
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
        step["caption"] = capped(caption, CAPTION_LIMIT)
    return step


def _show_step(ctx: LessonStoryContext, raw: dict[str, Any], path: str) -> dict[str, Any] | None:
    visual = _as_str(raw.get("visual"))
    if raw.get("figure") is not None or visual in ("", "image"):
        step = _figure_step(ctx, raw)
        if step is None:
            builder_issue(
                DANGLING_REF,
                path,
                "this show step names no figure of the lesson: use"
                ' {"type": "show", "figure": N} with a figure listed above, or leave it out',
            )
        return step
    problem = drawn_visual_problem(visual, raw.get("params"))
    if problem is not None:
        # The player draws only these: anything else would show "not available".
        builder_issue(
            UNKNOWN_VISUAL,
            path,
            f"{problem}. Use a lesson figure or a drawn visual with its params, or leave it out",
        )
        return None
    step = {"type": "show", "visual": visual, "params": copy.deepcopy(raw["params"])}
    caption = text_object(raw.get("caption"), path=f"{path}.caption")
    if caption:
        step["caption"] = capped(caption, CAPTION_LIMIT)
    return step


@dataclass
class _Refs:
    """What ``ask``/``photo``/``game`` steps may point at, and what they did."""

    #: The model's own ref (``q1``, ``x2``, the id it gave) → the question id.
    questions: dict[str, str]
    exercises: dict[str, str]
    minigame: str | None
    situations: dict[str, _BuiltQuestion]
    #: Question and exercise ids a salvage pass left out: their steps go too, silently.
    dropped: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)
    placed: list[str] = field(default_factory=list)
    game_placed: bool = False


def taught(step: dict[str, Any]) -> set[int]:
    """The lesson IDEA numbers a concept card names (``teaches``: an int or a list)."""
    value = step.get("teaches")
    values = value if isinstance(value, list) else [value]
    return {v for v in values if isinstance(v, int) and not isinstance(v, bool) and v > 0}


def _teaches(value: Any) -> int | list[int] | None:
    """The model's ``teaches`` as the document stores it: an int, a list, or nothing."""
    values = value if isinstance(value, list) else [value]
    out: list[int] = []
    for item in values:
        if isinstance(item, str) and item.strip().isdigit():
            item = int(item.strip())
        if isinstance(item, int) and not isinstance(item, bool) and item > 0 and item not in out:
            out.append(item)
    if not out:
        return None
    return out[0] if len(out) == 1 and not isinstance(value, list) else out


class _ScreenplayBuilder:
    """Turns the model's ``scenes`` into the chapter's scenes, recording every fix.

    Every step it builds carries ``_src``, the path of the model's own step,
    so the story checks name what the model wrote; it is removed before the
    document is returned.
    """

    def __init__(
        self,
        ctx: LessonStoryContext,
        cast: _Cast,
        places: set[str],
        objective_map: dict[str, str],
        refs: _Refs,
        book: Any = None,
    ) -> None:
        self.ctx = ctx
        self.cast = cast
        self.places = places
        self.objective_map = objective_map
        self.refs = refs
        self.book = book
        self.prefix = _prefix_re(cast)
        self.concepts = 0
        self.default_place = default_place(ctx.bible_content, ctx.is_kids)
        self.refrains = ctx.refrains_before
        self.catchphrases = [
            {
                "who": _as_str(c.get("who")),
                "keys": {(lang, line_key(c.get(lang))) for lang in LANGS if c.get(lang)},
            }
            for c in ctx.catchphrases[:MAX_CATCHPHRASES]
            if isinstance(c, dict)
        ]

    def scenes(self, raw_scenes: Any) -> list[dict[str, Any]]:
        scenes: list[dict[str, Any]] = []
        for index, raw in enumerate(_items(raw_scenes)):
            if isinstance(raw, dict):
                scene = self.scene(raw, f"scenes[{index}]")
                if scene is not None:
                    scenes.append(scene)
        return scenes

    def scene(self, raw: dict[str, Any], path: str) -> dict[str, Any] | None:
        place = _as_str(raw.get("place"))
        if place not in self.places:
            slug = _slug(place, "")
            place_fixed = slug if slug in self.places else self.default_place
            builder_issue(
                UNKNOWN_PLACE,
                f"{path}.place",
                f"{place!r} is not a place of the course: use one of the place ids listed",
            )
            place = place_fixed
        on_stage: list[str] = []
        for member in _items(raw.get("cast")):
            resolved = self.cast.resolve(member)
            if resolved is None:
                builder_issue(
                    UNKNOWN_SPEAKER, f"{path}.cast", f"{_as_str(member)!r} is not in the cast"
                )
            elif resolved not in on_stage:
                on_stage.append(resolved)

        steps: list[dict[str, Any]] = []
        for index, raw_step in enumerate(_items(raw.get("steps"))):
            if isinstance(raw_step, dict):
                built = self.step(raw_step, f"{path}.steps[{index}]")
                for step in built:
                    step.setdefault("_src", f"{path}.steps[{index}]")
                steps.extend(built)
        if not steps:
            return None
        for index, step in enumerate(steps):
            said = step.pop("_was_say", None)
            if said is None:
                continue
            after = steps[index + 1] if index + 1 < len(steps) else None
            if after is not None and (
                after.get("type") == "ask" or str(after.get("id", "")).startswith("situation-")
            ):
                # A stage direction that is a question's lead-in stays the say
                # it was: as a narrate step it would leave the question with no
                # lead-in, a repair call (#2697 review).
                steps[index] = said
        for step in steps:
            if step["type"] == "say" and step["who"] not in on_stage:
                on_stage.append(step["who"])
        if not MIN_ON_STAGE <= len(on_stage) <= MAX_ON_STAGE:
            builder_issue(
                SCENE_CAST,
                f"{path}.cast",
                f"{len(on_stage)} characters on stage: a scene shows {MIN_ON_STAGE} or"
                f" {MAX_ON_STAGE}, and every speaker of the scene is one of them",
            )
        scene: dict[str, Any] = {"id": "", "place": place, "cast": on_stage}
        objective = self.objective_map.get(_as_str(raw.get("objective")))
        if objective:
            scene["objective"] = objective
        if self.book is not None and raw.get("props") is not None:
            listed = self.book.refs(raw.get("props"), f"{path}.props")
            if listed:
                scene["props"] = listed
        scene["steps"] = steps
        return scene

    def _line_props(self, step: dict[str, Any], raw: dict[str, Any], path: str) -> None:
        if self.book is None or raw.get("props") is None:
            return
        refs = self.book.refs(raw.get("props"), f"{path}.props")
        if refs:
            step["props"] = refs

    def _refrain(self, step: dict[str, Any]) -> None:
        """A say line that is one of the plan's catchphrases, by its speaker: a refrain."""
        keys = {(lang, line_key(step.get(lang))) for lang in LANGS}
        for phrase in self.catchphrases:
            if phrase["who"] == step.get("who") and keys & phrase["keys"]:
                if self.refrains < MAX_REFRAINS:
                    step["refrain"] = True
                    self.refrains += 1
                return

    def step(self, raw: dict[str, Any], path: str) -> list[dict[str, Any]]:
        kind = _as_str(raw.get("type"))
        if kind == "narrate":
            step = _story_line("narrate", raw, path)
            if step:
                self._line_props(step, raw, path)
            return [step] if step else []
        if kind == "say":
            who = self.cast.resolve(raw.get("who"))
            if who is None:
                builder_issue(
                    UNKNOWN_SPEAKER,
                    f"{path}.who",
                    f"{_as_str(raw.get('who'))!r} is not in the cast: 'who' is one of"
                    f" {', '.join(self.cast.ids)}",
                )
                return []
            step = _story_line(
                "say", raw, path, who=who, mood=_mood(raw.get("mood"), path), prefix=self.prefix
            )
            if not step:
                return []
            self._line_props(step, raw, path)
            steps = _split_self_narration(step, self.cast.own_names(who), path)
            for built in steps:
                if built["type"] == "say":
                    self._refrain(built)
            return steps
        if kind == "concept":
            return self.concept(raw, path)
        if kind == "ask":
            return self.ask(raw, path)
        if kind == "show":
            if raw.get("prop") is not None and self.book is not None:
                step = self.book.closeup(raw, path)
            else:
                step = _show_step(self.ctx, raw, path)
            return [step] if step else []
        if kind == "game":
            if self.refs.minigame is None or self.refs.game_placed:
                return []
            self.refs.game_placed = True
            return [{"type": "game", "ref": self.refs.minigame}]
        if kind == "photo":
            ref = self.refs.exercises.get(_as_str(raw.get("ref")).upper())
            if ref is None and _as_str(raw.get("ref")).upper() in self.refs.dropped:
                return []
            if ref is None:
                builder_issue(
                    DANGLING_REF, f"{path}.ref", f"{_as_str(raw.get('ref'))!r} is not an exercise"
                )
                return []
            if ref in self.refs.placed:
                return []
            self.refs.placed.append(ref)
            return [{"type": "photo", "ref": ref}]
        builder_issue(
            UNKNOWN_STEP,
            f"{path}.type",
            f"{kind!r} is not a step type: use narrate, say, concept, ask, show, game or photo",
        )
        return []

    def concept(self, raw: dict[str, Any], path: str) -> list[dict[str, Any]]:
        with _unless_kept() as kept:
            rows = parallel_rows(raw.get("en"), raw.get("fr"), path=path)
            if rows is None:
                return []
            if len(rows["en"]) > MAX_CONCEPT_ROWS:
                builder_issue(
                    CONCEPT_TOO_LONG,
                    path,
                    f"{len(rows['en'])} rows: a concept card has 2 to {MAX_CONCEPT_ROWS}",
                )
                rows = {lang: rows[lang][:MAX_CONCEPT_ROWS] for lang in LANGS}
            self.concepts += 1
            title = text_object(raw.get("title"), path=f"{path}.title") or {
                "en": f"Key idea {self.concepts}",
                "fr": f"Idée clé {self.concepts}",
            }
            step: dict[str, Any] = {
                "type": "concept",
                "id": f"c{self.concepts}",
                "title": title,
                "en": list(rows["en"]),
                "fr": list(rows["fr"]),
            }
            teaches = _teaches(raw.get("teaches"))
            if teaches is not None:
                step["teaches"] = teaches
            self._line_props(step, raw, path)
            kept.append(True)
            return [step]

    def ask(self, raw: dict[str, Any], path: str) -> list[dict[str, Any]]:
        question_id = self.refs.questions.get(_as_str(raw.get("ref")))
        if question_id is None and _as_str(raw.get("ref")) in self.refs.dropped:
            return []  # left out on purpose (salvage): its ask goes with it
        if question_id is None:
            builder_issue(
                DANGLING_REF,
                f"{path}.ref",
                f"{_as_str(raw.get('ref'))!r} is not one of your questions: ask each"
                " question by its ref",
            )
            return []
        if question_id in self.refs.asked:
            builder_issue(ASKED_TWICE, f"{path}.ref", f"{question_id} is already asked earlier")
            return []
        self.refs.asked.append(question_id)
        return ask_steps(self.refs.situations.get(question_id), question_id)


def ask_steps(question: _BuiltQuestion | None, question_id: str) -> list[dict[str, Any]]:
    """An ``ask`` step, after the situation card of a quiz question whose stem is long."""
    steps: list[dict[str, Any]] = []
    if question is not None and question.situation is not None:
        steps.append(
            {
                "type": "concept",
                "id": situation_step_id(question_id),
                "title": dict(_SITUATION_TITLE),
                "en": [question.situation["en"]],
                "fr": [question.situation["fr"]],
            }
        )
    steps.append({"type": "ask", "ref": question_id})
    return steps


def _flat(scenes: list[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], int, dict[str, Any]]]:
    for scene in scenes:
        for index, step in enumerate(scene["steps"]):
            yield scene, index, step


def repeat_keys(step: dict[str, Any]) -> set[tuple[str, str]]:
    """The repetition keys of a story line (none for a short one or a non-line)."""
    if step.get("type") not in ("narrate", "say") or step.get("frame"):
        return set()
    keys = {(lang, line_key(step.get(lang))) for lang in LANGS if isinstance(step.get(lang), str)}
    return {key for key in keys if len(key[1]) >= MIN_REPEAT_LENGTH}


def is_closeup(step: dict[str, Any]) -> bool:
    """A prop's close-up: transparent in a run of questions.

    The player drops a close-up it has no picture for, so it never separates
    two runs: a run is counted through it.
    """
    return step.get("type") == "show" and step.get("visual") == "prop"


def joins_ask_runs(steps: list[dict[str, Any]], index: int) -> bool:
    """Whether removing ``steps[index]`` leaves more than MAX_ASKS_IN_A_ROW asks in a row.

    Close-ups are seen through (:func:`is_closeup`); removing one joins nothing.
    """
    if is_closeup(steps[index]):
        return False
    before = after = 0
    i = index - 1
    while i >= 0 and (steps[i].get("type") == "ask" or is_closeup(steps[i])):
        before, i = before + (steps[i].get("type") == "ask"), i - 1
    i = index + 1
    while i < len(steps) and (steps[i].get("type") == "ask" or is_closeup(steps[i])):
        after, i = after + (steps[i].get("type") == "ask"), i + 1
    return before + after > MAX_ASKS_IN_A_ROW


def drop_steps_keeping_runs(
    scenes: list[dict[str, Any]], pick: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    """Remove the steps ``pick`` chooses, in order, but never a separator.

    A picked step whose removal would join two runs of questions into one
    longer than :data:`MAX_ASKS_IN_A_ROW` is kept; those are returned.
    ``scenes`` are one chapter's, so runs are counted across its scenes.
    """
    alive = [step for scene in scenes for step in scene["steps"]]
    removed: set[int] = set()
    kept: list[dict[str, Any]] = []
    index = 0
    while index < len(alive):
        step = alive[index]
        if pick(step):
            if joins_ask_runs(alive, index):
                kept.append(step)
            else:
                removed.add(id(step))
                alive.pop(index)
                continue
        index += 1
    for scene in scenes:
        scene["steps"] = [step for step in scene["steps"] if id(step) not in removed]
    return kept


def ask_run_excess(steps: list[dict[str, Any]]) -> list[str]:
    """The refs of the asks beyond :data:`MAX_ASKS_IN_A_ROW` in each run of ``steps``.

    A close-up does not end a run (:func:`is_closeup`).
    """
    excess: list[str] = []
    run = 0
    for step in steps:
        if step.get("type") == "ask":
            run += 1
            if run > MAX_ASKS_IN_A_ROW and step.get("ref"):
                excess.append(step["ref"])
        elif not is_closeup(step):
            run = 0
    return excess


def _drop_repeated_lines(
    scenes: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    earlier: dict[tuple[str, str], str] | None = None,
) -> None:
    """Keep the first telling of a line; a later one is dropped, and reported.

    ``earlier`` are the lines of the chapters told before this one (v4): one
    of those told again is dropped too. A refrain (one of the plan's
    catchphrases, marked by the builder) may come back. A repeated line that
    is the only thing between two runs of questions stays (still reported, so
    the model writes a new line).
    """
    earlier = earlier or {}

    def told_before(step: dict[str, Any]) -> bool:
        if step.get("refrain"):
            return False
        keys = repeat_keys(step)
        before = next((earlier[k] for k in keys if k in earlier), None)
        if before is not None:
            builder_issue(
                REPEATED_LINE,
                step.get("_src") or "scenes",
                f"this line was already said in chapter {before}: {step['en'][:60]!r}; write a"
                ' new one. A catchphrase marked "refrain": true may come back',
            )
            return True
        if keys & seen:
            builder_issue(
                REPEATED_LINE,
                step.get("_src") or "scenes",
                f"this line is told twice: {step['en'][:60]!r}; every line is"
                " written for its own moment",
            )
            return True
        seen.update(keys)
        return False

    drop_steps_keeping_runs(scenes, told_before)


def _card_of(scenes: list[dict[str, Any]], idea: int | None) -> tuple[dict[str, Any], int] | None:
    """The scene and position right after the card naming ``idea`` and its asks."""
    if idea is None:
        return None
    for scene, index, step in _flat(scenes):
        if step["type"] == "concept" and idea in taught(step):
            after = index + 1
            while after < len(scene["steps"]) and scene["steps"][after]["type"] == "ask":
                after += 1
            return scene, after
    return None


def _place_unasked(
    scenes: list[dict[str, Any]], questions: list[_BuiltQuestion], refs: _Refs
) -> None:
    """Ask every question the model left out, after the card of the IDEA it tests.

    A question whose IDEA is known (v4: the pack's ``idea``) goes right after
    the card naming that IDEA; otherwise after a concept card that has room
    (followed by fewer than two asks), else before the last scene's closing
    lines. Reported, so the repair loop asks the model to place it.
    """
    for question in questions:
        qid = question.doc["id"]
        if qid in refs.asked:
            continue
        spine_path = f"derived[{qid}]" if question.derived else f"questions[{qid}]"
        builder_issue(
            QUESTION_NOT_ASKED,
            "scenes",
            f'{spine_path} is never asked: ask {{"type": "ask", "ref": "{qid}"}} right'
            + (
                f" after the card of IDEA {question.idea}, with a lead-in and a reaction"
                if question.idea
                else " after the concept card it tests"
            ),
        )
        target = _card_of(scenes, question.idea)
        if target is None:
            for scene, index, step in _flat(scenes):
                if step["type"] != "concept" or str(step.get("id", "")).startswith("situation-"):
                    continue
                after = index + 1
                while after < len(scene["steps"]) and scene["steps"][after]["type"] == "ask":
                    after += 1
                if after - index - 1 < 2:
                    target = (scene, after)
                    break
        if target is None:
            scene = scenes[-1]
            target = (scene, _before_closing_lines(scene["steps"]))
        scene, position = target
        scene["steps"][position:position] = ask_steps(question, qid)
        refs.asked.append(qid)


def _before_closing_lines(steps: list[dict[str, Any]]) -> int:
    """Where to insert something before the final run of story lines of ``steps``.

    A scene of story lines only (a cliffhanger) keeps its last two lines
    after the item, its only line when it has one: never appended.
    """
    position = len(steps)
    while position > 0 and steps[position - 1].get("type") in ("say", "narrate"):
        position -= 1
    return position if position > 0 else max(len(steps) - 2, 0)


def _cap_ask_runs(scenes: list[dict[str, Any]]) -> set[str]:
    """Asks beyond :data:`MAX_ASKS_IN_A_ROW` in a run are left out; their ids returned.

    A close-up does not end a run (:func:`is_closeup`): the player may drop it.
    """
    dropped: set[str] = set()
    run = 0
    for scene in scenes:
        kept: list[dict[str, Any]] = []
        for step in scene["steps"]:
            if is_closeup(step):
                kept.append(step)
                continue
            if step["type"] == "ask":
                if run >= MAX_ASKS_IN_A_ROW:
                    dropped.add(step["ref"])
                    builder_issue(
                        TOO_MANY_ASKS,
                        "scenes",
                        f"more than {MAX_ASKS_IN_A_ROW} questions in a row: a line, a card"
                        f" or a figure goes between them ({step['ref']} was left out)",
                    )
                    continue
                run += 1
            else:
                run = 0
            kept.append(step)
        scene["steps"] = kept
    if dropped:
        situations = {situation_step_id(qid) for qid in dropped}
        for scene in scenes:
            scene["steps"] = [s for s in scene["steps"] if s.get("id") not in situations]
    return dropped


def _check_coverage(
    ctx: LessonStoryContext,
    scenes: list[dict[str, Any]],
    *,
    cover: bool = False,
    ideas: dict[str, int | None] | None = None,
) -> int:
    """Every concept of the lesson is taught by a concept card that names it.

    With ``cover`` (once the repair budget is spent) a concept the model never
    taught gets a card, so the learner always sees it: built from the plan
    beat's card title and discovery (v4), or from the lesson's own text (no
    plan, or a plan made in code), placed before the first question on it.
    Returns how many fallback cards were added.
    """
    concepts = ctx.lesson_list("concepts")
    covered: set[int] = set()
    for _scene, _index, step in _flat(scenes):
        if step.get("type") == "concept":
            covered |= taught(step)
    missing = [n for n in range(1, len(concepts) + 1) if n not in covered]
    for number in missing:
        builder_issue(
            CONCEPT_NOT_COVERED,
            f"lesson.concepts[{number}]",
            f"IDEA {number} ({truncate(concepts[number - 1], 70)!r}) is on no card: show it"
            f' happening in its beat\'s scene, then add a card with "teaches": [{number}]'
            + ("; a card was added instead" if cover else ""),
        )
    if not cover or not missing:
        return 0
    added = 0
    beats = ctx.beats if ctx.is_v4 and not ctx.plan_defaulted else []
    done: set[int] = set()
    for number in missing:
        if number in done:
            continue
        beat_index = next((i for i, b in enumerate(beats) if number in _beat_ideas(b)), None)
        if beat_index is not None:
            beat = beats[beat_index]
            numbers = [n for n in _beat_ideas(beat) if n in missing and n not in done]
            card = _beat_card(beat, beat_index + 1, numbers)
            if card is None:
                card = _paragraph_card(number, concepts[number - 1])
                numbers = [number]
        else:
            card = _paragraph_card(number, concepts[number - 1])
            numbers = [number]
        done.update(numbers)
        _place_fallback_card(scenes, card, numbers, ideas or {}, beat_index)
        added += 1
    return added


def _beat_ideas(beat: dict[str, Any]) -> list[int]:
    values = beat.get("ideas") if isinstance(beat.get("ideas"), list) else []
    return [v for v in values if isinstance(v, int) and not isinstance(v, bool)]


def _beat_card(beat: dict[str, Any], number: int, ideas: list[int]) -> dict[str, Any] | None:
    """The fallback card of a beat: its card title, then its discovery, in both languages."""
    title = text_object(beat.get("card_title"))
    discovery = text_object(beat.get("discovery"))
    if title is None or discovery is None:
        return None
    return {
        "type": "concept",
        "id": f"cbeat{number}",
        "title": title,
        "en": [discovery["en"]],
        "fr": [discovery["fr"]],
        "teaches": list(ideas),
    }


def _paragraph_card(number: int, paragraph: str) -> dict[str, Any]:
    """The fallback card of a concept from the lesson's own text, whole (2 to 4 rows)."""
    rows = split_sentences(paragraph) or [paragraph]
    return {
        "type": "concept",
        "id": f"cfallback{number}",
        "title": {"en": f"Key idea {number}", "fr": f"Idée clé {number}"},
        # The lesson exists in the target language only.
        "en": list(rows),
        "fr": list(rows),
        "teaches": number,
    }


def _place_fallback_card(
    scenes: list[dict[str, Any]],
    card: dict[str, Any],
    numbers: list[int],
    ideas: dict[str, int | None],
    beat_index: int | None,
) -> None:
    """Before the first question on one of ``numbers`` (and its lead-in line).

    Without one: in the beat's scene (v4) before its closing lines; else
    before the first question asked after the card of the IDEA before it,
    else before the card of the next IDEA, else before the last scene's
    closing lines — never after the questions it teaches.
    """
    wanted = set(numbers)
    for scene, index, step in _flat(scenes):
        if step["type"] == "ask" and ideas.get(str(step.get("ref"))) in wanted:
            position = index
            while position > 0 and str(scene["steps"][position - 1].get("id", "")).startswith(
                "situation-"
            ):
                position -= 1
            if position > 0 and scene["steps"][position - 1]["type"] == "say":
                position -= 1
            scene["steps"].insert(position, card)
            return
    if beat_index is not None and beat_index < len(scenes):
        steps = scenes[beat_index]["steps"]
        steps.insert(_before_closing_lines(steps), card)
        return
    first = min(numbers)
    seen_previous = first == 1
    for scene, index, step in _flat(scenes):
        if step["type"] == "concept" and (first - 1) in taught(step):
            seen_previous = True
            continue
        if seen_previous and step["type"] in ("ask", "game", "photo"):
            scene["steps"].insert(index, card)
            return
        if step["type"] == "concept" and any(n > first for n in taught(step)):
            scene["steps"].insert(index, card)
            return
    steps = scenes[-1]["steps"]
    steps.insert(_before_closing_lines(steps), card)


def _place_items(
    scenes: list[dict[str, Any]], refs: _Refs, exercises: list[dict[str, Any]]
) -> None:
    """The mini-game and the paper exercises the model did not place.

    They go before the last scene's closing lines, never as its last steps.
    """
    last = scenes[-1]["steps"]
    if refs.minigame is not None and not refs.game_placed:
        builder_issue(
            UNPLACED_ITEM,
            "minigame",
            'the mini-game is never played: add {"type": "game"} where it fits the story',
        )
        last.insert(_before_closing_lines(last), {"type": "game", "ref": refs.minigame})
        refs.game_placed = True
    for number, exercise in enumerate(exercises, start=1):
        if exercise["id"] in refs.placed:
            continue
        if not exercise["id"].startswith("R"):
            builder_issue(
                UNPLACED_ITEM,
                f"exercises[{_exercise_index(exercise['id'], number)}]",
                f"exercise {exercise['id']} is never given: add"
                f' {{"type": "photo", "ref": "{exercise["id"]}"}} where a character hands it over',
            )
        last.insert(_before_closing_lines(last), {"type": "photo", "ref": exercise["id"]})
        refs.placed.append(exercise["id"])


def _exercise_index(exercise_id: str, fallback: int) -> int:
    digits = exercise_id[1:]
    return int(digits) - 1 if exercise_id.startswith("E") and digits.isdigit() else fallback - 1


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


def rewards_for(is_kids: bool) -> dict[str, Any]:
    """The rewards block: mangoes for children, points for adults."""
    rewards = copy.deepcopy(REWARD_DEFAULTS)
    if not is_kids:
        rewards["unit"] = {"en": "points", "fr": "points"}
    return rewards


def predicted_typical(
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
    #: The builder's own findings — every fix it made to the model's JSON (a
    #: copied translation, a name label stripped, a line cut, a question
    #: placed...). Errors while the repair loop runs; see
    #: :func:`with_generator_issues` and :func:`settle_translations`. A prop
    #: issue (:data:`PROP_CODES`) is only ever a warning.
    issues: list[ValidationIssue] = field(default_factory=list)
    #: v4: the story lints (warnings, never a repair call).
    lints: list[ValidationIssue] = field(default_factory=list)
    #: v4: ``checks.story_quality``.
    quality: dict[str, Any] = field(default_factory=dict)


def picked_mcqs(ctx: LessonStoryContext, spine: Any) -> list[QuizMcq]:
    """The quiz MCQs that become questions of this story.

    For the lesson unit's own quiz, all of them. v4: the ones the episode plan
    gave this chapter (``quiz_scope`` ``"assigned"``). For a covering quiz
    unit's quiz (or the module's quizzes, for a rally told without a plan),
    only the candidates the model picked — those it wrote a ``derived`` entry
    for — in quiz order, at most :attr:`LessonStoryContext.max_picks` (the
    first ones it picked). A ref that is not a candidate is ignored.
    """
    if ctx.quiz_scope == "assigned":
        wanted = set(ctx.assigned_refs)
        return [m for m in ctx.mcqs if m.ref in wanted]
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
    chosen = set(picked[: ctx.max_picks])
    return [m for m in ctx.mcqs if m.ref in chosen]


def _issue_applies(issue: ValidationIssue, question_ids: set[str], exercise_ids: set[str]) -> bool:
    """Whether a builder issue is about something the finished story contains.

    Questions and exercises are filtered here, by the ids the story kept.
    Objectives merged away are never recorded unless kept: see :class:`_Held`.
    """
    if match := re.match(r"^(?:derived|questions)\[([^\]]+)\]", issue.path):
        return match.group(1) in question_ids
    if (match := re.match(r"^exercises\[(\d+)\]", issue.path)) and issue.code != UNPLACED_ITEM:
        return f"E{int(match.group(1)) + 1}" in exercise_ids
    return True


def build_story_document(
    ctx: LessonStoryContext,
    spine: Any,
    *,
    drop_question_ids: Iterable[str] = (),
    drop_exercise_ids: Iterable[str] = (),
    drop_minigame: bool = False,
    cover_missing_concepts: bool = False,
    story_checks: bool = True,
) -> StoryBuild:
    """Check the model's screenplay and turn it into a ``story-course/1`` chapter.

    Deterministic and side-effect free: the same context and answer always
    give the same document, so the repair loop can rebuild after every model
    call and the salvage pass can rebuild without the items it drops. Every
    fix made to the answer is returned in :attr:`StoryBuild.issues`.
    ``cover_missing_concepts`` (once the repair budget is spent) adds a card
    for every concept the screenplay never taught. ``story_checks=False``
    (the check of a practice pack on a stub scene) skips the story checks.
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
            cover=cover_missing_concepts,
            story_checks=story_checks,
        )
    finally:
        _SINK.reset(token)
    question_ids = {q["id"] for q in build.doc["questions"]}
    exercise_ids = {e["id"] for e in build.doc["exercises"]}
    build.issues = [i for i in sink.issues if _issue_applies(i, question_ids, exercise_ids)]
    return build


def _idea(value: Any) -> int | None:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _questions(
    ctx: LessonStoryContext,
    spine: dict[str, Any],
    registry: _Misconceptions,
    objective_map: dict[str, str],
    drop_q: set[str],
) -> tuple[list[_BuiltQuestion], dict[str, str]]:
    """The derived and extra questions, and the refs an ``ask`` step may use for each."""
    specs: dict[str, dict[str, Any]] = {}
    for item in _items(spine.get("derived")):
        if isinstance(item, dict) and _as_str(item.get("ref")):
            specs.setdefault(_as_str(item.get("ref")), item)

    built: list[_BuiltQuestion] = []
    refs: dict[str, str] = {}
    for mcq in picked_mcqs(ctx, spine):
        if mcq.ref in drop_q:
            continue
        spec = specs.get(mcq.ref, {})
        question = _derived_question(mcq, spec, ctx, registry, objective_map)
        if question is None:
            logger.warning("Derived question dropped: answer leak", question=mcq.source_id)
            continue
        question.idea = _idea(spec.get("idea"))
        built.append(question)
        refs[mcq.ref] = mcq.ref

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
            question.idea = _idea(raw.get("idea")) if isinstance(raw, dict) else None
            built.append(question)
            refs[qid] = qid
            if raw_id and raw_id not in refs:
                refs[raw_id] = qid
    return built, refs


def _fallback_rows(scenes: list[dict[str, Any]]) -> dict[str, list[str]] | None:
    """The rows of the chapter's concept cards: true statements for a fallback game."""
    rows: dict[str, list[str]] = {"en": [], "fr": []}
    for _scene, _index, step in _flat(scenes):
        if step["type"] == "concept" and not str(step.get("id", "")).startswith("situation-"):
            for en, fr in zip(step["en"], step["fr"], strict=False):
                if len(en) <= 120 and len(fr) <= 140:
                    rows["en"].append(en)
                    rows["fr"].append(fr)
    return rows if rows["en"] else None


def _sources(ctx: LessonStoryContext, derived_count: int) -> list[dict[str, Any]]:
    if ctx.is_rally:
        sources: list[dict[str, Any]] = []
    else:
        sources = [
            {
                "kind": "lesson",
                "ref": f"Lesson {ctx.unit_number} — {ctx.unit_title[ctx.target]}",
                "used_for": "story, concepts and key points",
            },
            *(
                {"kind": "lesson", "ref": ref, "used_for": "concepts"}
                for ref in ctx.lesson_list("sources_cited")[:10]
            ),
        ]
    if ctx.has_quiz and derived_count:
        units = sorted({m.quiz_unit for m in ctx.mcqs if m.quiz_unit}) or [
            ctx.quiz_unit_number or ctx.unit_number
        ]
        sources += [
            {"kind": "test", "ref": f"Unit {unit} quiz", "used_for": "questions, derived verbatim"}
            for unit in units
        ]
    return sources


def _chapter_facts(spine: dict[str, Any]) -> list[dict[str, Any]]:
    """Local details the chapter tells: with a source, or marked invented."""
    facts: list[dict[str, Any]] = []
    for item in _items(spine.get("facts"))[:6]:
        if not isinstance(item, dict):
            continue
        text = text_object({"en": item.get("en"), "fr": item.get("fr")})
        if text is None:
            continue
        fact: dict[str, Any] = {"en": text["en"], "fr": text["fr"]}
        source = _as_str(item.get("source"))
        if source and item.get("invented") is not True:
            fact["source"] = source[:200]
            fact["invented"] = False
        else:
            fact["invented"] = True
        facts.append(fact)
    return facts


def _question_facts(built: list[_BuiltQuestion]) -> dict[str, Any]:
    from app.domain.services.story_checks import QuestionFacts

    out: dict[str, Any] = {}
    for question in built:
        doc = question.doc
        if doc["type"] == "choice":
            correct = next((c for c in doc["choices"] if c["id"] == doc["answer"]), {})
            answers = [correct[lang] for lang in LANGS if correct.get(lang)]
        else:
            answers = [_as_str(doc.get("answer"))]
        out[doc["id"]] = QuestionFacts(question.derived, answers, question.idea)
    return out


def _infer_objectives(scenes: list[dict[str, Any]], built: list[_BuiltQuestion]) -> None:
    """A scene without an objective takes the objective of its first question."""
    objective_of = {q.doc["id"]: q.doc.get("objective") for q in built}
    for scene in scenes:
        if scene.get("objective"):
            continue
        for step in scene["steps"]:
            if step["type"] == "ask" and objective_of.get(step.get("ref")):
                scene["objective"] = objective_of[step["ref"]]
                break


def _strip_private(scenes: list[dict[str, Any]]) -> None:
    for scene in scenes:
        for step in scene["steps"]:
            step.pop("_src", None)


def _assemble(
    ctx: LessonStoryContext,
    spine: dict[str, Any],
    *,
    drop_q: set[str],
    drop_e: set[str],
    drop_minigame: bool,
    cover: bool = False,
    story_checks: bool = True,
) -> StoryBuild:
    from app.domain.services.story_checks import check_story
    from app.domain.services.story_props import PropBook

    registry = _Misconceptions(spine.get("misconceptions"))
    held = _Held()
    objectives, objective_map, origins = _objectives(spine.get("objectives"), ctx, held)
    built, question_refs = _questions(ctx, spine, registry, objective_map, drop_q)

    # Exercise ids follow the spine's positions so a salvage pass can name
    # the same exercise again on a rebuild.
    exercises = []
    for number, raw in enumerate(_items(spine.get("exercises")), start=1):
        if f"E{number}" in drop_e:
            continue
        exercise = _exercise(raw, f"E{number}", objective_map, f"exercises[{number - 1}]")
        if exercise is not None:
            exercises.append(exercise)

    bible = ctx.bible_content
    cast = _Cast(doc_cast(bible))
    # v4: only the chapter the episode plan gives the game plays it.
    game_here = not ctx.is_v4 or ctx.has_game
    refs = _Refs(
        questions=question_refs,
        exercises={e["id"]: e["id"] for e in exercises},
        minigame=MINIGAME_ID if game_here else None,
        situations={q.doc["id"]: q for q in built},
        dropped=drop_q | drop_e,
    )
    book = PropBook(
        spine.get("props"),
        known=ctx.known_props,
        figures=ctx.figure_refs(),
        cast_ids=cast.ids,
        issue=builder_issue,
        cast_names=cast.names(),
    )
    # A generated scene is set at one of the bible's places, never at a key of
    # the old catalog: the course's art is made for those places only.
    bible_places = {str(place["id"]) for place in bible.get("places") or []}
    builder = _ScreenplayBuilder(ctx, cast, bible_places, objective_map, refs, book)
    scenes = builder.scenes(spine.get("scenes"))
    if scenes:
        _drop_repeated_lines(scenes, set(), ctx.earlier_line_keys)
        scenes = [s for s in scenes if s["steps"]]
    fallback_cards = 0
    if scenes:
        _place_unasked(scenes, built, refs)
        dropped = _cap_ask_runs(scenes)
        built = [q for q in built if q.doc["id"] not in dropped]
        if not MIN_SCENES <= len(scenes) <= MAX_SCENES:
            builder_issue(
                SCENE_COUNT,
                "scenes",
                f"{len(scenes)} scenes: a chapter tells its lesson in {MIN_SCENES} to"
                f" {MAX_SCENES} scenes, each at one of the course's places",
            )
        if not ctx.is_rally:
            fallback_cards = _check_coverage(
                ctx, scenes, cover=cover, ideas={q.doc["id"]: q.idea for q in built}
            )

    objectives, exercises, moved = _rebalance(objectives, built, exercises)
    for scene in scenes:
        if scene.get("objective"):
            new_id = moved.get(scene["objective"])
            if new_id:
                scene["objective"] = new_id
            else:
                scene.pop("objective")
    held.report(
        ("objective", index)
        for objective, index in origins
        if any(objective is kept for kept in objectives)
    )

    minigame = None
    if game_here:
        fallback = _fallback_rows(scenes)
        minigame = None if drop_minigame else _minigame(spine.get("minigame"), registry, fallback)
        if minigame is None and fallback:
            minigame = _minigame({}, registry, fallback)
    if minigame is not None:
        minigame["objective"] = objectives[0]["id"]

    props: list[dict[str, Any]] = []
    lints: list[ValidationIssue] = []
    quality: dict[str, Any] = {}
    if scenes:
        if minigame is None:
            for scene in scenes:
                scene["steps"] = [s for s in scene["steps"] if s["type"] != "game"]
            refs.minigame = None
        _place_items(scenes, refs, exercises)
        _infer_objectives(scenes, built)
        props = book.finish(scenes, module_count=len(ctx.known_props))
        # The props removed close-ups: runs are capped once more (a backstop,
        # as close-ups are seen through, removing one never joins two runs).
        recapped = _cap_ask_runs(scenes)
        if recapped:
            built = [q for q in built if q.doc["id"] not in recapped]
        if ctx.is_v4 and story_checks:
            story = check_story(
                ctx, scenes, _question_facts(built), builder_issue, fallback_cards=fallback_cards
            )
            lints, quality = story.lints, story.quality
        _strip_private(scenes)
        for number, scene in enumerate(scenes, start=1):
            scene["id"] = f"s{number}"
    else:
        builder_issue(
            NO_SCENES,
            "scenes",
            "no scene could be read: write the chapter as 2 to 4 scenes, each with a place,"
            " the cast on stage and its steps",
        )

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

    title = None
    if ctx.is_rally or ctx.is_v4:
        title = text_object(spine.get("chapter_title"), path="chapter_title")
    chapters = (
        [{"id": "ch1", "title": title or dict(ctx.unit_title), "scenes": scenes}] if scenes else []
    )
    derived_count = sum(1 for q in built if q.derived)
    checks: dict[str, Any] = {
        "predicted_typical": predicted_typical(questions, exercises, minigame)
    }
    if quality:
        checks["story_quality"] = quality
    doc: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "id": ctx.slug,
        "sira_builder": CHAPTER_BUILDER_VERSION,
        "sira_chapter": chapter_marker(ctx),
        "course": ctx.course_title[ctx.target] or ctx.module_title[ctx.target] or "Sira",
        "unit": f"{ctx.unit_number} · {ctx.unit_title[ctx.target]}",
        "week": max(int(ctx.module_number or 1), 1),
        "title": dict(ctx.unit_title),
        "languages": language_pair(ctx.language),
        "learner": {"first_name": CHILD},
        "sources": _sources(ctx, derived_count),
        "objectives": objectives,
        "glossary": [],
        "calibration": [],
        "misconceptions": registry.used_only(used_misconceptions),
        "cast": cast.members,
        "places": doc_places(bible),
        "facts": _chapter_facts(spine),
        "chapters": chapters,
        "questions": questions,
        "exercises": exercises,
        "minigames": [minigame] if minigame else [],
        "videos": [],
        "tutor": _tutor(spine if not ctx.is_v4 else {}, ctx, objectives),
        "rewards": rewards_for(ctx.is_kids),
        "art_requests": [],
        "engine_requests": [],
        "checks": checks,
    }
    if props:
        doc["props"] = props
    enforce_quiz_fidelity(doc, ctx)
    return StoryBuild(
        doc=doc,
        derived_ids=[q.doc["id"] for q in built if q.derived],
        extra_ids=[q.doc["id"] for q in built if not q.derived],
        lints=lints,
        quality=quality,
    )


def chapter_marker(ctx: LessonStoryContext) -> dict[str, Any]:
    """``sira_chapter``: what a chapter was told with, for freshness.

    ``bible`` is the digest of the course bible. v4: ``plan`` is the episode
    plan's global digest, ``beat`` the digest of this chapter's plan entry and
    its questions, ``fact_sheet`` that of the lesson's fact sheet — a chapter
    whose marker differs from what the module needs now is stale; ``prev``
    (the chapter before it, as it was told) and ``pack`` are diagnostic.
    Without a plan, ``arc`` is the chapter's part in the module's mission.
    """
    if ctx.is_v4:
        return {
            "kind": ctx.kind,
            "bible": ctx.bible_digest_value,
            "plan": ctx.plan_global_digest,
            "beat": ctx.beat_digest,
            "fact_sheet": ctx.fact_sheet_digest,
            "prev": ctx.prev_digest,
            "pack": ctx.pack_digest,
        }
    return {"kind": ctx.kind, "bible": ctx.bible_digest_value, "arc": ctx.arc}


def minimal_document(ctx: LessonStoryContext) -> dict[str, Any]:
    """The bare header of the unit's story: what is stored when nothing could be built.

    It parses as ``story-course/1`` (so it can be stored as a draft with its
    report) but has no chapters, so it can never validate or be served.
    """
    return {
        "format": FORMAT_VERSION,
        "id": ctx.slug,
        "sira_builder": CHAPTER_BUILDER_VERSION,
        "sira_chapter": chapter_marker(ctx),
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
        correct = [choices[mcq.correct_index].get(lang, "") for lang in LANGS]
        story = usable_story_stem(ctx, mcq.ref, correct)
        original = question.get("original_stem")
        if story is not None and situation is None:
            # #2698: asked in the story's voice — the approved stem, re-asserted;
            # the quiz's own stem stays on record.
            question["prompt"] = dict(story)
            original = original if isinstance(original, dict) else {}
            question["original_stem"] = {
                target: mcq.stem,
                ctx.home: original.get(ctx.home) or mcq.stem,
            }
            question.pop("stem", None)
            if mcq.explanation and isinstance(question.get("explanation"), dict):
                question["explanation"][target] = mcq.explanation
            continue
        question.pop("original_stem", None)
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


def with_warnings(report: ValidationReport, issues: Iterable[ValidationIssue]) -> ValidationReport:
    """``report`` with extra warnings appended (and its ``checks`` counts kept true)."""
    extra = [i.model_copy(update={"severity": "warning"}) for i in issues]
    if not extra:
        return report
    warnings = [*report.warnings, *extra]
    checks = report.checks.model_copy(update={"warnings": len(warnings)})
    return report.model_copy(update={"warnings": warnings, "checks": checks})


def with_generator_issues(report: ValidationReport, build: StoryBuild) -> ValidationReport:
    """Fold the builder's own findings (copy-fallbacks) into the report as errors.

    That is what makes the repair loop ask the model for the missing
    translation, exactly as it asks for anything the validator found. A prop
    fix (:data:`PROP_CODES`) and the story lints are warnings: they never cost
    a repair call on their own (:data:`QUIET_CODES`). ``checks.story_quality``
    is carried over.
    """
    errors = [i for i in build.issues if i.code not in QUIET_CODES]
    props = [i for i in build.issues if i.code in QUIET_CODES]
    report = with_warnings(with_issues(report, errors), [*props, *build.lints])
    if build.quality:
        checks = report.checks.model_copy(update={"story_quality": dict(build.quality)})
        report = report.model_copy(update={"checks": checks})
    return report


def repair_issues(report: ValidationReport) -> list[ValidationIssue]:
    """What a repair call is told: every error, then the prop fixes (listed only then)."""
    return [*report.errors, *(w for w in report.warnings if w.code in QUIET_CODES)]


def settle_translations(report: ValidationReport) -> ValidationReport:
    """After the repair budget: keep each fix of the builder, as a warning.

    A copied translation, a line cut to its limit, a question placed by the
    builder — each is a last resort (a story with a line in the wrong
    language is still better than none) but never silent: it stays in the
    stored report. Every other error keeps the story unpublished.
    """
    moved = [e for e in report.errors if e.code in SETTLEABLE]
    if not moved:
        return report
    errors = [e for e in report.errors if e.code not in SETTLEABLE]
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
