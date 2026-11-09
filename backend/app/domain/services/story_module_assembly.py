"""The module story: one ``story-course/1`` week per (module, language).

A module story has exactly one chapter per unit of the module, in teaching
order. A lesson unit's chapter is that lesson's own story — made, validated
and cached by the per-lesson pipeline (:mod:`story_repair`, contract C-1) —
and a quiz, case-study or scenario unit's chapter is a short checkpoint scene
that sends the learner to the unit's own page. This module joins them
(contract C-2). It is pure and deterministic: no database, no model, no
clock, no randomness, so the same inputs always give byte-identical JSON and
a merge costs nothing.

What the assembler does, and nothing else:

* **Ids.** Every id of a chapter — objectives, misconceptions, questions,
  exercises, mini-games, videos, concept steps — and every reference to one
  is namespaced ``u{key}-`` (``key`` is the unit number with every
  non-alphanumeric character replaced by ``_``). Chapters are renumbered
  ``ch1..chN`` and scenes ``s1..sM`` over the whole document. Cast ids are
  not namespaced: every chapter has the same :func:`story_repair.pinned_cast`.
* **Frames, by marker only.** A lesson's ``opener`` and ``ask_tutor`` steps
  are dropped and its ``finished`` step becomes a "lesson X is done" line;
  its ``objectives`` step is kept. The first chapter opens with a module
  intro scene listing every unit, and the last one closes with the module's
  closing scene. Every step the assembler writes carries a ``frame`` marker
  (see :data:`GENERATED_FRAMES`) and addresses ``{child}``.
* **Duplicates.** A quiz question copied into two lessons' chapters (same
  ``derived_from``) is kept in the first; a later copy is dropped unless that
  would leave its chapter with fewer than :data:`story_repair.MIN_QUESTIONS`.
* **Everything module-level**: header, merged sources, objectives,
  misconceptions, glossary and facts, the tutor brief, rewards, one pass of
  ask spacing (the same bridges as a lesson story), the summed typical run,
  and the ``covers`` and ``module_story`` metadata.

It never edits a text a learner reads, apart from those frame lines: every
question, choice, hint, explanation, exercise, mini-game and concept row is
the chapter's own, so the verbatim quiz MCQs that :mod:`mcq_checks` checked
stay verbatim. Learner-facing text never comes from anywhere but the chapter
documents and the fixed frame lines here; an ``option_misconceptions`` key is
never copied.
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
from app.domain.services.story_course_validator import validate_story_course

logger = structlog.get_logger(__name__)

#: Recorded in ``module_story.assembler``; a stored module story built by
#: another version is stale.
MODULE_ASSEMBLER_VERSION = 1

UnitRole = Literal["lesson", "quiz_checkpoint", "case_checkpoint"]
ChapterStatus = Literal["ready", "unavailable", "checkpoint"]

#: Unit types completed without a quiz, other than lessons (progress.py).
CASE_UNIT_TYPES = frozenset({"case-study", "scenario"})

#: The ``frame`` markers of the steps the assembler writes. ``objectives``,
#: the one chapter frame kept, is a lesson's own step.
FRAME_OPENER = repair.FRAME_OPENER
FRAME_MODULE_INTRO = "module_intro"
FRAME_MODULE_OVERVIEW = "module_overview"
FRAME_LESSON_DONE = "lesson_done"
FRAME_CHECKPOINT = "checkpoint"
FRAME_UNAVAILABLE = "unavailable"
FRAME_FINISHED = repair.FRAME_FINISHED
FRAME_CHECKPOINT_REMINDER = "checkpoint_reminder"
FRAME_ASK_TUTOR = repair.FRAME_ASK_TUTOR
GENERATED_FRAMES = (
    FRAME_OPENER,
    FRAME_MODULE_INTRO,
    FRAME_MODULE_OVERVIEW,
    FRAME_LESSON_DONE,
    FRAME_CHECKPOINT,
    FRAME_UNAVAILABLE,
    FRAME_FINISHED,
    FRAME_CHECKPOINT_REMINDER,
    FRAME_ASK_TUTOR,
)

#: The chapter frames dropped from every lesson: the module has one opener
#: and one closing line to the tutor.
_DROPPED_FRAMES = frozenset({repair.FRAME_OPENER, repair.FRAME_ASK_TUTOR})

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
    """A unit and, for a lesson, its chapter document.

    ``doc`` is the fresh, valid, published chapter (a lesson story, C-1) for
    role ``"lesson"``; ``None`` means the lesson's chapter is unavailable. It
    is ignored for checkpoints.
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


