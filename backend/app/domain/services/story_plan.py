"""The episode plan of a module story (#2680, story generator v4: "plan, then tell").

A module is ONE episode: each lesson is a chapter and the rally is the
climax. Before any chapter is written, one model call — the showrunner —
plans it: the premise (a want, stakes, a clock), the voices, the running
gag and catchphrases, the props that are planted and paid off, and per
chapter its when, opening, goal, obstacle, beats (which lesson IDEA cracks
which problem, its discovery and card title, the course questions it
takes), turn, ending, game and paper task; then the rally's steps.

:func:`validate_plan` lists what is wrong (one repair call is spent on
it); :func:`normalise_plan` then fixes the rest in code and records each fix
in ``gaps``. When no answer can be used twice, a plan is made in code
(:func:`default_plan`, ``model`` :data:`~story_repair.PLAN_DEFAULTED`),
retried once on the next run. A provider outage stores nothing.

The plan is cached per (module, language) in ``story_module_plans``
(migration 110) and is **sticky**: it is made again only when its inputs
change (:func:`plan_inputs`) — the plan version, the bible, the roster or a
quiz row make a full re-plan; a changed lesson fact sheet re-plans only that
chapter (incremental mode), its title, when, opening and ending kept, and
every other byte of the plan copied back, so the other chapters' digests do
not move. A lesson rewritten in prose with the same ideas changes nothing.

Digests a chapter records (``sira_chapter``): ``plan`` is
:func:`global_digest` (the plan without its chapters), ``beat`` is
:func:`beat_digest` (its entry and the content of its questions).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.story_course import ValidationIssue
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import FRIEND, HERO, StoryBible
from app.domain.services.story_props import fold, is_one_emoji, prop_slug

logger = structlog.get_logger(__name__)

#: A plan retried once after defaults, then kept until its inputs change.
DEFAULTED = repair.PLAN_DEFAULTED
DEFAULTED_KEPT = f"{DEFAULTED}-kept"

#: Answers read per plan: the first and one repair.
MAX_CALLS = 2

MAX_BEATS = 4
MAX_REFS_PER_BEAT = 2
MAX_REFS_PER_CHAPTER = 4
MAX_RALLY_REFS = 6
MIN_RALLY_REFS = 3
MAX_PROPS = 4
MAX_CATCHPHRASES = 2
TITLE_LIMIT = 40
DISCOVERY_LIMIT = 90
CARD_TITLE_LIMIT = 40
CATCHPHRASE_LIMIT = 50
FIELD_LIMIT = 300

_SYLLABUS_WORDS_RE = re.compile(r"\b(?:le[cç]ons?|lessons?|modules?|chapitres?|chapters?)\b", re.I)
_PREMISE_RE = re.compile(
    r"^(?:learn|discover|understand|apprendre|d[ée]couvrir|comprendre)\b|the mystery of", re.I
)
_TEXT_KEYS = (
    "logline",
    "want",
    "stakes",
    "clock",
    "hero_flaw",
    "running_gag",
)
_CHAPTER_TEXT = ("when", "opens_on", "goal", "obstacle", "turn", "ends_on", "paper_task")
_RALLY_TEXT = ("when", "opens_on", "final_obstacle", "resolution", "last_image", "paper_task")
#: What incremental mode rewrites in a changed chapter; everything else is kept.
REWRITTEN = ("goal", "obstacle", "beats", "turn")


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


def sha(value: Any) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mcq_key(mcq: repair.QuizMcq) -> str:
    """A course question's content key: its stem, options and correct index."""
    return sha([mcq.stem, list(mcq.options), mcq.correct_index])


@dataclass(frozen=True)
class PlanLesson:
    """A lesson chapter as the planner sees it."""

    unit_id: uuid.UUID
    unit_number: str
    title: dict[str, str]
    sheet: Any  # story_from_lesson.FactSheet
    lesson_row_id: uuid.UUID | None = None

    @property
    def ideas(self) -> int:
        return len(self.sheet.ideas)


@dataclass(frozen=True)
class PlanCandidate:
    """A course question the plan may give a chapter, numbered ``q1..``."""

    ref: str
    mcq: repair.QuizMcq
    quiz_unit: str
    #: The lesson units its quiz covers (a chapter may take it).
    covers: tuple[str, ...] = ()
    #: A lesson's own quiz: only that lesson's chapter may take it.
    only_unit: str | None = None

    @property
    def key(self) -> str:
        return mcq_key(self.mcq)

    def allowed(self, unit: str) -> bool:
        if self.only_unit:
            return unit == self.only_unit
        return unit in self.covers


@dataclass
class PlanRequest:
    """Everything a plan is made from; built by the module story's prep phase."""

    module_id: uuid.UUID
    language: str
    is_kids: bool
    module_number: int
    module_title: dict[str, str]
    course_title: dict[str, str]
    bible: StoryBible
    lessons: list[PlanLesson]
    candidates: list[PlanCandidate]
    #: ``[[quiz unit id, row id, content_revision, digest of its MCQ keys]]``.
    quiz_rows: list[list[Any]]
    roster_digest: str
    has_rally: bool
    blocklist: list[str] = field(default_factory=list)
    mission: dict[str, str] | None = None
    #: The previous module's plan: ``{"number", "title", "logline"}``.
    previous: dict[str, Any] | None = None
    #: The rows the plan is made from: ``{"lessons": {unit id: row id}, "quizzes": {...}}``.
    pins: dict[str, Any] = field(default_factory=dict)

    @property
    def units(self) -> list[str]:
        return [lesson.unit_number for lesson in self.lessons]

    def lesson(self, unit: str) -> PlanLesson | None:
        return next((lesson for lesson in self.lessons if lesson.unit_number == unit), None)

    def candidate(self, ref: str) -> PlanCandidate | None:
        return next((c for c in self.candidates if c.ref == ref), None)


