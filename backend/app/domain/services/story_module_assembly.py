"""The module story: one ``story-course/1`` week per (module, language).

A module story tells a module as one cartoon series episode (#2672): one
chapter per **lesson** unit, in teaching order, then — when the module has a
quiz unit — one final **rally** chapter that mixes questions of the module's
quizzes and resolves the module's mission. Quiz, case-study and scenario
units produce no chapter of their own (their pages still list them). A lesson
chapter is that lesson's own story, made, validated and cached by the
per-lesson pipeline (:mod:`story_repair`, contract C-1); the rally is made by
the same pipeline from the module's quizzes and cached with the module story.
This module joins them (contract C-2). It is pure and deterministic: no
database, no model, no clock, no randomness, so the same inputs always give
byte-identical JSON and a merge costs nothing.

What the assembler does, and nothing else:

* **Ids.** Every id of a chapter — objectives, misconceptions, questions,
  exercises, mini-games, videos, concept steps — and every reference to one
  is namespaced ``u{key}-`` (``key`` is the unit number with every
  non-alphanumeric character replaced by ``_``). Chapters are renumbered
  ``ch1..chN`` and scenes ``s1..sM`` over the whole document. Cast and place
  ids are not namespaced: every chapter has the course bible's.
* **The bible.** The document's ``cast`` (with ``role``, ``look``,
  ``variants``) and ``places`` are the course bible's (:mod:`story_bible`),
  identical in every module story of the course; its facts join the
  chapters' own.
* **Duplicates.** A quiz question copied into two lessons' chapters (both
  carry ``derived_from`` and read the same stem, options and answer in the
  target language) is kept in the first; a later copy is dropped unless that
  would leave its chapter with fewer than :data:`story_repair.MIN_QUESTIONS`.
  The rally is a review and keeps its questions. A story line told again in a
  later chapter is dropped there.
* **Everything module-level**: header, merged sources, objectives,
  misconceptions, glossary and facts, the tutor brief, rewards, the summed
  typical run, and the ``covers`` and ``module_story`` metadata. A lesson
  whose chapter is not ready keeps a "read it on its page" placeholder chapter
  (``frame`` ``unavailable``), so completion still works.

It never edits a text a learner reads: every question, choice, hint,
explanation, exercise, mini-game, line and concept row is the chapter's own,
so the verbatim quiz MCQs that :mod:`mcq_checks` checked stay verbatim. An
``option_misconceptions`` key is never copied.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from app.api.v1.schemas.story_course import (
    FORMAT_VERSION,
    StoryCourse,
    ValidationIssue,
    ValidationReport,
)
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import (
    StoryBible,
    default_bible,
    doc_cast,
    doc_facts,
    doc_places,
)
from app.domain.services.story_course_validator import (
    MIN_REPEAT_LENGTH,
    line_key,
    validate_story_course,
)

logger = structlog.get_logger(__name__)

#: Recorded in ``module_story.assembler`` and the module row's manifest; a
#: stored module story built by another version is stale. 2: the screenplay
#: generator with the course bible (#2674) — chapters only for lessons, plus
#: the rally.
MODULE_ASSEMBLER_VERSION = 2

UnitRole = Literal["lesson", "quiz_checkpoint", "case_checkpoint"]
ChapterStatus = Literal["ready", "unavailable", "checkpoint"]

#: Unit types completed without a quiz, other than lessons (progress.py).
CASE_UNIT_TYPES = frozenset({"case-study", "scenario"})

#: The ``frame`` marker of the only lines the assembler writes: the
#: placeholder of a lesson whose chapter is not ready.
FRAME_UNAVAILABLE = "unavailable"
GENERATED_FRAMES = (FRAME_UNAVAILABLE,)

#: Never copied from a chapter, at any depth: a quiz's per-option
#: misconceptions are prompt input, not story content.
_NEVER_COPIED = "option_misconceptions"

_KEY_RE = re.compile(r"[^A-Za-z0-9]")


# --------------------------------------------------------------------------
# Contract C-2: inputs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StoryUnit:
    """One unit of the module, as the story sees it."""

    module_unit_id: uuid.UUID
    unit_number: str
    unit_type: str | None
    order_index: int
    role: UnitRole
    title: dict[str, str]  # {"en", "fr"}


@dataclass(frozen=True)
class ChapterSource:
    """A unit and, for a lesson (or the rally), its chapter document.

    ``doc`` is the fresh, valid, published chapter for role ``"lesson"``;
    ``None`` means the lesson's chapter is unavailable. It is ignored for
    other units.
    """

    unit: StoryUnit
    doc: dict[str, Any] | None


@dataclass(frozen=True)
class ModuleStoryContext:
    module_id: uuid.UUID
    language: str
    module_number: int
    module_title: dict[str, str]
    course_title: dict[str, str]
    previous_module: tuple[int, dict[str, str]] | None
    is_kids: bool
    #: The course bible; ``None``: the audience's default (a module without a course).
    bible: StoryBible | None = None

    @property
    def story_bible(self) -> StoryBible:
        return self.bible or default_bible(self.is_kids)


def module_story_slug(module_id: uuid.UUID, language: str) -> str:
    """The reserved id of a module story; it can never collide with authored weeks."""
    return f"module-{module_id.hex}-{language}"


def unit_role(unit_type: str | None, *, has_case_content: bool = False) -> UnitRole:
    """A unit's role, classified exactly as the completion API does (progress.py).

    ``None`` (legacy rows) and ``"lesson"`` are lessons. ``"case-study"`` and
    ``"scenario"`` are case checkpoints, and so is any other type whose unit
    holds cached case content (#2163). Everything else — ``"quiz"`` and any
    unknown type, which completion treats as quiz-gated — is a quiz checkpoint.
    """
    if unit_type is None or unit_type == "lesson":
        return "lesson"
    if unit_type in CASE_UNIT_TYPES or has_case_content:
        return "case_checkpoint"
    return "quiz_checkpoint"


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace, UTF-8 kept: the form every digest is taken of."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if isinstance(value, str | int | float) else ""


def _pair(title: Any, fallback_en: str, fallback_fr: str) -> dict[str, str]:
    """``{"en", "fr"}`` with each language falling back to the other, then to a default."""
    title = title if isinstance(title, dict) else {}
    en, fr = _text(title.get("en")), _text(title.get("fr"))
    return {"en": en or fr or fallback_en, "fr": fr or en or fallback_fr}


def _unit_title(unit: StoryUnit) -> dict[str, str]:
    number = _text(unit.unit_number)
    return _pair(unit.title, f"Unit {number}".strip(), f"Unité {number}".strip())


def _line(kind: str, en: str, fr: str, frame: str, who: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"type": kind}
    if who:
        step["who"] = who
    step["en"] = repair.truncate(en, repair.STORY_LINE_LIMIT)
    step["fr"] = repair.truncate(fr, repair.STORY_LINE_LIMIT)
    step["frame"] = frame
    return step


def _concept(
    step_id: str, title: dict[str, str], rows: dict[str, list[str]], frame: str
) -> dict[str, Any]:
    return {
        "type": "concept",
        "id": step_id,
        "title": title,
        "en": list(rows["en"]),
        "fr": list(rows["fr"]),
        "frame": frame,
    }


def _without_forbidden(value: Any) -> Any:
    """A copy of ``value`` with every ``option_misconceptions`` key removed."""
    if isinstance(value, dict):
        return {k: _without_forbidden(v) for k, v in value.items() if k != _NEVER_COPIED}
    if isinstance(value, list):
        return [_without_forbidden(v) for v in value]
    return copy.deepcopy(value)


def _prefixes(sources: Sequence[ChapterSource]) -> list[str]:
    """``u{key}-`` per unit; a key two unit numbers share gets ``_2``, ``_3``…"""
    used: set[str] = set()
    out: list[str] = []
    for source in sources:
        base = _KEY_RE.sub("_", str(source.unit.unit_number or ""))
        key, n = base, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        used.add(key)
        out.append(f"u{key}-")
    return out


# --------------------------------------------------------------------------
# Which lesson chapters can be used
# --------------------------------------------------------------------------


def _unusable_reason(source: ChapterSource, language: str) -> str | None:
    """Why a lesson's chapter document cannot be joined, or ``None``.

    The document must be a ``story-course/1`` week built by this chapter
    builder (``sira_builder``), for this unit and this language, with at
    least one chapter. Anything else becomes the "not in the story yet"
    placeholder, never an error of the module story.
    """
    doc = source.doc
    if doc is None:
        return "missing"
    if not isinstance(doc, dict):
        return "not_an_object"
    if doc.get("sira_builder") != repair.CHAPTER_BUILDER_VERSION:
        return "old_builder"
    languages = doc.get("languages")
    if not isinstance(languages, dict) or languages.get("target") != language:
        return "wrong_language"
    if doc.get("id") != repair.story_slug(source.unit.module_unit_id, language):
        return "wrong_unit"
    try:
        course = StoryCourse.model_validate(doc)
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        return "malformed"
    if not course.chapters:
        return "no_chapters"
    return None


# --------------------------------------------------------------------------
# Cross-chapter de-duplication of quiz questions
# --------------------------------------------------------------------------


#: What makes two copied quiz questions the same question for the learner.
DerivedKey = tuple[str, tuple[str, ...], str]


def derived_key(question: dict[str, Any], language: str) -> DerivedKey | None:
    """The verbatim quiz question a derived question copies, by its content.

    Only a question with ``derived_from`` (C-1) is a copy, but its identity is
    what the learner reads in the target language — the stem (or the prompt
    when the stem fits it), the options in order and the correct one — never
    the ``(quiz_unit, question_id)`` label. Two chapters can be built from
    different quiz rows of one quiz unit (another level or country) whose
    generated ids are the same ``q1..qN`` for other questions; and a quiz unit
    renumbered between two chapters' builds labels one question twice.
    """
    if not isinstance(question.get("derived_from"), dict):
        return None
    reading = question.get("stem")
    if not isinstance(reading, dict):
        reading = question.get("prompt")
    text = _text(reading.get(language)) if isinstance(reading, dict) else ""
    choices = question.get("choices")
    options = (
        tuple(_text(c.get(language)) for c in choices or [] if isinstance(c, dict))
        if isinstance(choices, list)
        else ()
    )
    answer = question.get("answer")
    if not text or not options or not all(options) or not isinstance(answer, str):
        return None
    return text, options, answer


def _question_points(doc: dict[str, Any], question: dict[str, Any]) -> int:
    """What the validator counts for ``question`` in ``doc``'s ``max_points``."""
    if isinstance(question.get("points"), int):
        return int(question["points"])
    rewards = doc.get("rewards")
    first_try = rewards.get("first_try", 2) if isinstance(rewards, dict) else 2
    return int(first_try or 2)


def _used_misconceptions(doc: dict[str, Any]) -> set[str]:
    used: set[str] = set()
    for question in doc.get("questions", []):
        used.update(
            c["misconception"] for c in question.get("choices", []) if c.get("misconception")
        )
        used.update(t["misconception"] for t in question.get("traps", []) if t.get("misconception"))
    for exercise in doc.get("exercises", []):
        used.update(t["misconception"] for t in exercise.get("traps", []) if t.get("misconception"))
    for game in doc.get("minigames", []):
        used.update(v for v in (game.get("traps") or {}).values() if isinstance(v, str))
        for round_data in game.get("rounds", []):
            items = round_data.get("items") if isinstance(round_data, dict) else None
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and isinstance(item.get("trap"), str):
                    used.add(item["trap"])
    for row in doc.get("calibration", []):
        if isinstance(row, dict) and row.get("misconception"):
            used.add(row["misconception"])
    return used


def _drop_questions(doc: dict[str, Any], ids: set[str]) -> int:
    """Remove questions, their ask and situation steps and now-unused misconceptions.

    Returns the points the validator would have counted for them.
    """
    points = sum(_question_points(doc, q) for q in doc["questions"] if q["id"] in ids)
    doc["questions"] = [q for q in doc["questions"] if q["id"] not in ids]
    situations = {repair.situation_step_id(qid) for qid in ids}
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            scene["steps"] = [
                step
                for step in scene["steps"]
                if not (step.get("type") == "ask" and step.get("ref") in ids)
                and not (step.get("type") == "concept" and step.get("id") in situations)
            ]
        chapter["scenes"] = [scene for scene in chapter["scenes"] if scene["steps"]]
    used = _used_misconceptions(doc)
    doc["misconceptions"] = [m for m in doc.get("misconceptions", []) if m.get("id") in used]
    return points


def _deduplicate(docs: dict[int, dict[str, Any]], language: str) -> dict[int, list[str]]:
    """Drop later copies of a quiz question, in chapter order, with the floor rule.

    Copies are the same verbatim question (:func:`derived_key`). A copy is
    kept when dropping it would leave its chapter with fewer than
    :data:`story_repair.MIN_QUESTIONS` questions. Returns the dropped ids per
    chapter index (ids as the chapter had them).
    """
    seen: set[DerivedKey] = set()
    dropped: dict[int, list[str]] = {}
    for index in sorted(docs):
        doc = docs[index]
        remaining = len(doc["questions"])
        drop: list[str] = []
        for question in doc["questions"]:
            key = derived_key(question, language)
            if key is None:
                continue
            if key not in seen:
                seen.add(key)
            elif remaining - 1 >= repair.MIN_QUESTIONS:
                drop.append(question["id"])
                remaining -= 1
        if drop:
            dropped[index] = drop
    return dropped


# --------------------------------------------------------------------------
# Namespacing
# --------------------------------------------------------------------------


class _Namespace:
    """Prefixes one chapter's ids and every reference to them."""

    def __init__(self, prefix: str, doc: dict[str, Any]) -> None:
        self.prefix = prefix
        self.question_ids = {q["id"] for q in doc.get("questions", [])}

    def id(self, value: Any) -> Any:
        return f"{self.prefix}{value}" if isinstance(value, str) and value else value

    def objective(self, item: dict[str, Any]) -> None:
        if item.get("objective"):
            item["objective"] = self.id(item["objective"])

    def traps(self, item: dict[str, Any]) -> None:
        for trap in item.get("traps") or []:
            if isinstance(trap, dict) and trap.get("misconception"):
                trap["misconception"] = self.id(trap["misconception"])

    def question(self, question: dict[str, Any]) -> dict[str, Any]:
        question["id"] = self.id(question["id"])
        self.objective(question)
        for choice in question.get("choices") or []:
            if choice.get("misconception"):
                choice["misconception"] = self.id(choice["misconception"])
        self.traps(question)
        if isinstance(question.get("review_of"), str) and question["review_of"] in (
            self.question_ids
        ):
            question["review_of"] = self.id(question["review_of"])
        return question

    def exercise(self, exercise: dict[str, Any]) -> dict[str, Any]:
        exercise["id"] = self.id(exercise["id"])
        self.objective(exercise)
        self.traps(exercise)
        return exercise

    def minigame(self, game: dict[str, Any]) -> dict[str, Any]:
        game["id"] = self.id(game["id"])
        self.objective(game)
        if isinstance(game.get("traps"), dict):
            game["traps"] = {target: self.id(m) for target, m in game["traps"].items()}
        for round_data in game.get("rounds") or []:
            items = round_data.get("items") if isinstance(round_data, dict) else None
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and item.get("trap"):
                    item["trap"] = self.id(item["trap"])
        return game

    def step(self, step: dict[str, Any]) -> dict[str, Any]:
        if step.get("id"):
            step["id"] = self.id(step["id"])
        if step.get("type") in ("ask", "game", "photo", "video") and step.get("ref"):
            step["ref"] = self.id(step["ref"])
        return step

    def calibration(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("misconception"):
            row["misconception"] = self.id(row["misconception"])
        return row

    def with_id(self, item: dict[str, Any]) -> dict[str, Any]:
        item["id"] = self.id(item["id"])
        return item


# --------------------------------------------------------------------------
# The placeholder of a lesson whose chapter is not ready
# --------------------------------------------------------------------------


def _unavailable_scene(unit: StoryUnit, prefix: str, place: str, cast: list[str]) -> dict[str, Any]:
    number = unit.unit_number
    title = _unit_title(unit)
    return {
        "place": place,
        "cast": cast,
        "steps": [
            _line(
                "narrate",
                f"Lesson {number} is not in the story yet, {{child}}.",
                f"La leçon {number} n'est pas encore dans l'histoire, {{child}}.",
                FRAME_UNAVAILABLE,
            ),
            _concept(
                f"{prefix}unavailable",
                {"en": f"Lesson {number}", "fr": f"Leçon {number}"},
                {"en": [title["en"]], "fr": [title["fr"]]},
                FRAME_UNAVAILABLE,
            ),
            _line(
                "say",
                f"Read lesson {number} on its own page, {{child}}, then come back.",
                f"Lis la leçon {number} sur sa page, {{child}}, puis reviens.",
                FRAME_UNAVAILABLE,
                repair.MENTOR_ID,
            ),
        ],
    }


# --------------------------------------------------------------------------
# The tutor
# --------------------------------------------------------------------------


def _tutor(ctx: ModuleStoryContext, objective_ids: list[str]) -> dict[str, Any]:
    who_to_ask = (
        {"en": "your teacher or your family", "fr": "ton enseignant ou ta famille"}
        if ctx.is_kids
        else {"en": "your supervisor or a colleague", "fr": "ton encadrant ou un collègue"}
    )
    earlier = None
    if ctx.previous_module is not None:
        number, title = ctx.previous_module
        previous = _pair(title, f"Module {number}", f"Module {number}")
        earlier = f"Module {number}: {previous[ctx.language]}"
    return {
        "persona": repair.TUTOR_ID,
        "intro": {
            "en": "Hi {child}! I'm Margo, your guide in this module. I am an AI, not a real person.",
            "fr": (
                "Bonjour {child} ! Je suis Margo, ton guide dans ce module."
                " Je suis une IA, pas une vraie personne."
            ),
        },
        "scope": {"this_week": objective_ids, "earlier_weeks": earlier},
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
            "Talk about anything other than this module.",
        ],
        "off_topic": {
            "en": f"Let's stay on this module. Ask {who_to_ask['en']} about that.",
            "fr": f"Restons sur ce module. Pose cette question à {who_to_ask['fr']}.",
        },
        "worry": {
            "en": "That sounds important. Please talk to someone you trust now.",
            "fr": "Cela semble important. Parles-en tout de suite à une personne de confiance.",
        },
        "max_turns_per_item": 6,
    }


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


@dataclass
class _Ready:
    """A lesson chapter being joined: the working copy and what dedup took out."""

    doc: dict[str, Any]
    dropped_points: int = 0


def _merge_unique(
    target: list[dict[str, Any]], items: Any, key: Callable[[dict[str, Any]], Any]
) -> None:
    seen = {key(item) for item in target}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and key(item) not in seen:
            seen.add(key(item))
            target.append(copy.deepcopy(item))


#: The collections a module story merges from its chapters, in document order.
_MERGED = (
    "sources",
    "objectives",
    "glossary",
    "calibration",
    "misconceptions",
    "facts",
    "questions",
    "exercises",
    "minigames",
    "videos",
    "art_requests",
    "engine_requests",
)


def _merge_chapter(
    merged: dict[str, list[dict[str, Any]]], doc: dict[str, Any], ns: _Namespace
) -> None:
    """Add one ready chapter's items, namespaced, to the module's collections.

    Objectives (at most three per chapter, as the builder made them),
    misconceptions, questions, exercises, mini-games, videos and calibration
    rows are concatenated: their namespaced ids cannot collide. Sources are
    de-duplicated by (kind, ref), glossary entries and facts by text, art and
    engine requests by name, first one wins.
    """
    merged["objectives"].extend(ns.with_id(o) for o in doc.get("objectives", []))
    merged["misconceptions"].extend(ns.with_id(m) for m in doc.get("misconceptions", []))
    merged["questions"].extend(ns.question(q) for q in doc.get("questions", []))
    merged["exercises"].extend(ns.exercise(e) for e in doc.get("exercises", []))
    merged["minigames"].extend(ns.minigame(g) for g in doc.get("minigames", []))
    merged["videos"].extend(ns.with_id(v) for v in doc.get("videos", []))
    merged["calibration"].extend(ns.calibration(r) for r in doc.get("calibration", []))
    _merge_unique(merged["sources"], doc.get("sources"), lambda s: (s.get("kind"), s.get("ref")))
    _merge_unique(merged["glossary"], doc.get("glossary"), lambda g: (g.get("en"), g.get("fr")))
    _merge_unique(merged["facts"], doc.get("facts"), lambda f: (f.get("en"), f.get("fr")))
    _merge_unique(merged["art_requests"], doc.get("art_requests"), lambda a: a.get("name"))
    _merge_unique(merged["engine_requests"], doc.get("engine_requests"), lambda e: e.get("engine"))


def _lesson_scenes(doc: dict[str, Any], ns: _Namespace) -> list[dict[str, Any]]:
    """The chapter's scenes, flattened from its chapters, namespaced."""
    scenes: list[dict[str, Any]] = []
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            steps = [ns.step(step) for step in scene["steps"]]
            if not steps:
                continue
            out = {key: value for key, value in scene.items() if key != "steps"}
            if out.get("objective"):
                out["objective"] = ns.id(out["objective"])
            out["steps"] = steps
            scenes.append(out)
    return scenes


def _typical(doc: dict[str, Any]) -> dict[str, Any]:
    minigames = doc.get("minigames") or []
    return repair.predicted_typical(
        doc.get("questions") or [], doc.get("exercises") or [], minigames[0] if minigames else None
    )


def _max_points(source_doc: dict[str, Any], dropped_points: int) -> int:
    checks = source_doc.get("checks")
    max_points = checks.get("max_points") if isinstance(checks, dict) else None
    if not isinstance(max_points, int) or isinstance(max_points, bool) or max_points <= 0:
        return 0
    return max(max_points - dropped_points, 0)


def _drop_retold_lines(scenes: list[dict[str, Any]], seen: set[tuple[str, str]]) -> None:
    """A line told in an earlier chapter is dropped from this one (never a frame line)."""
    for scene in scenes:
        kept: list[dict[str, Any]] = []
        for step in scene["steps"]:
            if step.get("type") in ("narrate", "say") and not step.get("frame"):
                keys = {
                    (lang, line_key(step.get(lang)))
                    for lang in ("en", "fr")
                    if isinstance(step.get(lang), str)
                }
                keys = {key for key in keys if len(key[1]) >= MIN_REPEAT_LENGTH}
                if keys & seen:
                    continue
                seen |= keys
            kept.append(step)
        scene["steps"] = kept


def _rally_unit(sources: Sequence[ChapterSource]) -> StoryUnit | None:
    """The quiz unit the rally chapter covers: the module's last quiz unit."""
    quizzes = [s.unit for s in sources if s.unit.role == "quiz_checkpoint"]
    return quizzes[-1] if quizzes else None


def assemble_module_story(
    ctx: ModuleStoryContext,
    chapters: Sequence[ChapterSource],
    rally: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Join a module's chapters into one ``story-course/1`` week (contract C-2).

    ``chapters`` are the module's units in teaching order, each with its
    lesson's chapter document (``None`` for other units); ``rally`` is the
    rally's chapter document, told for the module's last quiz unit. Pure and
    deterministic; never mutates its inputs. A lesson whose document cannot be
    joined (see :func:`_unusable_reason`) becomes a "read it on its page"
    placeholder; an unusable rally is left out. The result is validated by
    the caller with :func:`validate_module_story`.
    """
    sources = list(chapters)
    language = ctx.language
    bible = ctx.story_bible
    rally_unit = _rally_unit(sources)
    told = [s for s in sources if s.unit.role == "lesson"]
    rally_source = None
    if rally is not None and rally_unit is not None:
        candidate = ChapterSource(unit=rally_unit, doc=rally)
        reason = _unusable_reason(candidate, language)
        if reason is None:
            rally_source = candidate
        else:
            logger.warning(
                "Rally chapter left out of the module story",
                module_id=str(ctx.module_id),
                reason=reason,
            )
    if rally_source is not None:
        told.append(rally_source)
    prefixes = _prefixes(told)

    ready: dict[int, _Ready] = {}
    statuses: list[ChapterStatus] = []
    for index, source in enumerate(told):
        if source is rally_source:
            ready[index] = _Ready(doc=_without_forbidden(source.doc))
            statuses.append("checkpoint")
            continue
        reason = _unusable_reason(source, language)
        if reason is None:
            ready[index] = _Ready(doc=_without_forbidden(source.doc))
            statuses.append("ready")
        else:
            statuses.append("unavailable")
            logger.warning(
                "Lesson chapter left out of the module story",
                module_id=str(ctx.module_id),
                unit=source.unit.unit_number,
                reason=reason,
            )

    lessons_ready = {i: r.doc for i, r in ready.items() if told[i] is not rally_source}
    for index, ids in _deduplicate(lessons_ready, language).items():
        ready[index].dropped_points = _drop_questions(ready[index].doc, set(ids))
        logger.info(
            "Quiz questions already told by an earlier chapter left out",
            module_id=str(ctx.module_id),
            unit=told[index].unit.unit_number,
            questions=ids,
        )

    module_chapters: list[dict[str, Any]] = []
    merged: dict[str, list[dict[str, Any]]] = {name: [] for name in _MERGED}
    merged["facts"].extend(doc_facts(bible.content))
    typical_points = 0
    typical_plans: list[str] = []
    seen_lines: set[tuple[str, str]] = set()
    place = next(iter(p["id"] for p in doc_places(bible.content)), "classroom")

    for index, source in enumerate(told):
        unit, prefix = source.unit, prefixes[index]
        title = _unit_title(unit)
        max_points = 0
        if index in ready:
            chapter_doc = ready[index].doc
            ns = _Namespace(prefix, chapter_doc)
            scenes = _lesson_scenes(chapter_doc, ns)
            _drop_retold_lines(scenes, seen_lines)
            scenes = [scene for scene in scenes if scene["steps"]]
            _merge_chapter(merged, chapter_doc, ns)
            typical = _typical(chapter_doc)
            typical_points += int(typical["points"])
            label = "Rally" if source is rally_source else f"Lesson {unit.unit_number}"
            typical_plans.append(f"{label}: {typical['plan']}")
            max_points = _max_points(source.doc or {}, ready[index].dropped_points)
        else:
            scenes = [_unavailable_scene(unit, prefix, place, [repair.MENTOR_ID])]

        if source is rally_source:
            chapter_title = _pair(
                (chapter_doc.get("chapters") or [{}])[0].get("title"), "The rally", "Le rallye"
            )
            covers = {
                "module_unit_id": str(unit.module_unit_id),
                "unit_number": unit.unit_number,
                "unit_type": unit.unit_type,
                "role": unit.role,
                "status": "checkpoint",
                # Story points never become a quiz score: the quiz unit is
                # still taken on its own page.
                "completes_unit": False,
                "max_points": max_points,
                "rally": True,
            }
        else:
            chapter_title = {
                "en": f"{unit.unit_number} · {title['en']}",
                "fr": f"{unit.unit_number} · {title['fr']}",
            }
            status = statuses[index]
            covers = {
                "module_unit_id": str(unit.module_unit_id),
                "unit_number": unit.unit_number,
                "unit_type": unit.unit_type,
                "role": unit.role,
                "status": status,
                "completes_unit": status == "ready",
                "max_points": max_points,
            }
        module_chapters.append(
            {"id": f"ch{index + 1}", "title": chapter_title, "scenes": scenes, "covers": covers}
        )

    scene_number = 0
    for chapter in module_chapters:
        renumbered = []
        for scene in chapter["scenes"]:
            scene_number += 1
            rest = {key: value for key, value in scene.items() if key != "id"}
            renumbered.append({"id": f"s{scene_number}", **rest})
        chapter["scenes"] = renumbered

    module_title = _pair(
        ctx.module_title, f"Module {ctx.module_number}", f"Module {ctx.module_number}"
    )
    course_title = _pair(ctx.course_title, "", "")
    revision_rows = [
        [
            str(source.unit.module_unit_id),
            "rally" if source is rally_source else source.unit.role,
            _sha256(source.doc) if index in ready else None,
        ]
        for index, source in enumerate(told)
    ]
    revision_rows.append(["bible", bible.digest, repair.CHAPTER_BUILDER_VERSION])
    doc: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "id": module_story_slug(ctx.module_id, language),
        "course": course_title[language] or module_title[language] or "Sira",
        "unit": f"Module {ctx.module_number} · {module_title[language]}",
        "week": max(int(ctx.module_number or 1), 1),
        "title": module_title,
        "languages": repair.language_pair(language),
        "learner": {"first_name": repair.CHILD},
        "sources": merged["sources"],
        "objectives": merged["objectives"],
        "glossary": merged["glossary"],
        "calibration": merged["calibration"],
        "misconceptions": merged["misconceptions"],
        "cast": doc_cast(bible.content),
        "places": doc_places(bible.content),
        "facts": merged["facts"],
        "chapters": module_chapters,
        "questions": merged["questions"],
        "exercises": merged["exercises"],
        "minigames": merged["minigames"],
        "videos": merged["videos"],
        "tutor": _tutor(ctx, [o["id"] for o in merged["objectives"]]),
        "rewards": repair.rewards_for(ctx.is_kids),
        "art_requests": merged["art_requests"],
        "engine_requests": merged["engine_requests"],
        "checks": {
            "predicted_typical": {
                "plan": " ".join(typical_plans) or "No lesson chapter yet: no points.",
                "points": typical_points,
            }
        },
        "module_story": {
            "module_id": str(ctx.module_id),
            "module_number": ctx.module_number,
            "assembler": MODULE_ASSEMBLER_VERSION,
            "generator": repair.CHAPTER_BUILDER_VERSION,
            "bible": bible.digest,
            "revision": _sha256(revision_rows)[:16],
        },
    }
    logger.info(
        "Module story assembled",
        module_id=str(ctx.module_id),
        language=language,
        chapters=len(module_chapters),
        ready=statuses.count("ready"),
        unavailable=statuses.count("unavailable"),
        rally=rally_source is not None,
        questions=len(doc["questions"]),
    )
    return doc


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _failed(code: str, message: str) -> ValidationReport:
    report = ValidationReport(
        ok=False,
        errors=[ValidationIssue(severity="error", code=code, path="", message=message[:500])],
    )
    return report.model_copy(update={"checks": report.checks.model_copy(update={"errors": 1})})


def validate_module_story(doc: dict[str, Any]) -> ValidationReport:
    """Appendix C plus the generator's own checks (:func:`story_repair.publishable`).

    Never raises: a document that does not parse is reported as
    ``malformed_course_file``. Only a Celery time limit propagates.
    """
    try:
        course = StoryCourse.model_validate(doc)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        return _failed("malformed_course_file", str(exc))
    try:
        return repair.publishable(validate_story_course(course), doc)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # pragma: no cover - the validator owns its shapes
        logger.exception("Module story validation failed", error=str(exc)[:300])
        return _failed("validator_failed", f"{type(exc).__name__}: {exc}")