def _derived_key(question: dict[str, Any]) -> tuple[str, str] | None:
    source = question.get("derived_from")
    if not isinstance(source, dict):
        return None
    quiz_unit, question_id = source.get("quiz_unit"), source.get("question_id")
    if isinstance(quiz_unit, str) and isinstance(question_id, str):
        return quiz_unit, question_id
    return None


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


def _deduplicate(docs: dict[int, dict[str, Any]]) -> dict[int, list[str]]:
    """Drop later copies of a quiz question, in chapter order, with the floor rule.

    A copy is kept when dropping it would leave its chapter with fewer than
    :data:`story_repair.MIN_QUESTIONS` questions. Returns the dropped ids per
    chapter index (ids as the chapter had them).
    """
    seen: set[tuple[str, str]] = set()
    dropped: dict[int, list[str]] = {}
    for index in sorted(docs):
        doc = docs[index]
        remaining = len(doc["questions"])
        drop: list[str] = []
        for question in doc["questions"]:
            key = _derived_key(question)
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
# Frame lines (FR and EN, {child}, at most 100 characters, gender-neutral tu)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Kind:
    """How a checkpoint unit is named."""

    en: str  # "the quiz"
    fr: str  # "le quiz"
    title_en: str  # "Quiz"
    title_fr: str  # "Quiz"
    label_en: str  # " (quiz)" in the module overview
    label_fr: str
    leave_en: str  # the mentor's line sending the learner to the unit's page
    leave_fr: str


_QUIZ = _Kind(
    en="the quiz",
    fr="le quiz",
    title_en="Quiz",
    title_fr="Quiz",
    label_en=" (quiz)",
    label_fr=" (quiz)",
    leave_en="This quiz is not part of the story, {child}: take it on its page.",
    leave_fr="Ce quiz ne fait pas partie de l'histoire, {child} : fais-le sur sa page.",
)
_CASE = _Kind(
    en="the case study",
    fr="l'étude de cas",
    title_en="Case study",
    title_fr="Étude de cas",
    label_en=" (case study)",
    label_fr=" (étude de cas)",
    leave_en="This case study is not part of the story, {child}: work on it on its page.",
    leave_fr="Cette étude de cas ne fait pas partie de l'histoire, {child} : fais-la sur sa page.",
)
_SCENARIO = _Kind(
    en="the scenario",
    fr="la mise en situation",
    title_en="Scenario",
    title_fr="Mise en situation",
    label_en=" (scenario)",
    label_fr=" (mise en situation)",
    leave_en="This scenario is not part of the story, {child}: work on it on its page.",
    leave_fr=(
        "Cette mise en situation ne fait pas partie de l'histoire, {child} : fais-la sur sa page."
    ),
)


def _kind(unit: StoryUnit) -> _Kind | None:
    if unit.role == "quiz_checkpoint":
        return _QUIZ
    if unit.role == "case_checkpoint":
        return _SCENARIO if unit.unit_type == "scenario" else _CASE
    return None