def plan_inputs(request: PlanRequest) -> dict[str, Any]:
    """What the plan depends on: a global part and each lesson's fact sheet.

    A change of the global part (plan version, bible, roster, a quiz row)
    makes a full re-plan; a change of only some lessons' fact sheets
    re-plans only those chapters.
    """
    return {
        "global": sha(
            [
                repair.PLAN_VERSION,
                request.bible.digest,
                request.language,
                request.roster_digest,
                request.quiz_rows,
            ]
        ),
        "lessons": {str(lesson.unit_id): lesson.sheet.digest for lesson in request.lessons},
    }


def plan_digest(plan: dict[str, Any]) -> str:
    return sha(plan)


def global_digest(plan: dict[str, Any]) -> str:
    """The plan without its chapters: what every chapter is told within."""
    return sha({k: v for k, v in plan.items() if k != "chapters"})


def beat_digest(entry: dict[str, Any] | None, keys: list[str]) -> str:
    """A chapter's plan entry and the content keys of its questions."""
    return sha([entry or {}, keys])


def beat_digests(plan: dict[str, Any], request: PlanRequest) -> dict[str, str]:
    """Each lesson unit id's (and ``"rally"``'s) :func:`beat_digest` in ``plan``."""
    out: dict[str, str] = {}
    chapters = {c.get("unit"): c for c in plan.get("chapters") or []}
    for lesson in request.lessons:
        entry = chapters.get(lesson.unit_number)
        keys = [c.key for ref in entry_refs(entry) if (c := request.candidate(ref)) is not None]
        out[str(lesson.unit_id)] = beat_digest(entry, keys)
    rally = plan.get("rally")
    if isinstance(rally, dict):
        keys = [
            c.key
            for ref in entry_refs(rally, rally=True)
            if (c := request.candidate(ref)) is not None
        ]
        out["rally"] = beat_digest(rally, keys)
    return out


def entry_refs(entry: dict[str, Any] | None, *, rally: bool = False) -> list[str]:
    """The question refs of a chapter entry (its beats') or of the rally (its steps')."""
    out: list[str] = []
    if not isinstance(entry, dict):
        return out
    parts = entry.get("steps") if rally else entry.get("beats")
    for part in parts or []:
        for ref in (part or {}).get("questions") or []:
            if isinstance(ref, str) and ref not in out:
                out.append(ref)
    return out


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


@dataclass
class EpisodePlan:
    """A stored, normalised plan and its digests."""

    plan: dict[str, Any]
    inputs: str
    digest: str
    global_digest: str
    model: str | None
    gaps: list[str] = field(default_factory=list)
    pins: dict[str, Any] = field(default_factory=dict)
    #: Model calls this run spent on it.
    calls: int = 0

    @property
    def defaulted(self) -> bool:
        return bool(self.model) and str(self.model).startswith(DEFAULTED)

    def chapter(self, unit: str) -> dict[str, Any] | None:
        return next((c for c in self.plan.get("chapters") or [] if c.get("unit") == unit), None)

    @property
    def rally(self) -> dict[str, Any] | None:
        rally = self.plan.get("rally")
        return rally if isinstance(rally, dict) else None

    def beat_digest(self, unit: str | None, request: PlanRequest) -> str:
        """``unit`` ``None``: the rally's."""
        entry = self.rally if unit is None else self.chapter(unit)
        refs = entry_refs(entry, rally=unit is None)
        keys = [c.key for ref in refs if (c := request.candidate(ref)) is not None]
        return beat_digest(entry, keys)


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity="error", code=code, path=path, message=message)


def _str(value: Any, limit: int = FIELD_LIMIT) -> str:
    if value is None or isinstance(value, dict | list | bool):
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(" ,;:-") + "…"


def _pair(value: Any, limit: int) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    out = {lang: _str(value.get(lang), limit) for lang in ("en", "fr")}
    return out if out["en"] and out["fr"] else None


def _title_problem(title: dict[str, str] | None, unit_title: dict[str, str] | None) -> str | None:
    if title is None:
        return "no title in both languages"
    for lang in ("en", "fr"):
        text = title[lang]
        if len(text) > TITLE_LIMIT:
            return f"«{text}» is longer than {TITLE_LIMIT} characters"
        if any(c.isdigit() for c in text) or _SYLLABUS_WORDS_RE.search(text):
            return f"«{text}» reads like a syllabus heading"
        if unit_title and fold(text) in {fold(unit_title.get("en")), fold(unit_title.get("fr"))}:
            return f"«{text}» is the lesson heading"
    return None


def _ints(value: Any) -> list[int]:
    values = value if isinstance(value, list) else [value]
    out: list[int] = []
    for item in values:
        if isinstance(item, str) and item.strip().isdigit():
            item = int(item.strip())
        if isinstance(item, int) and not isinstance(item, bool) and item not in out:
            out.append(item)
    return out


