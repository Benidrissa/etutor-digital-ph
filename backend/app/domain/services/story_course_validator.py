"""Validator for the ``story-course/1`` course file format (Appendix C).

A course file is only publishable when this reports **zero errors**. The nine
check groups below map one-to-one onto Appendix C:

1. structure, unique ids, every reference resolves, catalog membership
2. answers — every ``verify`` recomputed, traps distinct, choices and marks sane
3. languages and lengths
4. no answer leaks into prompts or hints (a prompt or hint naming the correct
   choice beside a distractor is a warning: it may be comparing them)
5. spread and coverage, and every marked-test mistake practised by a trap
6. mini-games — the rule recomputed for every target
7. photo checks — each exercise's own worked solution passes its checker
8. tutor
9. scores — the perfect run is computed, the typical run must be authored

The point of recomputing rather than trusting the file is that these course
files are authored by a language model from school lessons; an answer no engine
agrees with is exactly the failure mode this catches before a child sees it.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import structlog

from app.ai.algorithms import story_maths as maths
from app.api.v1.schemas.story_course import (
    ART_KEYS,
    CAST_ROLES,
    COPY_SHAPES,
    DRAWN_VISUALS,
    LENGTH_LIMITS,
    MAX_CLOSEUPS_PER_SCENE,
    MAX_PROPS_PER_LINE,
    MAX_PROPS_PER_MODULE,
    MAX_PROPS_PER_SCENE,
    MINIGAME_ENGINES,
    MOODS,
    PLACES,
    PROP_QUERY_LIMIT,
    VISUALS,
    Checks,
    StoryCourse,
    ValidationIssue,
    ValidationReport,
)
from app.domain.services import mcq_checks
from app.domain.services.story_props import is_one_emoji

logger = structlog.get_logger(__name__)

VALIDATOR_NAME = "story_course_validator v1"

#: Answers shorter than this are not leak-checked: a bare "7" or "12" shows up
#: in prompts for innocent reasons, and flagging those would train authors to
#: ignore the check.
_MIN_LEAK_LENGTH = 3

#: Lines shorter than this ("Yes!", "Merci !") may come back in any chapter.
MIN_REPEAT_LENGTH = 12

#: #2680: a generated chapter whose story lines are fewer than this share of
#: its steps gets a ``story_ratio_low`` warning.
STORY_RATIO_FLOOR = 0.55

_PROP_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def longest_ask_run(step_types: list[str]) -> int:
    """The most ``ask`` steps in a row in ``step_types``."""
    longest = run = 0
    for step_type in step_types:
        run = run + 1 if step_type == "ask" else 0
        longest = max(longest, run)
    return longest


#: Appendix A.4 step kinds that point at another collection by ``ref``.
_REF_TARGETS = {
    "ask": "questions",
    "game": "minigames",
    "photo": "exercises",
    "video": "videos",
}


def _norm(text: str) -> str:
    """Lowercase, strip spaces and fold the minus sign, for leak comparison."""
    return re.sub(r"\s+", "", str(text)).lower().replace(maths.MINUS, "-")


#: Honorifics a line may put before a speaker's name ("M. Kaboré dit : ...").
#: Shared by the validator and the generator's builder, which strips what this
#: flags.
HONORIFICS = (
    "mr",
    "mrs",
    "ms",
    "miss",
    "dr",
    "m",
    "mme",
    "mlle",
    "monsieur",
    "madame",
    "maître",
    "maitre",
    "teacher",
)
#: Verbs that, with a colon or an opening quote after them, label a line.
SPEECH_VERBS = (
    "says",
    "said",
    "asks",
    "asked",
    "replies",
    "answers",
    "explains",
    "shouts",
    "whispers",
    "dit",
    "demande",
    "répond",
    "repond",
    "explique",
    "crie",
    "chuchote",
)
_HONORIFIC = rf"(?:(?:{'|'.join(HONORIFICS)})\.?\s+)?"
_OPENING_QUOTES = "«\"“‘'"
#: Each opening quote and the quotes that close it.
_QUOTE_PAIRS = {"«": "»", '"': '"', "“": '”"', "‘": "’'", "'": "'’"}
#: ``Name:`` — or ``Name <speech verb>`` followed by a colon or an opening
#: quote, with or without a comma (``Margo says, "Look!"``). ``Kaboré dit
#: que…`` or ``Margo says the…`` is reported speech, not a label.
_SPEECH_TAG = rf"(?:\s*:|\s+(?:{'|'.join(SPEECH_VERBS)})\s*,?\s*(?::|(?=[{_OPENING_QUOTES}])))"
#: What may follow the closing quote of a labelled line: punctuation, or the
#: name of the one spoken to (``“Look at the clock”, {child}.``).
_AFTER_QUOTE_RE = re.compile(r"^[\s,]*(?:\{(?:child|friend)\})?[\s.!?…,;:]*$", re.IGNORECASE)


def _closing_quote(text: str) -> int | None:
    """Where the quote opening ``text`` closes, or ``None``."""
    closers = _QUOTE_PAIRS.get(text[:1])
    if not closers:
        return None
    index = max(text.rfind(c) for c in closers)
    return index if index > 0 else None


def speaker_label(text: Any, pattern: re.Pattern[str] | None) -> str | None:
    """The words of a line that opens with a speaker label, or ``None``.

    ``Kaboré: « Regarde ! »`` and ``Margo says, "Look!"`` are labels: the
    words are returned without the label, and without their quotes when the
    quoted words are the whole line (punctuation, or ``{child}`` after the
    closing quote, may follow it; quotes are only ever removed as a pair).
    ``Kaboré says 'prime' means…`` — a speech verb, then a quoted word in a
    longer sentence — is reported speech, not a label: ``None``.
    """
    if pattern is None or not isinstance(text, str):
        return None
    match = pattern.match(text)
    if not match:
        return None
    colon = match.group(0).rstrip().endswith(":")
    rest = text[match.end() :].strip()
    close = _closing_quote(rest)
    if close is not None and _AFTER_QUOTE_RE.match(rest[close + 1 :]):
        words = (rest[1:close].strip() + rest[close + 1 :]).strip()
        return words or None
    if not colon:
        # "Name says «x» to everyone": a verb and a quote in a longer sentence.
        return None
    return rest or None


def speaker_prefix_pattern(names: list[str]) -> re.Pattern[str] | None:
    """A line that opens with a speaker's name used as a label, or ``None``.

    ``M. Kaboré dit : « ... »``, ``Awa: ...`` or ``{friend} says: "..."`` — a
    ``say`` step already names its speaker in ``who``, and the stage shows the
    bubble on that character, so the line must be the words alone. The match
    ends after the colon, or before the opening quote. The generator's
    builder strips exactly what this matches.
    """
    alternatives = sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)
    if not alternatives:
        return None
    joined = "|".join(re.escape(n) for n in alternatives)
    return re.compile(
        rf"^[\s{_OPENING_QUOTES}(]*{_HONORIFIC}(?:{joined}){_SPEECH_TAG}", re.IGNORECASE
    )


_PLACEHOLDERS_RE = re.compile(r"\{(?:child|friend)\}", re.IGNORECASE)


def line_key(text: Any) -> str:
    """A story line folded for the repetition check.

    Case, spaces and edge punctuation are folded, and the ``{child}`` and
    ``{friend}`` placeholders left out, so "Bravo, {child} !" is as short as
    "Bravo !" and falls under :data:`MIN_REPEAT_LENGTH`.
    """
    value = _PLACEHOLDERS_RE.sub("", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip().casefold()
    value = re.sub(r"\s+([,.!?…;:])", r"\1", value)
    return value.strip(" .!?…,;:«»\"'“”‘’-–—")


def drawn_visual_problem(visual: str, params: Any) -> str | None:
    """Why the player cannot draw ``visual`` with ``params``, or ``None``.

    Only :data:`DRAWN_VISUALS` are drawn, and only with their params.
    """
    spec = DRAWN_VISUALS.get(visual)
    if spec is None:
        return f"{visual!r} is not a visual the player draws: use one of {', '.join(DRAWN_VISUALS)}"
    params = params if isinstance(params, dict) else {}
    for name, (required, description) in spec.items():
        if required and name not in params:
            return f"{visual} needs params.{name}: {description}"
    if visual == "hundred_square":
        highlight = str(params.get("highlight"))
        if highlight != "primes" and not re.fullmatch(r"multiples:[1-9]\d?", highlight):
            return 'params.highlight is "primes" or "multiples:N"'
        return None

    def whole(value: Any, low: int) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and low <= value <= 1000

    if visual in ("factor_tree", "division_ladder"):
        n = params.get("n")
        if not whole(n, 4):
            return f"params.n of {visual} is a whole number from 4 to 1000"
        split = params.get("first_split")
        bad_split = split is not None and (
            not isinstance(split, list)
            or len(split) != 2
            or not all(whole(x, 2) for x in split)
            or split[0] * split[1] != n
        )
        if visual == "factor_tree" and bad_split:
            return "params.first_split is [a, b] with a × b = n"
        return None
    if not (whole(params.get("a"), 2) and whole(params.get("b"), 2)):
        return "params.a and params.b of venn_primes are whole numbers from 2 to 1000"
    return None


class StoryCourseValidator:
    """Runs the Appendix C checks over one parsed course file."""

    def __init__(self, course: StoryCourse, *, generated: bool = False) -> None:
        self.course = course
        #: A story the generator made (#2674): the screenplay rules that are only
        #: warnings for a hand-authored week (mood, speaker label, a line told
        #: again, a visual the player cannot draw) are errors.
        self.generated = generated
        self.errors: list[ValidationIssue] = []
        self.warnings: list[ValidationIssue] = []
        self._target, self._home = course.language_codes
        self._objective_ids = {o.id for o in course.objectives}
        self._misconception_ids = {m.id for m in course.misconceptions}
        self._cast_ids = {c.id for c in course.cast}
        self._question_ids = {q.id for q in course.questions}
        self._exercise_ids = {e.id for e in course.exercises}
        self._minigame_ids = {g.id for g in course.minigames}
        self._video_ids = {v.id for v in course.videos}
        self._declared_art = {a.name for a in course.art_requests}
        self._declared_engines = {e.engine for e in course.engine_requests}
        self._place_ids = {p.id for p in course.places}
        names = [c.name for c in course.cast] + [c.id for c in course.cast]
        names += [c.default_name for c in course.cast if c.default_name]
        self._prefix = speaker_prefix_pattern(names)
        #: #2681: the declared props, and which were pointed at or shown close up.
        self._props = {p.id: p for p in course.props}
        self._pointed: set[str] = set()
        self._shown: set[str] = set()
        self._scenes_without_visual = 0

    # -- issue helpers ------------------------------------------------------

    def _error(self, code: str, path: str, message: str) -> None:
        self.errors.append(ValidationIssue(severity="error", code=code, path=path, message=message))

    def _strict(self, code: str, path: str, message: str) -> None:
        """An error in a generated story, a warning in a hand-authored week."""
        if self.generated:
            self._error(code, path, message)
        else:
            self._warn(code, path, message)

    def _warn(self, code: str, path: str, message: str) -> None:
        self.warnings.append(
            ValidationIssue(severity="warning", code=code, path=path, message=message)
        )

    # -- entry point --------------------------------------------------------

    def run(self) -> ValidationReport:
        self._check_structure()
        self._check_answers()
        self._check_languages_and_lengths()
        self._check_no_leaks()
        self._check_spread_and_coverage()
        self._check_minigames()
        self._check_photo_checks()
        self._check_tutor()
        checks = self._check_scores()
        checks.props = self._props_checks()
        if self.generated and self._told_from_plan():
            self._check_story_shape()

        checks.errors = len(self.errors)
        checks.warnings = len(self.warnings)
        report = ValidationReport(
            ok=not self.errors,
            errors=self.errors,
            warnings=self.warnings,
            checks=checks,
        )
        logger.info(
            "Story course validated",
            course_id=self.course.id,
            week=self.course.week,
            errors=len(self.errors),
            warnings=len(self.warnings),
        )
        return report

    # -- C.1 structure ------------------------------------------------------

    def _check_structure(self) -> None:
        course = self.course

        if not course.objectives:
            self._error("missing_objectives", "objectives", "A week needs at least one objective")
        # A generated chapter (#2680) has the episode's one game only if the
        # plan gives it to it. A module story told from a plan has its game in
        # one chapter: while that chapter is not ready, the story still plays
        # (a warning, not an error).
        chapter_only = self.generated and getattr(course, "sira_chapter", None) is not None
        if not course.minigames and not chapter_only:
            if self.generated and self._told_from_plan():
                self._warn(
                    "missing_minigame",
                    "minigames",
                    "the chapter with the episode's game is not ready yet",
                )
            else:
                self._error("missing_minigame", "minigames", "A.3 requires at least one mini-game")
        self._check_props()
        if not course.chapters:
            self._error("missing_chapters", "chapters", "A week needs at least one chapter")

        self._check_unique_ids()

        for index, member in enumerate(course.cast):
            if member.art not in ART_KEYS and member.art not in self._declared_art:
                self._error(
                    "unknown_art",
                    f"cast[{index}].art",
                    f"{member.art!r} is not in the art catalog and has no art_requests entry",
                )
            if member.role is not None and member.role not in CAST_ROLES:
                self._error(
                    "unknown_role",
                    f"cast[{index}].role",
                    f"{member.role!r} is not one of {', '.join(CAST_ROLES)}",
                )
            variant_ids = [v.id for v in member.variants]
            if len(variant_ids) != len(set(variant_ids)):
                self._error("duplicate_id", f"cast[{index}].variants", "a variant id is used twice")
        for index, place in enumerate(course.places):
            self._text(place.title, f"places[{index}].title", "title")

        for chapter in course.chapters:
            for scene in chapter.scenes:
                self._check_scene(chapter.id, scene)

        for question in course.questions:
            self._check_objective_ref(question.objective, f"questions[{question.id}].objective")
        for exercise in course.exercises:
            self._check_objective_ref(exercise.objective, f"exercises[{exercise.id}].objective")
        for game in course.minigames:
            self._check_objective_ref(game.objective, f"minigames[{game.id}].objective")
            if game.engine not in MINIGAME_ENGINES and game.engine not in self._declared_engines:
                self._error(
                    "unknown_engine",
                    f"minigames[{game.id}].engine",
                    f"{game.engine!r} is not a v1 engine and has no engine_requests entry",
                )

        self._check_misconception_refs()

    def _check_unique_ids(self) -> None:
        groups = {
            "objectives": [o.id for o in self.course.objectives],
            "misconceptions": [m.id for m in self.course.misconceptions],
            "cast": [c.id for c in self.course.cast],
            "questions": [q.id for q in self.course.questions],
            "exercises": [e.id for e in self.course.exercises],
            "minigames": [g.id for g in self.course.minigames],
            "videos": [v.id for v in self.course.videos],
            "chapters": [c.id for c in self.course.chapters],
            "places": [p.id for p in self.course.places],
        }
        scene_ids: list[str] = []
        for chapter in self.course.chapters:
            scene_ids.extend(scene.id for scene in chapter.scenes)
        groups["scenes"] = scene_ids

        for name, ids in groups.items():
            seen: set[str] = set()
            for an_id in ids:
                if an_id in seen:
                    self._error("duplicate_id", name, f"id {an_id!r} is used more than once")
                seen.add(an_id)

    # -- props (#2681) ------------------------------------------------------

    def _check_props(self) -> None:
        """Each declared prop: a unique id, both labels, a query, its figure."""
        seen: set[str] = set()
        for index, prop in enumerate(self.course.props):
            path = f"props[{index}]"
            if not _PROP_ID_RE.match(prop.id):
                self._error("prop_id_invalid", f"{path}.id", f"{prop.id!r} is not snake_case")
            if prop.id in seen:
                self._error("prop_id_duplicate", f"{path}.id", f"{prop.id!r} is declared twice")
            seen.add(prop.id)
            for lang in (self._target, self._home):
                if not str((prop.label or {}).get(lang) or "").strip():
                    self._error(
                        "prop_label_missing", f"{path}.label.{lang}", "the label has no text"
                    )
            if not prop.query.strip() or len(prop.query) > PROP_QUERY_LIMIT:
                self._error(
                    "prop_query_invalid",
                    f"{path}.query",
                    f"a query is 1 to {PROP_QUERY_LIMIT} characters",
                )
            if prop.kind == "figure" and (prop.figure is None or not prop.figure.source_image_id):
                self._error(
                    "prop_figure_missing", f"{path}.figure", "a figure prop names its figure"
                )
            if prop.emoji is not None and not is_one_emoji(prop.emoji):
                self._warn("prop_emoji_invalid", f"{path}.emoji", "not one emoji")
        if len(self.course.props) > MAX_PROPS_PER_MODULE:
            self._warn(
                "module_props_too_many",
                "props",
                f"{len(self.course.props)} props: at most {MAX_PROPS_PER_MODULE}",
            )

    def _check_scene_props(self, scene: Any, path: str) -> None:
        listed = list(scene.props or [])
        for pid in listed:
            if pid not in self._props:
                self._error("unknown_prop", f"{path}.props", f"{pid!r} is not a declared prop")
        if len(listed) > MAX_PROPS_PER_SCENE:
            self._error(
                "scene_props_too_many",
                f"{path}.props",
                f"{len(listed)} props: at most {MAX_PROPS_PER_SCENE} in a scene",
            )
        cast = set(scene.cast or [])
        for pid in listed:
            prop = self._props.get(pid)
            if prop is not None and prop.at == "held" and prop.holder not in cast:
                self._strict(
                    "holder_not_in_cast",
                    f"{path}.props",
                    f"{pid!r} is held by {prop.holder!r}, who is not on stage",
                )
        closeups = 0
        lines = 0
        visual = bool(listed)
        for index, step in enumerate(scene.steps):
            step_path = f"{path}.steps[{index}]"
            refs = step.props or []
            if refs and step.type not in ("say", "narrate", "concept"):
                self._error(
                    "step_props_wrong_type",
                    f"{step_path}.props",
                    "only a say, narrate or concept step points at props",
                )
            if len(refs) > MAX_PROPS_PER_LINE:
                self._error(
                    "step_props_too_many",
                    f"{step_path}.props",
                    f"a line points at {MAX_PROPS_PER_LINE} props at most",
                )
            for pid in refs:
                if pid not in self._props:
                    self._error("unknown_prop", f"{step_path}.props", f"{pid!r} is not declared")
                elif pid not in listed:
                    self._strict(
                        "prop_not_in_scene",
                        f"{step_path}.props",
                        f"{pid!r} is not among the scene's props",
                    )
                else:
                    self._pointed.add(pid)
            if step.type in ("say", "narrate"):
                lines += 1
            if step.type == "show":
                visual = True
            if step.type == "show" and step.visual == "prop":
                closeups += 1
                pid = (step.params or {}).get("prop")
                if not pid:
                    self._error(
                        "missing_prop", f"{step_path}.params", 'a close-up needs "params.prop"'
                    )
                elif pid not in self._props:
                    self._error("unknown_prop", f"{step_path}.params.prop", f"{pid!r} is unknown")
                else:
                    self._shown.add(pid)
                    if self._props[pid].kind == "sticker":
                        self._strict(
                            "closeup_of_sticker",
                            step_path,
                            f"{pid!r} is a sticker: it is not shown close up",
                        )
        if closeups > MAX_CLOSEUPS_PER_SCENE:
            self._strict(
                "too_many_closeups_in_scene",
                path,
                f"{closeups} close-ups: at most {MAX_CLOSEUPS_PER_SCENE} in a scene",
            )
        if lines >= 3 and not visual:
            self._scenes_without_visual += 1
            if self._props:
                self._warn(
                    "scene_without_visual",
                    path,
                    "3 or more lines and nothing to see: no prop and no picture",
                )

    def _props_checks(self) -> dict[str, Any] | None:
        """``checks.props``: what the story shows, for staging review."""
        if not self._props:
            return None
        for pid, prop in self._props.items():
            if prop.educational and pid in self._pointed and pid not in self._shown:
                self._warn(
                    "educational_prop_not_shown",
                    "props",
                    f"{pid!r} is named but never shown close up",
                )
        lines = with_props = 0
        for chapter in self.course.chapters:
            for scene in chapter.scenes:
                for step in scene.steps:
                    if step.type in ("say", "narrate") and not getattr(step, "frame", None):
                        lines += 1
                        with_props += bool(step.props)
        props = list(self._props.values())
        return {
            "declared": len(props),
            "educational": sum(1 for p in props if p.educational),
            "stickers": sum(1 for p in props if p.kind == "sticker"),
            "figures": sum(1 for p in props if p.kind == "figure"),
            "lines": lines,
            "lines_with_props": with_props,
            "coverage": round(with_props / lines, 2) if lines else 0.0,
            "closeups": len(self._shown),
            "scenes_without_visual": self._scenes_without_visual,
        }

    def _check_scene(self, chapter_id: str, scene: Any) -> None:
        path = f"chapters[{chapter_id}].scenes[{scene.id}]"
        self._check_scene_props(scene, path)
        if (
            scene.place not in PLACES
            and scene.place not in self._place_ids
            and scene.place not in self._declared_art
        ):
            self._error(
                "unknown_place",
                f"{path}.place",
                f"{scene.place!r} is not one of the story's places, not in the place catalog"
                " and has no art_requests entry",
            )
        self._check_objective_ref(scene.objective, f"{path}.objective")
        for member in scene.cast or []:
            if member not in self._cast_ids:
                self._error("unknown_scene_cast", f"{path}.cast", f"{member!r} is not in the cast")

        for index, step in enumerate(scene.steps):
            step_path = f"{path}.steps[{index}]"
            if step.type == "say":
                if not step.who:
                    self._error("missing_speaker", step_path, "a 'say' step needs 'who'")
                elif step.who not in self._cast_ids:
                    self._error(
                        "unknown_speaker", f"{step_path}.who", f"{step.who!r} is not in the cast"
                    )
                self._check_speaker_prefix(step, step_path)
            elif step.type == "show":
                if not step.visual:
                    self._error("missing_visual", step_path, "a 'show' step needs 'visual'")
                elif step.visual not in VISUALS and step.visual not in self._declared_art:
                    self._error(
                        "unknown_visual",
                        f"{step_path}.visual",
                        f"{step.visual!r} is not in the visual catalog and has no "
                        "art_requests entry",
                    )
                elif step.visual not in ("image", "prop") and (
                    problem := drawn_visual_problem(step.visual, step.params)
                ):
                    self._strict("visual_not_drawn", f"{step_path}.visual", problem)
            elif step.type in _REF_TARGETS:
                self._check_step_ref(step, step_path)

            if step.mood and step.mood not in MOODS:
                self._strict(
                    "unknown_mood",
                    f"{step_path}.mood",
                    f"{step.mood!r} is not a mood: use one of {', '.join(MOODS)}",
                )

    def _check_speaker_prefix(self, step: Any, step_path: str) -> None:
        """A ``say`` line is the words alone: never "Awa: ..." or "M. Kaboré dit : ..."."""
        if self._prefix is None:
            return
        for lang in ("en", "fr"):
            value = getattr(step, lang, None)
            if speaker_label(value, self._prefix) is not None:
                self._strict(
                    "speaker_prefix",
                    f"{step_path}.{lang}",
                    "the line starts with the speaker's name: 'who' already says who"
                    " speaks, so write only the words they say",
                )

    def _check_step_ref(self, step: Any, step_path: str) -> None:
        collection = _REF_TARGETS[step.type]
        known = {
            "questions": self._question_ids,
            "exercises": self._exercise_ids,
            "minigames": self._minigame_ids,
            "videos": self._video_ids,
        }[collection]
        if not step.ref:
            self._error("missing_ref", step_path, f"a {step.type!r} step needs 'ref'")
        elif step.ref not in known:
            self._error(
                "dangling_ref",
                f"{step_path}.ref",
                f"{step.ref!r} is not in {collection}",
            )

    def _check_objective_ref(self, objective: str | None, path: str) -> None:
        if objective and objective not in self._objective_ids:
            self._error("dangling_objective", path, f"{objective!r} is not in objectives")

    def _check_misconception_refs(self) -> None:
        for row in self.course.calibration:
            if row.misconception and row.misconception not in self._misconception_ids:
                self._error(
                    "dangling_misconception",
                    "calibration",
                    f"{row.misconception!r} is not in misconceptions",
                )
        for question in self.course.questions:
            for index, trap in enumerate(question.traps):
                self._check_one_misconception(
                    trap.misconception, f"questions[{question.id}].traps[{index}].misconception"
                )
            for index, choice in enumerate(question.choices):
                if choice.misconception:
                    self._check_one_misconception(
                        choice.misconception,
                        f"questions[{question.id}].choices[{index}].misconception",
                    )
        for exercise in self.course.exercises:
            for index, trap in enumerate(exercise.traps):
                self._check_one_misconception(
                    trap.misconception, f"exercises[{exercise.id}].traps[{index}].misconception"
                )
        for game in self.course.minigames:
            for target, misconception in game.traps.items():
                self._check_one_misconception(
                    misconception, f"minigames[{game.id}].traps[{target}]"
                )

    def _check_one_misconception(self, misconception: str | None, path: str) -> None:
        if misconception and misconception not in self._misconception_ids:
            self._error("dangling_misconception", path, f"{misconception!r} is not declared")

    # -- C.2 answers --------------------------------------------------------

    def _check_answers(self) -> None:
        for question in self.course.questions:
            path = f"questions[{question.id}]"
            self._verify_answer(question.verify, question.answer, path, question.type)
            self._check_traps_differ(question, path)
            self._check_choices(question, path)
            if (
                question.type == "index_form"
                and question.require_index
                and question.answer
                and not maths.is_index_form(str(question.answer))
            ):
                self._error(
                    "answer_not_index_form",
                    f"{path}.answer",
                    f"require_index is set but {question.answer!r} repeats a prime "
                    "instead of using powers",
                )
            for p_index, part in enumerate(question.parts):
                self._verify_answer(
                    part.verify, part.answer, f"{path}.parts[{p_index}]", part.type or ""
                )

        for exercise in self.course.exercises:
            path = f"exercises[{exercise.id}]"
            self._verify_answer(exercise.verify, exercise.answer, path, "")
            self._check_traps_differ(exercise, path)
            if exercise.parts:
                part_marks = sum(p.marks or 0 for p in exercise.parts)
                if part_marks != exercise.marks:
                    self._error(
                        "marks_mismatch",
                        f"{path}.parts",
                        f"part marks add up to {part_marks}, but marks is {exercise.marks}",
                    )
                for p_index, part in enumerate(exercise.parts):
                    self._verify_answer(
                        part.verify, part.answer, f"{path}.parts[{p_index}]", part.type or ""
                    )
            for row in exercise.mark_scheme:
                if not row.en or not row.fr:
                    self._error(
                        "incomplete_mark_scheme",
                        f"{path}.mark_scheme",
                        f"{row.code} needs text in both languages",
                    )

    def _verify_answer(self, verify: Any, answer: Any, path: str, kind: str) -> None:
        """Recompute ``verify`` and insist it equals the authored answer."""
        if verify is None:
            if kind and kind != "choice" and kind != "exact_text" and answer is not None:
                self._warn(
                    "no_verify",
                    path,
                    "no verify block: this answer is not recomputed by the engine",
                )
            return
        if answer is None:
            self._error("missing_answer", path, "verify is set but there is no answer")
            return
        try:
            result = maths.call(verify.fn, verify.args, verify.kwargs)
        except maths.EngineError as exc:
            if getattr(exc, "code", "") == "not_in_engine":
                if verify.fn in self._declared_engines:
                    self._warn(
                        "engine_requested",
                        f"{path}.verify.fn",
                        f"{verify.fn!r} is not in maths library v1 but is declared in "
                        "engine_requests; the answer was not recomputed",
                    )
                else:
                    self._error(
                        "unknown_engine_fn",
                        f"{path}.verify.fn",
                        f"{verify.fn!r} is not in maths library v1 and has no "
                        "engine_requests entry",
                    )
            else:
                self._error("verify_failed", f"{path}.verify", str(exc))
            return

        if not maths.answers_match(answer, result, fn=verify.fn):
            self._error(
                "answer_mismatch",
                f"{path}.answer",
                f"{verify.fn}(...) is {result.text!r}, but answer is {answer!r}",
            )

    def _check_traps_differ(self, item: Any, path: str) -> None:
        """A trap equal to the answer would mark a right answer wrong."""
        if item.answer is None:
            return
        answer_norm = _norm(item.answer)
        for index, trap in enumerate(item.traps):
            if trap.answer is None:
                self._error(
                    "trap_without_answer", f"{path}.traps[{index}]", "a trap needs an answer"
                )
                continue
            if _norm(trap.answer) == answer_norm:
                self._error(
                    "trap_equals_answer",
                    f"{path}.traps[{index}].answer",
                    f"trap {trap.answer!r} is the correct answer",
                )
            if not trap.misconception:
                self._error(
                    "trap_without_misconception",
                    f"{path}.traps[{index}]",
                    "every trap needs a misconception",
                )
            if not trap.hint:
                self._warn(
                    "trap_without_hint",
                    f"{path}.traps[{index}]",
                    "a trap should carry a hint aimed at that mistake",
                )

    def _check_choices(self, question: Any, path: str) -> None:
        if question.type != "choice":
            if question.choices:
                self._warn(
                    "unexpected_choices", f"{path}.choices", "choices only apply to type 'choice'"
                )
            return
        if not question.choices:
            self._error("missing_choices", f"{path}.choices", "a 'choice' question needs choices")
            return
        correct = [c for c in question.choices if c.id == str(question.answer)]
        if len(correct) != 1:
            self._error(
                "choice_answer_unresolved",
                f"{path}.answer",
                f"answer {question.answer!r} must name exactly one choice id "
                f"(matched {len(correct)})",
            )
        for index, choice in enumerate(question.choices):
            if choice.id == str(question.answer):
                continue
            if not choice.misconception:
                self._error(
                    "distractor_without_misconception",
                    f"{path}.choices[{index}]",
                    f"wrong option {choice.id!r} needs a misconception — wrong choices are "
                    "traps, never random distractors",
                )

        # The shared MCQ rules, judged on the options' text. _assert_no_leak
        # cannot catch a choice leak: for a choice question its needle is the
        # choice id ("c"), not what the learner reads. Errors are adopted, and
        # so is the warning for a prompt or hint that names the correct choice
        # beside a distractor (a comparison or a leak: a person decides). The
        # short-answer "not leak-checked" note is informational and stays out,
        # and the misconception rule is already enforced above per choice.
        for view in mcq_checks.from_story_choice_question(question):
            for issue in (
                *mcq_checks.check_answer_leak(view),
                *mcq_checks.check_duplicate_options(view),
            ):
                if issue.severity == "error":
                    self._error(issue.code, issue.path, issue.message)
                elif issue.code == mcq_checks.ANSWER_LEAK_AMBIGUOUS:
                    self._warn(issue.code, issue.path, issue.message)

    # -- C.3 languages and lengths -----------------------------------------

    def _check_languages_and_lengths(self) -> None:
        course = self.course

        self._text(course.title, "title", "title")
        for chapter in course.chapters:
            self._text(chapter.title, f"chapters[{chapter.id}].title", "title")
            for scene in chapter.scenes:
                for index, step in enumerate(scene.steps):
                    self._check_step_text(chapter.id, scene.id, index, step)

        for entry_index, entry in enumerate(course.glossary):
            if entry.note:
                self._text(entry.note, f"glossary[{entry_index}].note", "note")

        for question in course.questions:
            path = f"questions[{question.id}]"
            self._text(question.prompt, f"{path}.prompt", "prompt")
            for index, hint in enumerate(question.hints):
                self._text(hint, f"{path}.hints[{index}]", "hint")
            if question.explanation:
                self._text(question.explanation, f"{path}.explanation", "explanation")
            for index, trap in enumerate(question.traps):
                if trap.hint:
                    self._text(trap.hint, f"{path}.traps[{index}].hint", "hint")

        for exercise in course.exercises:
            path = f"exercises[{exercise.id}]"
            self._text(exercise.prompt, f"{path}.prompt", "prompt")
            if exercise.explanation:
                self._text(exercise.explanation, f"{path}.explanation", "explanation")
            self._check_parallel_lists(exercise.working, f"{path}.working", "working lines")

        for game in course.minigames:
            path = f"minigames[{game.id}]"
            self._text(game.title, f"{path}.title", "title")
            self._text(game.instruction, f"{path}.instruction", "instruction")
            if game.hint_after_wrong:
                self._text(game.hint_after_wrong, f"{path}.hint_after_wrong", "hint")

    def _check_step_text(self, chapter_id: str, scene_id: str, index: int, step: Any) -> None:
        path = f"chapters[{chapter_id}].scenes[{scene_id}].steps[{index}]"
        if step.type in ("narrate", "say"):
            self._flat_text(step, path, "story")
        elif step.type == "concept":
            if step.title:
                self._text(step.title, f"{path}.title", "title")
            # Language-keyed like a text object: ``en`` rows are English and
            # ``fr`` rows French, whichever of them is the target language.
            rows = {
                lang: value
                for lang, value in (("en", step.en), ("fr", step.fr))
                if isinstance(value, list)
            }
            self._check_parallel_lists(rows, path, "concept rows")
        elif step.type == "show" and step.caption:
            self._text(step.caption, f"{path}.caption", "caption")

    def _flat_text(self, step: Any, path: str, kind: str) -> None:
        """``narrate``/``say`` carry flat ``en``/``fr`` rather than a text object.

        The two fields are language-keyed, exactly like a text object: ``en`` is
        the English line and ``fr`` the French one, regardless of which is the
        target language. Reading them positionally (``en`` = target) would show
        a French-target story's lines in the wrong language and apply each
        language's length limit to the other's text.
        """
        as_object = {}
        if isinstance(step.en, str):
            as_object["en"] = step.en
        if isinstance(step.fr, str):
            as_object["fr"] = step.fr
        self._text(as_object, path, kind)

    def _text(self, obj: Any, path: str, kind: str) -> None:
        """Both declared languages present, each within its A.2 length limit."""
        if not isinstance(obj, dict):
            self._error(
                "not_a_text_object", path, f"expected a text object, got {type(obj).__name__}"
            )
            return
        for lang in (self._target, self._home):
            value = obj.get(lang)
            if value is None or not str(value).strip():
                self._error(
                    "missing_language",
                    f"{path}.{lang}",
                    f"every text object needs {lang!r}",
                )
                continue
            limit = LENGTH_LIMITS.get(kind, {}).get(lang)
            if limit and len(str(value)) > limit:
                self._error(
                    "too_long",
                    f"{path}.{lang}",
                    f"{len(str(value))} characters, limit for {kind} in {lang} is {limit}",
                )

    def _check_parallel_lists(self, rows: Any, path: str, label: str) -> None:
        """Concept rows and working lines must line up across languages (C.3)."""
        if not isinstance(rows, dict) or not rows:
            return
        present = {lang: rows.get(lang) for lang in (self._target, self._home)}
        missing = [lang for lang, value in present.items() if not value]
        if missing and any(present.values()):
            for lang in missing:
                self._error("missing_language", f"{path}.{lang}", f"{label} missing for {lang!r}")
            return
        lengths = {lang: len(value) for lang, value in present.items() if value}
        if len(set(lengths.values())) > 1:
            self._error(
                "unequal_rows",
                path,
                f"{label} differ in count across languages: {lengths}",
            )

    # -- C.4 no leaks -------------------------------------------------------

    def _check_no_leaks(self) -> None:
        for question in self.course.questions:
            path = f"questions[{question.id}]"
            texts = [(f"{path}.prompt", question.prompt)]
            texts += [(f"{path}.hints[{i}]", h) for i, h in enumerate(question.hints)]
            texts += [
                (f"{path}.traps[{i}].hint", t.hint) for i, t in enumerate(question.traps) if t.hint
            ]
            self._assert_no_leak(question.answer, texts)
        for exercise in self.course.exercises:
            path = f"exercises[{exercise.id}]"
            texts = [(f"{path}.prompt", exercise.prompt)]
            texts += [
                (f"{path}.traps[{i}].hint", t.hint) for i, t in enumerate(exercise.traps) if t.hint
            ]
            self._assert_no_leak(exercise.answer, texts)

    def _assert_no_leak(self, answer: Any, texts: list[tuple[str, Any]]) -> None:
        if answer is None:
            return
        needle = _norm(answer)
        if len(needle) < _MIN_LEAK_LENGTH:
            return
        for path, text in texts:
            if not isinstance(text, dict):
                continue
            for lang, value in text.items():
                if needle in _norm(value):
                    self._error(
                        "answer_leak",
                        f"{path}.{lang}",
                        f"the answer {answer!r} appears in the text a learner reads "
                        "before answering",
                    )

    # -- C.5 spread and coverage -------------------------------------------

    def _check_spread_and_coverage(self) -> None:
        asked: list[str] = []
        runs: list[list[str]] = []
        for chapter in self.course.chapters:
            # A chapter ends on its own screen, so a run of questions never
            # carries over into the next chapter.
            flat_types: list[str] = []
            for scene in chapter.scenes:
                for step in scene.steps:
                    flat_types.append(step.type)
                    if step.type == "ask" and step.ref:
                        asked.append(step.ref)
            runs.append(flat_types)

        for question in self.course.questions:
            if question.id not in asked:
                self._error(
                    "question_never_asked",
                    f"questions[{question.id}]",
                    "every question must be asked by an 'ask' step in the story",
                )

        if any(longest_ask_run(flat_types) > 3 for flat_types in runs):
            self._error(
                "too_many_questions_in_a_row",
                "chapters",
                "more than 3 questions in a row — put a concept or visual between them",
            )
        self._check_lines_not_repeated()

        questions_per_objective: dict[str, int] = {}
        for question in self.course.questions:
            if question.objective:
                questions_per_objective[question.objective] = (
                    questions_per_objective.get(question.objective, 0) + 1
                )
        exercises_per_objective: dict[str, int] = {}
        for exercise in self.course.exercises:
            if exercise.objective:
                exercises_per_objective[exercise.objective] = (
                    exercises_per_objective.get(exercise.objective, 0) + 1
                )
        for objective in self.course.objectives:
            if questions_per_objective.get(objective.id, 0) < 2:
                self._warn(
                    "thin_question_coverage",
                    f"objectives[{objective.id}]",
                    "fewer than 2 questions for this objective",
                )
            if exercises_per_objective.get(objective.id, 0) < 1:
                self._warn(
                    "no_exercise_for_objective",
                    f"objectives[{objective.id}]",
                    "no paper exercise for this objective",
                )

        self._check_test_mistakes_practised()

    def _check_lines_not_repeated(self) -> None:
        """No story line told again in another chapter.

        A line every chapter opens or closes with ("Well done, {child}: the
        lesson is over") reads as boilerplate, not story. Steps marked with
        ``frame`` are the application's own placeholder lines, and steps marked
        ``retold`` were kept on purpose by the module assembler (dropping them
        would have joined two runs of questions): both are exempt.
        """
        first_seen: dict[tuple[str, str], str] = {}
        for chapter in self.course.chapters:
            for scene in chapter.scenes:
                for index, step in enumerate(scene.steps):
                    if (
                        step.type not in ("narrate", "say")
                        or getattr(step, "frame", None)
                        or getattr(step, "retold", None)
                        or getattr(step, "refrain", None)
                    ):
                        continue
                    for lang in ("en", "fr"):
                        value = getattr(step, lang, None)
                        key = line_key(value) if isinstance(value, str) else ""
                        if len(key) < MIN_REPEAT_LENGTH:
                            continue
                        seen_in = first_seen.setdefault((lang, key), chapter.id)
                        if seen_in != chapter.id:
                            self._strict(
                                "repeated_line",
                                f"chapters[{chapter.id}].scenes[{scene.id}].steps[{index}].{lang}",
                                f"this line was already told in chapter {seen_in}: every"
                                " line of the story is written for its own moment",
                            )

    def _told_from_plan(self) -> bool:
        """A module story, or a chapter told from an episode plan (#2680)."""
        marker = getattr(self.course, "sira_chapter", None)
        if isinstance(marker, dict):
            return bool(marker.get("plan"))
        return isinstance(getattr(self.course, "module_story", None), dict)

    def _check_story_shape(self) -> None:
        """#2680, generated stories: warnings that never block publishing.

        A lesson chapter that ends on a question, the game or a paper task
        (``chapter_ends_on_task``), and a chapter whose story lines are under
        :data:`STORY_RATIO_FLOOR` of its steps (``story_ratio_low``). The
        application's placeholder chapters (``frame``) are not judged.
        """
        for chapter in self.course.chapters:
            steps = [step for scene in chapter.scenes for step in scene.steps]
            if not steps or any(getattr(step, "frame", None) for step in steps):
                continue
            covers = getattr(chapter, "covers", None)
            rally = isinstance(covers, dict) and covers.get("rally")
            if not rally and steps[-1].type in ("ask", "game", "photo"):
                self._warn(
                    "chapter_ends_on_task",
                    f"chapters[{chapter.id}]",
                    f"the chapter ends on a {steps[-1].type}: end on a story line",
                )
            counted = [
                s
                for s in steps
                if not (s.type == "show" and s.visual == "prop")
                and not str(s.id or "").startswith("situation-")
            ]
            lines = sum(1 for s in counted if s.type in ("say", "narrate"))
            if counted and lines / len(counted) < STORY_RATIO_FLOOR:
                self._warn(
                    "story_ratio_low",
                    f"chapters[{chapter.id}]",
                    f"{lines} story lines in {len(counted)} steps: the story is thin",
                )

    def _check_test_mistakes_practised(self) -> None:
        """Every mistake from the marked test must be practised by a trap."""
        practised: set[str] = set()
        for question in self.course.questions:
            practised.update(t.misconception for t in question.traps if t.misconception)
            practised.update(c.misconception for c in question.choices if c.misconception)
        for exercise in self.course.exercises:
            practised.update(t.misconception for t in exercise.traps if t.misconception)
        for game in self.course.minigames:
            practised.update(game.traps.values())

        from_test = {m.id for m in self.course.misconceptions if m.from_test}
        from_test.update(r.misconception for r in self.course.calibration if r.misconception)
        for misconception in sorted(from_test - practised):
            self._error(
                "test_mistake_not_practised",
                f"misconceptions[{misconception}]",
                "this mistake came from the marked test but no trap practises it",
            )

    # -- C.6 mini-games -----------------------------------------------------

    def _check_minigames(self) -> None:
        for game in self.course.minigames:
            path = f"minigames[{game.id}]"
            if not game.rounds:
                self._error("no_rounds", f"{path}.rounds", "a mini-game needs at least one round")
                continue
            for index, round_data in enumerate(game.rounds):
                self._check_round(game, index, round_data, f"{path}.rounds[{index}]")

    def _check_round(self, game: Any, index: int, round_data: Any, path: str) -> None:
        rule_fn = (game.rule or {}).get("fn")

        # pop/catch style: a list of targets filtered by the rule.
        if isinstance(round_data, list):
            if not rule_fn:
                self._warn("no_rule", path, "a list round needs a rule to decide the targets")
                return
            correct, wrong = [], []
            for target in round_data:
                try:
                    result = maths.call(rule_fn, [target])
                except maths.EngineError as exc:
                    self._error("rule_failed", path, f"{rule_fn}({target!r}) failed: {exc}")
                    return
                (correct if result.value else wrong).append(target)
            if not correct:
                self._error(
                    "round_without_target",
                    path,
                    f"no value in this round satisfies {rule_fn} — nothing to tap",
                )
            for target in wrong:
                if str(target) not in game.traps:
                    self._warn(
                        "wrong_target_without_misconception",
                        f"{path}",
                        f"{target!r} is a wrong target with no entry in traps",
                    )
            return

        if not isinstance(round_data, dict):
            self._error("bad_round", path, "a round must be a list of targets or an object")
            return

        # catch style: explicit items with a `correct` flag.
        items = round_data.get("items")
        if isinstance(items, list):
            if not any(item.get("correct") for item in items if isinstance(item, dict)):
                self._error("round_without_target", path, "no item in this round is correct")
            for item_index, item in enumerate(items):
                if isinstance(item, dict) and not item.get("correct") and not item.get("trap"):
                    self._warn(
                        "wrong_target_without_misconception",
                        f"{path}.items[{item_index}]",
                        "a wrong item should name the trap it represents",
                    )
            return

        # which_first style: the engine solves the expression itself.
        if "expr" in round_data:
            try:
                maths.calc(str(round_data["expr"]))
            except maths.EngineError as exc:
                self._error("bad_expression", f"{path}.expr", str(exc))
            return

        # hop style: a number line walk.
        if "start" in round_data and ("moves" in round_data or "target" in round_data):
            return

        self._warn("unchecked_round", path, "the validator has no rule for this round shape")

    # -- C.7 photo checks ---------------------------------------------------

    def _check_photo_checks(self) -> None:
        """Each exercise's own worked solution must pass its step checker.

        The canonical working is derived from the declared number, so this
        catches a ``photo_check`` whose ``n`` disagrees with the exercise's own
        answer — the case where a child's correct photo would be marked wrong.
        """
        for exercise in self.course.exercises:
            check = exercise.photo_check
            if check is None:
                continue
            path = f"exercises[{exercise.id}].photo_check"
            if (
                check.copy_shape not in COPY_SHAPES
                and check.copy_shape not in self._declared_engines
            ):
                self._error(
                    "unknown_copy_shape",
                    f"{path}.copy",
                    f"{check.copy_shape!r} is not an A.6 copy shape and has no engine_requests entry",
                )
                continue

            fn = check.check.get("fn")
            if not fn:
                self._warn("no_check_fn", path, "no check function: nothing recomputes her working")
                continue
            if fn not in maths.STEP_CHECKERS:
                if fn not in self._declared_engines:
                    self._error(
                        "unknown_check_fn",
                        f"{path}.check.fn",
                        f"{fn!r} is not a step checker and has no engine_requests entry",
                    )
                continue

            number = check.check.get("n")
            if number is None:
                self._warn("no_check_number", f"{path}.check", "no 'n' to rebuild the working from")
                continue
            self._self_test_photo_check(exercise, fn, number, path)

    def _self_test_photo_check(self, exercise: Any, fn: str, number: Any, path: str) -> None:
        try:
            value = int(number)
            primes = maths.prime_factors(value)
        except (TypeError, ValueError, maths.EngineError) as exc:
            self._error("bad_check_number", f"{path}.check.n", f"{number!r}: {exc}")
            return

        if fn == "ladder_steps":
            rows, current = [], value
            for prime in primes:
                rows.append({"p": prime, "n": current})
                current //= prime
            result = maths.ladder_steps(rows, exercise.answer, n=value)
        elif fn == "tree_splits":
            splits, current = [], value
            for prime in primes[:-1]:
                splits.append({"n": current, "into": [prime, current // prime]})
                current //= prime
            result = maths.tree_splits(splits, exercise.answer, n=value) if splits else None
            if result is None:
                self._warn("tree_too_small", path, f"{value} has too few factors to build a tree")
                return
        else:
            # calc_lines has no canonical working to rebuild; the answer check
            # in C.2 already covers it.
            return

        if not result.ok:
            self._error(
                "photo_check_self_test_failed",
                path,
                f"the correct working for {value} does not pass {fn}: "
                f"{result.error_code} ({result.detail})",
            )

    # -- C.8 tutor ----------------------------------------------------------

    def _check_tutor(self) -> None:
        tutor = self.course.tutor
        if tutor is None:
            self._error("missing_tutor", "tutor", "A.3 requires a tutor block")
            return

        persona = next((c for c in self.course.cast if c.id == tutor.persona), None)
        if persona is None:
            self._error(
                "tutor_persona_not_in_cast",
                "tutor.persona",
                f"{tutor.persona!r} is not in the cast",
            )
        elif persona.kind != "ai_tutor":
            self._error(
                "tutor_persona_wrong_kind",
                "tutor.persona",
                f"{persona.id!r} is kind {persona.kind!r}, expected 'ai_tutor'",
            )

        self._text(tutor.intro, "tutor.intro", "intro")
        # The child must be told she is talking to a machine, in whichever
        # language she is reading, so every language must say it.
        declares_ai = (tutor.intro or {}) and all(
            re.search(r"\b(ai|ia|robot|intelligence artificielle)\b", str(value), re.IGNORECASE)
            for value in (tutor.intro or {}).values()
        )
        if not declares_ai:
            self._error(
                "tutor_intro_hides_ai",
                "tutor.intro",
                "the intro must say the tutor is an AI",
            )

        if tutor.off_topic:
            self._text(tutor.off_topic, "tutor.off_topic", "reply")
        else:
            self._error("missing_off_topic", "tutor.off_topic", "A.10 requires an off_topic reply")
        if tutor.worry:
            self._text(tutor.worry, "tutor.worry", "reply")
        else:
            self._error("missing_worry", "tutor.worry", "A.10 requires a worry reply")

        if not tutor.never:
            self._warn("empty_never", "tutor.never", "no 'never' rules: the tutor is unconstrained")
        for objective in tutor.scope.this_week:
            if objective not in self._objective_ids:
                self._error(
                    "dangling_objective",
                    "tutor.scope.this_week",
                    f"{objective!r} is not in objectives",
                )

    # -- C.9 scores ---------------------------------------------------------

    def _check_scores(self) -> Checks:
        """Compute the perfect run and require the typical run to be authored.

        ``max_points`` is the sum of three transparent parts:

        * questions — ``points`` when set, else ``rewards.first_try``
        * exercises — the paper marks
        * mini-games — one ``points.per_correct`` per correct target in every
          round

        Streak bonuses are deliberately excluded: they depend on the order the
        child happens to answer in, which the file does not fix.
        """
        rewards = self.course.rewards or {}
        first_try = int(rewards.get("first_try", 2) or 2)

        question_points = sum(
            q.points if q.points is not None else first_try for q in self.course.questions
        )
        paper_marks = sum(e.marks or 0 for e in self.course.exercises)

        minigame_points = 0
        minigame_rounds = 0
        for game in self.course.minigames:
            # An explicit None check: ``x or 1`` would turn an authored
            # ``per_correct: 0`` (a game that awards nothing) back into 1, so
            # max_points would count points the player can never earn.
            raw_per_correct = (game.points or {}).get("per_correct")
            per_correct = 1 if raw_per_correct is None else int(raw_per_correct)
            rule_fn = (game.rule or {}).get("fn")
            for round_data in game.rounds:
                minigame_rounds += 1
                if isinstance(round_data, list) and rule_fn:
                    for target in round_data:
                        try:
                            if maths.call(rule_fn, [target]).value:
                                minigame_points += per_correct
                        except maths.EngineError:
                            continue
                elif isinstance(round_data, dict) and isinstance(round_data.get("items"), list):
                    minigame_points += per_correct * sum(
                        1
                        for item in round_data["items"]
                        if isinstance(item, dict) and item.get("correct")
                    )
                else:
                    minigame_points += per_correct

        max_points = question_points + paper_marks + minigame_points

        authored = self.course.checks
        if authored.max_points and authored.max_points != max_points:
            self._warn(
                "max_points_mismatch",
                "checks.max_points",
                f"the file says {authored.max_points}, the validator computes {max_points}",
            )
        if not authored.predicted_typical:
            self._error(
                "missing_predicted_typical",
                "checks.predicted_typical",
                "C.9 needs the typical-mistakes run worked out by hand",
            )

        return Checks(
            validator=VALIDATOR_NAME,
            date=date.today().isoformat(),
            questions=len(self.course.questions),
            exercises=len(self.course.exercises),
            paper_marks=paper_marks,
            minigame_rounds=minigame_rounds,
            max_points=max_points,
            predicted_typical=authored.predicted_typical,
        )


def validate_story_course(course: StoryCourse, *, generated: bool = False) -> ValidationReport:
    """Run every Appendix C check over a parsed course file.

    ``generated``: a story the generator made, held to the screenplay rules
    (mood, speaker label, a line told again, a visual the player draws) as
    errors; a hand-authored week gets them as warnings.
    """
    return StoryCourseValidator(course, generated=generated).run()