def _intro_scene(units: Sequence[StoryUnit], place: str) -> dict[str, Any]:
    rows: dict[str, list[str]] = {"en": [], "fr": []}
    for unit in units:
        title = _unit_title(unit)
        kind = _kind(unit)
        rows["en"].append(f"{unit.unit_number} · {title['en']}{kind.label_en if kind else ''}")
        rows["fr"].append(f"{unit.unit_number} · {title['fr']}{kind.label_fr if kind else ''}")
    return {
        "place": place,
        "steps": [
            _line(
                "narrate",
                "This story is about you, {child}.",
                "Cette histoire parle de toi, {child}.",
                FRAME_OPENER,
            ),
            _line(
                "narrate",
                "Here is your path through this module, {child}.",
                "Voici ton chemin dans ce module, {child}.",
                FRAME_MODULE_INTRO,
            ),
            _concept(
                "module-overview",
                {"en": "In this module", "fr": "Dans ce module"},
                rows,
                FRAME_MODULE_OVERVIEW,
            ),
        ],
    }


def _checkpoint_scene(unit: StoryUnit, kind: _Kind, prefix: str, place: str) -> dict[str, Any]:
    number = unit.unit_number
    title = _unit_title(unit)
    return {
        "place": place,
        "steps": [
            _line(
                "narrate",
                f"Checkpoint, {{child}}: {kind.en} of unit {number}.",
                f"Étape, {{child}} : {kind.fr} de l'unité {number}.",
                FRAME_CHECKPOINT,
            ),
            _concept(
                f"{prefix}checkpoint",
                {"en": f"{kind.title_en} {number}", "fr": f"{kind.title_fr} {number}"},
                {"en": [title["en"]], "fr": [title["fr"]]},
                FRAME_CHECKPOINT,
            ),
            _line("say", kind.leave_en, kind.leave_fr, FRAME_CHECKPOINT, repair.MENTOR_ID),
        ],
    }


def _unavailable_scene(unit: StoryUnit, prefix: str, place: str) -> dict[str, Any]:
    number = unit.unit_number
    title = _unit_title(unit)
    return {
        "place": place,
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
                "Read it on its own page, {child}, then come back.",
                "Lis-la sur sa page, {child}, puis reviens.",
                FRAME_UNAVAILABLE,
                repair.MENTOR_ID,
            ),
        ],
    }


def _lesson_done(unit: StoryUnit) -> dict[str, Any]:
    return _line(
        "narrate",
        f"Well done, {{child}}: lesson {unit.unit_number} is done.",
        f"Bravo, {{child}} : la leçon {unit.unit_number} est terminée.",
        FRAME_LESSON_DONE,
    )


def _closing_scene(units: Sequence[StoryUnit], place: str) -> dict[str, Any]:
    roles = {unit.role for unit in units}
    steps = [
        _line(
            "narrate",
            "And that is the whole module, {child}: you have finished this story.",
            "Et voilà tout le module, {child} : tu as terminé cette histoire.",
            FRAME_FINISHED,
        )
    ]
    quizzes, cases = "quiz_checkpoint" in roles, "case_checkpoint" in roles
    if quizzes or cases:
        if quizzes and cases:
            en, fr = "Your quizzes and case studies", "Tes quiz et tes études de cas"
        elif quizzes:
            en, fr = "Your quizzes", "Tes quiz"
        else:
            en, fr = "Your case studies", "Tes études de cas"
        steps.append(
            _line(
                "narrate",
                f"{en} wait for you on their own pages, {{child}}.",
                f"{fr} t'attendent sur leurs pages, {{child}}.",
                FRAME_CHECKPOINT_REMINDER,
            )
        )
    steps.append(
        _line(
            "say",
            "Questions about this module? Ask me any time, {child}.",
            "Une question sur ce module ? Demande-moi quand tu veux, {child}.",
            FRAME_ASK_TUTOR,
            repair.TUTOR_ID,
        )
    )
    return {"place": place, "steps": steps}


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


def _lesson_scenes(doc: dict[str, Any], unit: StoryUnit, ns: _Namespace) -> list[dict[str, Any]]:
    """The lesson's scenes, flattened from its chapters, with the frame edits."""
    scenes: list[dict[str, Any]] = []
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            steps: list[dict[str, Any]] = []
            for step in scene["steps"]:
                frame = step.get("frame")
                if frame in _DROPPED_FRAMES:
                    continue
                if frame == repair.FRAME_FINISHED:
                    steps.append(_lesson_done(unit))
                    continue
                steps.append(ns.step(step))
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