def validate_plan(raw: Any, request: PlanRequest) -> list[ValidationIssue]:
    """Every rule of the plan, as issues for its one repair call (design §A)."""
    issues: list[ValidationIssue] = []
    if not isinstance(raw, dict):
        return [_issue("plan_unreadable", "", "the answer is not one JSON object")]
    bible = request.bible.content
    places = {p["id"] for p in bible.get("places") or []}
    cast_ids = {m["id"] for m in bible.get("cast") or []}
    chapters = [c for c in raw.get("chapters") or [] if isinstance(c, dict)]
    units = [str(c.get("unit") or "") for c in chapters]
    if units != request.units:
        issues.append(
            _issue(
                "plan_chapter_count",
                "chapters",
                f"chapters must be exactly {', '.join(request.units)}, in this order",
            )
        )
    rally = raw.get("rally")
    if request.has_rally != isinstance(rally, dict):
        issues.append(
            _issue(
                "plan_chapter_count",
                "rally",
                "the module has a quiz unit: plan the rally"
                if request.has_rally
                else "the module has no quiz unit: leave the rally out",
            )
        )
    used: dict[str, str] = {}
    games = 0
    for index, chapter in enumerate(chapters):
        path = f"chapters[{index}]"
        unit = str(chapter.get("unit") or "")
        lesson = request.lesson(unit)
        seen: dict[int, int] = {}
        beats = [b for b in chapter.get("beats") or [] if isinstance(b, dict)]
        if not 1 <= len(beats) <= MAX_BEATS:
            issues.append(_issue("plan_chapter_count", f"{path}.beats", "1 to 4 beats"))
        refs_here = 0
        for b_index, beat in enumerate(beats):
            b_path = f"{path}.beats[{b_index}]"
            for idea in _ints(beat.get("ideas")):
                if idea in seen:
                    issues.append(
                        _issue(
                            "plan_concept_twice",
                            f"{b_path}.ideas",
                            f"IDEA {idea} of lesson {unit} is in two beats",
                        )
                    )
                seen[idea] = b_index
            if beat.get("place") not in places:
                issues.append(
                    _issue("plan_unknown_place", f"{b_path}.place", "not a place id of the bible")
                )
            cast = beat.get("cast") if isinstance(beat.get("cast"), list) else []
            if any(c not in cast_ids for c in cast):
                issues.append(_issue("plan_unknown_cast", f"{b_path}.cast", "not a cast id"))
            if not 2 <= len(cast) <= 3 or HERO not in cast:
                issues.append(
                    _issue(
                        "plan_cast_size",
                        f"{b_path}.cast",
                        '2 or 3 cast ids, "hero" always among them',
                    )
                )
            refs = [r for r in beat.get("questions") or [] if isinstance(r, str)]
            if len(refs) > MAX_REFS_PER_BEAT:
                issues.append(
                    _issue("plan_too_many_questions", f"{b_path}.questions", "at most 2 per beat")
                )
            refs_here += len(refs)
            for ref in refs:
                candidate = request.candidate(ref)
                if candidate is None:
                    issues.append(
                        _issue("plan_ref_unknown", f"{b_path}.questions", f"{ref} is not listed")
                    )
                    continue
                if ref in used:
                    issues.append(
                        _issue(
                            "plan_ref_twice",
                            f"{b_path}.questions",
                            f"{ref} is already in chapter {used[ref]}",
                        )
                    )
                used.setdefault(ref, unit)
                if not candidate.allowed(unit):
                    issues.append(
                        _issue(
                            "plan_ref_wrong_lesson",
                            f"{b_path}.questions",
                            f"{ref} is not a question of lesson {unit}: give it to its own"
                            " chapter or the rally",
                        )
                    )
            for key, limit in (("discovery", DISCOVERY_LIMIT), ("card_title", CARD_TITLE_LIMIT)):
                value = beat.get(key)
                if _pair(value, 10_000) is None:
                    issues.append(
                        _issue("plan_missing_translation", f"{b_path}.{key}", 'needs "en" and "fr"')
                    )
                elif any(len(_str(value.get(lang), 10_000)) > limit for lang in ("en", "fr")):
                    issues.append(
                        _issue("plan_too_long", f"{b_path}.{key}", f"at most {limit} characters")
                    )
        if refs_here > MAX_REFS_PER_CHAPTER:
            issues.append(
                _issue("plan_too_many_questions", f"{path}.beats", "at most 4 per lesson chapter")
            )
        if lesson is not None:
            missing = [n for n in range(1, lesson.ideas + 1) if n not in seen]
            if missing:
                issues.append(
                    _issue(
                        "plan_concept_not_covered",
                        path,
                        f"IDEA {', '.join(map(str, missing))} of lesson {unit} is in no beat",
                    )
                )
        problem = _title_problem(
            _pair(chapter.get("title"), 10_000), lesson.title if lesson else None
        )
        if problem:
            issues.append(
                _issue("plan_title_syllabus", f"{path}.title", f"{problem}: give it a story title")
            )
        for key in ("goal", "obstacle", "turn", "ends_on"):
            if not _str(chapter.get(key)):
                issues.append(_issue("plan_hook_missing", f"{path}.{key}", "write it"))
        games += bool(_str(chapter.get("game")))
    if isinstance(rally, dict):
        games += bool(_str(rally.get("game")))
        refs = entry_refs(rally, rally=True)
        low = min(MIN_RALLY_REFS, len(request.candidates))
        high = min(MAX_RALLY_REFS, len(request.candidates))
        if not low <= len(refs) <= high:
            issues.append(
                _issue("plan_too_many_questions", "rally.steps", f"the rally takes {low} to {high}")
            )
        for ref in refs:
            if request.candidate(ref) is None:
                issues.append(_issue("plan_ref_unknown", "rally.steps", f"{ref} is not listed"))
        problem = _title_problem(_pair(rally.get("title"), 10_000), None)
        if problem:
            issues.append(_issue("plan_title_syllabus", "rally.title", problem))
    if games != 1:
        issues.append(_issue("plan_game_count", "game", f"exactly 1 game, not {games}"))
    problem = _title_problem(_pair(raw.get("episode_title"), 10_000), request.module_title)
    if problem:
        issues.append(_issue("plan_title_syllabus", "episode_title", problem))
    for index, phrase in enumerate(raw.get("catchphrases") or []):
        value = phrase if isinstance(phrase, dict) else {}
        if _pair(value, 10_000) is None:
            issues.append(
                _issue("plan_missing_translation", f"catchphrases[{index}]", 'needs "en" and "fr"')
            )
        elif any(len(_str(value.get(lang), 10_000)) > CATCHPHRASE_LIMIT for lang in ("en", "fr")):
            issues.append(
                _issue("plan_too_long", f"catchphrases[{index}]", "at most 50 characters")
            )
    for key in ("want", "logline"):
        if _PREMISE_RE.search(_str(raw.get(key))):
            issues.append(
                _issue(
                    "plan_premise_is_syllabus",
                    key,
                    "a want is something the characters want, never to learn or discover X",
                )
            )
    return issues