def assemble_module_story(
    ctx: ModuleStoryContext, chapters: Sequence[ChapterSource]
) -> dict[str, Any]:
    """Join a module's chapters into one ``story-course/1`` week (contract C-2).

    Pure and deterministic; never mutates ``chapters``. A lesson whose
    document cannot be joined (see :func:`_unusable_reason`) becomes a "read
    it on its page" placeholder. The result is validated by the caller with
    :func:`validate_module_story`.
    """
    sources = list(chapters)
    language = ctx.language
    place = "classroom" if ctx.is_kids else "desk"
    prefixes = _prefixes(sources)

    ready: dict[int, _Ready] = {}
    statuses: list[ChapterStatus] = []
    for index, source in enumerate(sources):
        if source.unit.role != "lesson":
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

    for index, ids in _deduplicate({i: r.doc for i, r in ready.items()}).items():
        ready[index].dropped_points = _drop_questions(ready[index].doc, set(ids))
        logger.info(
            "Quiz questions already told by an earlier chapter left out",
            module_id=str(ctx.module_id),
            unit=sources[index].unit.unit_number,
            questions=ids,
        )

    module_chapters: list[dict[str, Any]] = []
    merged: dict[str, list[dict[str, Any]]] = {name: [] for name in _MERGED}
    typical_points = 0
    typical_plans: list[str] = []

    for index, source in enumerate(sources):
        unit, prefix = source.unit, prefixes[index]
        title = _unit_title(unit)
        scenes: list[dict[str, Any]] = []
        if index == 0:
            scenes.append(_intro_scene([s.unit for s in sources], place))
        max_points = 0
        if index in ready:
            chapter_doc = ready[index].doc
            ns = _Namespace(prefix, chapter_doc)
            scenes.extend(_lesson_scenes(chapter_doc, unit, ns))
            _merge_chapter(merged, chapter_doc, ns)
            typical = _typical(chapter_doc)
            typical_points += int(typical["points"])
            typical_plans.append(f"Lesson {unit.unit_number}: {typical['plan']}")
            max_points = _max_points(source.doc or {}, ready[index].dropped_points)
        elif (kind := _kind(unit)) is not None:
            scenes.append(_checkpoint_scene(unit, kind, prefix, place))
        else:
            scenes.append(_unavailable_scene(unit, prefix, place))
        if index == len(sources) - 1:
            scenes.append(_closing_scene([s.unit for s in sources], place))

        status = statuses[index]
        module_chapters.append(
            {
                "id": f"ch{index + 1}",
                "title": {
                    "en": f"{unit.unit_number} · {title['en']}",
                    "fr": f"{unit.unit_number} · {title['fr']}",
                },
                "scenes": scenes,
                "covers": {
                    "module_unit_id": str(unit.module_unit_id),
                    "unit_number": unit.unit_number,
                    "unit_type": unit.unit_type,
                    "role": unit.role,
                    "status": status,
                    "completes_unit": unit.role == "lesson" and status == "ready",
                    "max_points": max_points,
                },
            }
        )

    scene_number = 0
    for chapter in module_chapters:
        renumbered = []
        for scene in chapter["scenes"]:
            scene_number += 1
            rest = {key: value for key, value in scene.items() if key != "id"}
            renumbered.append({"id": f"s{scene_number}", **rest})
        chapter["scenes"] = renumbered
    repair.enforce_ask_spacing(module_chapters)

    module_title = _pair(
        ctx.module_title, f"Module {ctx.module_number}", f"Module {ctx.module_number}"
    )
    course_title = _pair(ctx.course_title, "", "")
    revision_rows = [
        [
            str(source.unit.module_unit_id),
            source.unit.role,
            _sha256(source.doc) if statuses[index] == "ready" else None,
        ]
        for index, source in enumerate(sources)
    ]
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
        "cast": repair.pinned_cast(ctx.is_kids, language),
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
        checkpoints=statuses.count("checkpoint"),
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