# --------------------------------------------------------------------------
# Normalisation: what the code fixes after the repair
# --------------------------------------------------------------------------


def _cast(value: Any, cast_ids: list[str]) -> list[str]:
    cast = [c for c in (value if isinstance(value, list) else []) if c in cast_ids]
    cast = list(dict.fromkeys(cast))
    if HERO not in cast:
        cast.insert(0, HERO)
    for filler in (FRIEND, *cast_ids):
        if len(cast) >= 2:
            break
        if filler not in cast:
            cast.append(filler)
    return cast[:3]


def _beat(raw: dict[str, Any], places: list[str], cast_ids: list[str]) -> dict[str, Any]:
    place = raw.get("place") if raw.get("place") in places else places[0]
    return {
        "ideas": _ints(raw.get("ideas")),
        "place": place,
        "cast": _cast(raw.get("cast"), cast_ids),
        "problem": _str(raw.get("problem")),
        "discovery": _pair(raw.get("discovery"), DISCOVERY_LIMIT) or {"en": "", "fr": ""},
        "card_title": _pair(raw.get("card_title"), CARD_TITLE_LIMIT) or {"en": "", "fr": ""},
        "questions": [r for r in raw.get("questions") or [] if isinstance(r, str)],
    }


def _default_beat(idea: int, places: list[str], lesson: PlanLesson | None) -> dict[str, Any]:
    text = _str(lesson.sheet.ideas[idea - 1], DISCOVERY_LIMIT) if lesson else ""
    return {
        "ideas": [idea],
        "place": places[(idea - 1) % len(places)],
        "cast": [HERO, FRIEND, "mentor"],
        "problem": "",
        "discovery": {"en": text, "fr": text},
        "card_title": {"en": f"Key idea {idea}", "fr": f"Idée clé {idea}"},
        "questions": [],
    }


def _chapter(
    raw: dict[str, Any] | None,
    lesson: PlanLesson,
    places: list[str],
    cast_ids: list[str],
    gaps: list[str],
) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    unit = lesson.unit_number
    beats = [_beat(b, places, cast_ids) for b in raw.get("beats") or [] if isinstance(b, dict)]
    if not beats:
        beats = [_default_beat(n, places, lesson) for n in range(1, lesson.ideas + 1)]
        if beats:
            gaps.append(f"{unit}: no beats; one per idea")
    if len(beats) > MAX_BEATS:
        last = beats[MAX_BEATS - 1]
        for extra in beats[MAX_BEATS:]:
            last["ideas"] += extra["ideas"]
            last["questions"] += extra["questions"]
        beats = beats[:MAX_BEATS]
        gaps.append(f"{unit}: extra beats merged into the last")
    seen: set[int] = set()
    for beat in beats:
        kept = []
        for idea in beat["ideas"]:
            if 1 <= idea <= lesson.ideas and idea not in seen:
                kept.append(idea)
                seen.add(idea)
        beat["ideas"] = kept
    orphans = [r for b in beats if not b["ideas"] for r in b["questions"]]
    beats = [b for b in beats if b["ideas"]] or beats[:1]
    if beats and orphans:
        beats[-1]["questions"] += orphans
    missing = [n for n in range(1, lesson.ideas + 1) if n not in seen]
    if missing and beats:
        beats[-1]["ideas"] += missing
        gaps.append(f"{unit}: IDEA {', '.join(map(str, missing))} added to the last beat")
    for beat in beats:
        first = beat["ideas"][0] if beat["ideas"] else 1
        if not beat["card_title"]["en"]:
            beat["card_title"] = {"en": f"Key idea {first}", "fr": f"Idée clé {first}"}
        if not beat["discovery"]["en"] and 1 <= first <= lesson.ideas:
            text = _str(lesson.sheet.ideas[first - 1], DISCOVERY_LIMIT)
            beat["discovery"] = {"en": text, "fr": text}
    title = _pair(raw.get("title"), 10_000)
    if _title_problem(title, lesson.title):
        card = beats[0]["card_title"] if beats else {"en": "", "fr": ""}
        title = {lang: _str(card[lang], TITLE_LIMIT) for lang in ("en", "fr")}
        if _title_problem(title, lesson.title):
            title = {lang: _str(lesson.title[lang], TITLE_LIMIT) for lang in ("en", "fr")}
        gaps.append(f"{unit}: syllabus title replaced")
    chapter: dict[str, Any] = {"unit": unit, "title": title}
    for key in _CHAPTER_TEXT:
        chapter[key] = _str(raw.get(key))
    chapter["beats"] = beats
    chapter["game"] = _str(raw.get("game")) or None
    if not chapter["paper_task"]:
        chapter["paper_task"] = "a short task on paper the story needs"
    return {key: chapter[key] for key in _CHAPTER_ORDER}


_CHAPTER_ORDER = (
    "unit",
    "title",
    "when",
    "opens_on",
    "goal",
    "obstacle",
    "beats",
    "turn",
    "ends_on",
    "game",
    "paper_task",
)


def _assign_refs(
    chapters: list[dict[str, Any]],
    request: PlanRequest,
    gaps: list[str],
    *,
    frozen: set[str] = frozenset(),
) -> None:
    """Every ref known, used once, by a lesson its quiz covers, within the caps.

    ``frozen`` chapters (incremental mode) keep theirs; their refs are taken.
    """
    used: set[str] = {
        ref for chapter in chapters if chapter["unit"] in frozen for ref in entry_refs(chapter)
    }
    for chapter in chapters:
        unit = chapter["unit"]
        if unit in frozen:
            continue
        total = 0
        for beat in chapter["beats"]:
            kept: list[str] = []
            for ref in beat["questions"]:
                candidate = request.candidate(ref)
                if candidate is None:
                    gaps.append(f"{unit}: unknown {ref} removed")
                    continue
                if ref in used:
                    gaps.append(f"{unit}: {ref} already used, removed")
                    continue
                if not candidate.allowed(unit):
                    gaps.append(f"{unit}: {ref} is not this lesson's, left for the rally")
                    continue
                if len(kept) >= MAX_REFS_PER_BEAT or total >= MAX_REFS_PER_CHAPTER:
                    gaps.append(f"{unit}: {ref} over the cap, left for the rally")
                    continue
                kept.append(ref)
                used.add(ref)
                total += 1
            beat["questions"] = kept


def _rally(
    raw: Any,
    chapters: list[dict[str, Any]],
    request: PlanRequest,
    places: list[str],
    gaps: list[str],
) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    units = request.units
    steps = []
    taken: list[str] = []
    for item in raw.get("steps") or []:
        if not isinstance(item, dict):
            continue
        refs = []
        for ref in item.get("questions") or []:
            if (
                isinstance(ref, str)
                and request.candidate(ref) is not None
                and ref not in taken
                and len(taken) < MAX_RALLY_REFS
            ):
                refs.append(ref)
                taken.append(ref)
        from_unit = str(item.get("from_unit") or "")
        steps.append(
            {
                "from_unit": from_unit if from_unit in units else units[-1],
                "uses": _str(item.get("uses")),
                "questions": refs,
            }
        )
    if not steps:
        steps = [{"from_unit": unit, "uses": "", "questions": []} for unit in units]
        gaps.append("rally: no steps; one per chapter")
    low = min(MIN_RALLY_REFS, len(request.candidates))
    if len(taken) < low:
        in_chapters = {ref for c in chapters for ref in entry_refs(c)}
        pool = [c.ref for c in request.candidates if c.ref not in in_chapters]
        pool += [c.ref for c in request.candidates if c.ref in in_chapters]
        for ref in pool:
            if len(taken) >= low:
                break
            if ref not in taken:
                steps[-1]["questions"].append(ref)
                taken.append(ref)
        gaps.append("rally: filled up to its questions")
    title = _pair(raw.get("title"), 10_000)
    if _title_problem(title, None):
        title = {"en": "The big day", "fr": "Le grand jour"}
        gaps.append("rally: title replaced")
    rally: dict[str, Any] = {"title": title}
    for key in _RALLY_TEXT:
        rally[key] = _str(raw.get(key))
    rally["steps"] = steps
    rally["payoffs"] = [p for p in raw.get("payoffs") or [] if isinstance(p, str)]
    rally["game"] = _str(raw.get("game")) or None
    if not rally["paper_task"]:
        rally["paper_task"] = "a short recap task on paper"
    return rally


def _props(raw: Any, units: list[str], gaps: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or len(out) >= MAX_PROPS:
            continue
        pid = prop_slug(item.get("id"))
        label = item.get("label") if isinstance(item.get("label"), dict) else item
        en, fr = _str(label.get("en"), 40), _str(label.get("fr"), 40)
        if not pid or not en or not fr or any(p["id"] == pid for p in out):
            gaps.append(f"prop {item.get('id')!r} left out")
            continue
        planted = str(item.get("planted") or "")
        prop: dict[str, Any] = {
            "id": pid,
            "en": en,
            "fr": fr,
            "query": _str(item.get("query"), 60) or en,
            "kind": "real" if str(item.get("kind")).lower() in ("real", "photo") else "sticker",
            "at": str(item.get("at") or "ground").lower(),
            "size": str(item.get("size") or "").lower() or None,
            "planted": planted if planted in units else units[0],
            "paid_off": str(item.get("paid_off") or "rally"),
        }
        emoji = _str(item.get("emoji"), 12)
        if is_one_emoji(emoji):
            prop["emoji"] = emoji
        out.append({k: v for k, v in prop.items() if v is not None})
    return out


def normalise_plan(
    raw: Any,
    request: PlanRequest,
    *,
    previous: dict[str, Any] | None = None,
    rewritten: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """The plan fixed in code (design: normalise_plan), and what was fixed.

    With ``previous`` and ``rewritten`` (incremental mode), every field but
    the ``goal``, ``obstacle``, ``beats`` and ``turn`` of the rewritten
    chapters is copied back from ``previous``, byte for byte, so the global
    digest and the other chapters' beat digests do not move.
    """
    raw = raw if isinstance(raw, dict) else {}
    gaps: list[str] = []
    bible = request.bible.content
    places = [p["id"] for p in bible.get("places") or []] or ["classroom"]
    cast_ids = [m["id"] for m in bible.get("cast") or []] or [HERO, FRIEND]
    by_unit = {str(c.get("unit")): c for c in raw.get("chapters") or [] if isinstance(c, dict)}
    chapters = [
        _chapter(by_unit.get(lesson.unit_number), lesson, places, cast_ids, gaps)
        for lesson in request.lessons
    ]
    if previous is not None and rewritten is not None:
        old = {c["unit"]: c for c in previous.get("chapters") or []}
        for index, chapter in enumerate(chapters):
            before = old.get(chapter["unit"])
            if before is None:
                continue
            if chapter["unit"] not in rewritten:
                chapters[index] = copy.deepcopy(before)
            else:
                fresh = copy.deepcopy(before)
                for key in REWRITTEN:
                    fresh[key] = chapter[key]
                chapters[index] = fresh
        frozen = {c["unit"] for c in chapters if c["unit"] not in rewritten}
        _assign_refs(chapters, request, gaps, frozen=frozen)
        plan = copy.deepcopy(previous)
        plan["chapters"] = chapters
        return plan, gaps

    _assign_refs(chapters, request, gaps)
    plan: dict[str, Any] = {
        "episode_title": _pair(raw.get("episode_title"), 10_000),
    }
    if _title_problem(plan["episode_title"], request.module_title):
        plan["episode_title"] = dict(chapters[0]["title"]) if chapters else None
        gaps.append("episode title replaced")
    for key in _TEXT_KEYS:
        plan[key] = _str(raw.get(key))
    if _PREMISE_RE.search(plan["want"]) or not plan["want"]:
        mission = request.mission or {}
        plan["want"] = plan["want"] or _str(mission.get("en"))
    voices = raw.get("voices") if isinstance(raw.get("voices"), dict) else {}
    plan["voices"] = {cid: _str(voices.get(cid)) for cid in cast_ids if _str(voices.get(cid))}
    phrases = []
    for item in raw.get("catchphrases") or []:
        if not isinstance(item, dict) or len(phrases) >= MAX_CATCHPHRASES:
            continue
        pair = _pair(item, CATCHPHRASE_LIMIT)
        who = item.get("who")
        if pair and who in cast_ids:
            phrases.append({"who": who, **pair})
    plan["catchphrases"] = phrases
    plan["props"] = _props(raw.get("props"), request.units, gaps)
    plan["chapters"] = chapters
    if request.has_rally:
        plan["rally"] = _rally(raw.get("rally"), chapters, request, places, gaps)
    _one_game(plan, request, gaps)
    return plan, gaps


def _one_game(plan: dict[str, Any], request: PlanRequest, gaps: list[str]) -> None:
    holders = [*plan["chapters"], *([plan["rally"]] if plan.get("rally") else [])]
    with_game = [h for h in holders if h.get("game")]
    for extra in with_game[1:]:
        extra["game"] = None
    if with_game[1:]:
        gaps.append("extra games removed")
    if not with_game and plan["chapters"]:
        richest = max(plan["chapters"], key=lambda c: sum(len(b["ideas"]) for b in c["beats"]))
        richest["game"] = "a quick catch game the characters play"
        gaps.append(f"{richest['unit']}: given the game")


def _code_made_chapters(
    request: PlanRequest, previous: dict[str, Any], units: set[str]
) -> tuple[dict[str, Any], list[str]]:
    """``previous`` with only ``units`` rebuilt in code (an incremental re-plan that failed).

    Every other entry, the global block included, is kept byte for byte, so no
    other chapter goes stale. A rebuilt chapter gets one beat per idea and keeps
    the questions it had, spread over its beats.
    """
    plan, gaps = normalise_plan({}, request, previous=previous, rewritten=units)
    old = {c.get("unit"): c for c in previous.get("chapters") or []}
    for chapter in plan["chapters"]:
        if chapter["unit"] not in units:
            continue
        refs = entry_refs(old.get(chapter["unit"]))
        for index, ref in enumerate(refs):
            beat = chapter["beats"][index % len(chapter["beats"])] if chapter["beats"] else None
            if beat is not None and len(beat["questions"]) < MAX_REFS_PER_BEAT:
                beat["questions"].append(ref)
    gaps.append(f"chapters {', '.join(sorted(units))} made in code")
    return plan, gaps


def default_plan(request: PlanRequest) -> dict[str, Any]:
    """A plan made in code when no answer could be used (``model`` DEFAULTED).

    One beat per idea, the lessons' titles, the bible's mission, no hooks,
    and the questions given round-robin to the chapters their quiz covers.
    """
    bible = request.bible.content
    places = [p["id"] for p in bible.get("places") or []] or ["classroom"]
    gaps: list[str] = []
    chapters = []
    for lesson in request.lessons:
        chapter = _chapter({}, lesson, places, [m["id"] for m in bible.get("cast") or []], gaps)
        chapter["title"] = {lang: _str(lesson.title[lang], 120) for lang in ("en", "fr")}
        chapters.append(chapter)
    counts = {c["unit"]: 0 for c in chapters}
    for candidate in request.candidates:
        for chapter in chapters:
            unit = chapter["unit"]
            if not candidate.allowed(unit) or counts[unit] >= MAX_REFS_PER_CHAPTER:
                continue
            beat = min(chapter["beats"], key=lambda b: len(b["questions"]))
            if len(beat["questions"]) < MAX_REFS_PER_BEAT:
                beat["questions"].append(candidate.ref)
                counts[unit] += 1
                break
    mission = request.mission or {}
    plan: dict[str, Any] = {
        "episode_title": dict(request.module_title),
        "logline": _str(mission.get("en")),
        "want": _str(mission.get("en")),
        "stakes": "",
        "clock": "",
        "hero_flaw": "",
        "running_gag": "",
        "voices": {},
        "catchphrases": [],
        "props": [],
        "chapters": chapters,
    }
    if request.has_rally:
        plan["rally"] = _rally({}, chapters, request, places, gaps)
    _one_game(plan, request, gaps)
    return plan


# --------------------------------------------------------------------------
# Storage and the service
# --------------------------------------------------------------------------


class PlanCallImpossible(RuntimeError):
    """The provider could not be called (an outage): nothing is stored."""


async def find_plan(
    session: AsyncSession, module_id: uuid.UUID, language: str, *, fresh: bool = False
) -> Any | None:
    from app.domain.models.story_module_plan import StoryModulePlan

    statement = select(StoryModulePlan).where(
        StoryModulePlan.module_id == module_id, StoryModulePlan.language == language
    )
    if fresh:
        statement = statement.execution_options(populate_existing=True)
    return (await session.execute(statement)).scalar_one_or_none()


async def find_plan_digests(
    session: AsyncSession, module_id: uuid.UUID, language: str
) -> tuple[str, str, dict[str, Any]] | None:
    """``(digest, global_digest, content)`` of the stored plan, for freshness.

    ``None`` — nothing is fresh — for a plan of another version, and for a
    plan made in code that still waits for its one retry (:data:`DEFAULTED`),
    as :func:`story_bible.find_bible_digest` does for the bible. A plan kept
    after its retry (:data:`DEFAULTED_KEPT`) is current.
    """
    from app.domain.models.story_module_plan import StoryModulePlan

    row = (
        await session.execute(
            select(
                StoryModulePlan.digest,
                StoryModulePlan.global_digest,
                StoryModulePlan.content,
                StoryModulePlan.model,
                StoryModulePlan.version,
            ).where(StoryModulePlan.module_id == module_id, StoryModulePlan.language == language)
        )
    ).first()
    if row is None or row.model == DEFAULTED or row.version != repair.PLAN_VERSION:
        return None
    return row.digest, row.global_digest, row.content


async def save_pack(
    session: AsyncSession, module_id: uuid.UUID, language: str, key: str, pack: dict[str, Any]
) -> None:
    """Keep a practice pack the moment it is made: ``content["packs"][key]``.

    ``key`` is a lesson unit id or ``"rally"``; ``pack`` is ``{"inputs",
    "spine"}``. One atomic JSONB update, so packs finishing together never
    overwrite each other. A deadline stop or a failed chapter then never pays
    for a pack again (its ``inputs`` tell whether it still fits).
    """
    from sqlalchemy import text as sql

    payload = json.dumps(pack, ensure_ascii=False)
    await session.execute(
        sql(
            "UPDATE story_module_plans SET content = jsonb_set("
            " content, '{packs}',"
            " COALESCE(content->'packs', '{}'::jsonb)"
            " || jsonb_build_object(CAST(:key AS text), CAST(:pack AS jsonb)))"
            " WHERE module_id = :module_id AND language = :language"
        ),
        {"key": key, "pack": payload, "module_id": module_id, "language": language},
    )
    await session.commit()


async def stored_packs(
    session: AsyncSession, module_id: uuid.UUID, language: str
) -> dict[str, Any]:
    """The packs kept with the plan (see :func:`save_pack`)."""
    from app.domain.models.story_module_plan import StoryModulePlan

    value = (
        await session.execute(
            select(StoryModulePlan.content["packs"]).where(
                StoryModulePlan.module_id == module_id, StoryModulePlan.language == language
            )
        )
    ).scalar_one_or_none()
    return value if isinstance(value, dict) else {}


def _lock_key(module_id: uuid.UUID, language: str) -> int:
    digest = hashlib.sha256(f"story-plan:{module_id}:{language}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _lock(session: AsyncSession, module_id: uuid.UUID, language: str) -> None:
    try:
        dialect = session.get_bind().dialect.name
    except Exception:  # pragma: no cover - a session without a bind
        dialect = ""
    if dialect == "postgresql":
        await session.execute(select(func.pg_advisory_xact_lock(_lock_key(module_id, language))))


def _from_row(row: Any) -> EpisodePlan:
    content = row.content if isinstance(row.content, dict) else {}
    return EpisodePlan(
        plan=content.get("plan") or {},
        inputs=row.inputs,
        digest=row.digest,
        global_digest=row.global_digest,
        model=row.model,
        gaps=list(content.get("gaps") or []),
        pins=dict(content.get("pins") or {}),
    )


class StoryPlanService:
    """Makes a module's episode plan (one call + one repair), stores it, reuses it."""

    def __init__(self, claude_service: Any) -> None:
        self.claude_service = claude_service

    async def get_or_create(
        self,
        session: AsyncSession,
        request: PlanRequest,
        *,
        system_prompt: str,
        force: bool = False,
    ) -> EpisodePlan:
        """The plan of ``(module, language)``: stored and current, else made now.

        Creation is serialised per (module, language) by an advisory lock;
        the row is read again after the lock (fresh from the database), so a
        plan another worker just made is reused, not paid for again.
        """
        parts = plan_inputs(request)
        inputs = sha(parts)
        row = await find_plan(session, request.module_id, request.language)
        plan = self._reusable(row, inputs, force)
        if plan is not None:
            return plan
        await _lock(session, request.module_id, request.language)
        row = await find_plan(session, request.module_id, request.language, fresh=True)
        plan = self._reusable(row, inputs, force)
        if plan is not None:
            return plan

        previous = _from_row(row) if row is not None else None
        content = row.content if row is not None and isinstance(row.content, dict) else {}
        #: Chapters an incremental re-plan could not rewrite: retried once.
        retry_units = {str(u) for u in content.get("retry_units") or []}
        changed: set[str] = set()
        if (
            previous is not None
            and not force
            and (not previous.defaulted or retry_units)
            and row.version == repair.PLAN_VERSION
        ):
            old = content.get("inputs") or {}
            if old.get("global") == parts["global"] and previous.plan.get("chapters"):
                lessons = old.get("lessons") or {}
                changed = {
                    lesson.unit_number
                    for lesson in request.lessons
                    if lessons.get(str(lesson.unit_id)) != parts["lessons"][str(lesson.unit_id)]
                } | (retry_units & set(request.units))
        incremental = bool(changed) and len(changed) < len(request.lessons)
        made, model, calls = await self._make(
            request,
            system_prompt=system_prompt,
            previous=previous.plan if incremental and previous else None,
            rewritten=changed if incremental else None,
        )
        retry: list[str] = []
        if model is None:
            # Unusable twice: made in code, retried once next time, then kept.
            model = DEFAULTED_KEPT if row is not None and row.model == DEFAULTED else DEFAULTED
            if incremental and previous is not None:
                # Never throw a good plan away: only the changed chapters are
                # made in code; every other entry stays byte for byte.
                made, gaps = _code_made_chapters(request, previous.plan, changed)
                retry = sorted(changed) if model == DEFAULTED else []
            else:
                made, gaps = default_plan(request), ["plan made in code"]
        else:
            made, gaps = made
        stored = await self._store(
            session, row, request, made, gaps, parts, model, retry_units=retry
        )
        stored.calls = calls
        logger.info(
            "Story episode plan made",
            module_id=str(request.module_id),
            language=request.language,
            incremental=sorted(changed) if incremental else None,
            model=model,
            calls=calls,
            gaps=len(gaps),
        )
        return stored

    @staticmethod
    def _reusable(row: Any, inputs: str, force: bool) -> EpisodePlan | None:
        if row is None or force or row.version != repair.PLAN_VERSION:
            return None
        if row.model == DEFAULTED:
            return None  # its one retry
        if row.inputs != inputs:
            return None
        return _from_row(row)

    async def _make(
        self,
        request: PlanRequest,
        *,
        system_prompt: str,
        previous: dict[str, Any] | None,
        rewritten: set[str] | None,
    ) -> tuple[Any, str | None, int]:
        """``((plan, gaps), model, calls)``; ``(None, None, calls)`` when no answer was usable.

        A provider outage (any error but an unreadable answer) raises
        :class:`PlanCallImpossible`: nothing is stored, the next run asks again.
        """
        from app.ai.prompts.story_plan import (
            build_incremental_block,
            build_plan_repair_message,
            build_plan_user_message,
        )

        message = build_plan_user_message(request)
        if previous is not None and rewritten:
            message += "\n\n" + build_incremental_block(previous, sorted(rewritten))
        calls = 0
        feedback: tuple[list[ValidationIssue], dict[str, Any] | None] | None = None
        best: Any = None
        for attempt in range(MAX_CALLS):
            prompt = (
                message
                if attempt == 0 or feedback is None
                else build_plan_repair_message(message, *feedback)
            )
            calls += 1
            try:
                raw = await self.claude_service.generate_structured_content(
                    system_prompt, prompt, "story", max_retries=0
                )
            except SoftTimeLimitExceeded:
                raise
            except ValueError as exc:
                logger.warning("Story plan answer unreadable", attempt=attempt + 1, error=str(exc))
                feedback = ([], None)
                continue
            except Exception as exc:
                if best is not None:
                    # The repair could not be made: keep the paid first answer.
                    logger.warning("Story plan repair failed; first answer kept", error=str(exc))
                    break
                raise PlanCallImpossible(f"{type(exc).__name__}: {exc}"[:300]) from exc
            if not isinstance(raw, dict) or raw.get("raw_response"):
                feedback = ([], None)
                continue
            raw.pop("__complete", None)
            if previous is not None and rewritten:
                best = raw
                break
            issues = validate_plan(raw, request)
            best = raw
            if not issues:
                break
            feedback = (issues, raw)
            logger.info("Story plan sent back for repair", codes=sorted({i.code for i in issues}))
        if best is None:
            return None, None, calls
        model = (
            _str(
                getattr(self.claude_service, "model", None)
                or getattr(self.claude_service, "_model", None),
                100,
            )
            or "unknown"
        )
        return normalise_plan(best, request, previous=previous, rewritten=rewritten), model, calls

    @staticmethod
    async def _store(
        session: AsyncSession,
        row: Any,
        request: PlanRequest,
        plan: dict[str, Any],
        gaps: list[str],
        parts: dict[str, Any],
        model: str,
        *,
        retry_units: list[str] | None = None,
    ) -> EpisodePlan:
        from app.domain.models.story_module_plan import StoryModulePlan

        before = row.content if row is not None and isinstance(row.content, dict) else {}
        content = {
            "plan": plan,
            "inputs": parts,
            "gaps": gaps,
            "pins": request.pins,
            # What each chapter must have been told from: freshness compares
            # these without reading the quizzes again.
            "beats": beat_digests(plan, request),
            # Packs already paid for: their inputs say whether they still fit.
            "packs": dict(before.get("packs") or {}),
        }
        if retry_units:
            content["retry_units"] = list(retry_units)
        values = {
            "version": repair.PLAN_VERSION,
            "inputs": sha(parts),
            "digest": plan_digest(plan),
            "global_digest": global_digest(plan),
            "content": content,
            "model": model,
        }
        for attempt in range(2):
            try:
                if row is not None:
                    for key, value in values.items():
                        setattr(row, key, value)
                else:
                    row = StoryModulePlan(
                        id=uuid.uuid4(),
                        module_id=request.module_id,
                        language=request.language,
                        **values,
                    )
                    session.add(row)
                await session.commit()
                break
            except IntegrityError:
                # Another worker stored the plan first: write over it.
                await session.rollback()
                if attempt:
                    raise
                row = await find_plan(session, request.module_id, request.language, fresh=True)
        return EpisodePlan(
            plan=plan,
            inputs=values["inputs"],
            digest=values["digest"],
            global_digest=values["global_digest"],
            model=model,
            gaps=gaps,
            pins=dict(request.pins),
        )
