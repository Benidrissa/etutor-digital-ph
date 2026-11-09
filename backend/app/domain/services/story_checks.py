"""The story checks of a chapter told from the episode plan (#2680).

The owner's verdict on the #2674 stories was "it does not sound like a
story, just an audio version of the course". These checks measure what that
means on a built chapter, deterministically:

* **codes** (:data:`story_repair.STORY_CODES`), recorded with
  :func:`story_repair.builder_issue`: errors while the story's repair budget
  lasts, warnings after it — a question with no lead-in or no reaction, a
  lead-in that gives the answer away, too little story between teaching
  moments, a chapter that ends on a task, Margo introducing herself, a line
  about the app, a name from the lesson's own examples;
* **lints**, warnings only, never worth a repair call: a line that lectures,
  a card that repeats the dialogue or gives an answer away, a mentor who
  does all the talking, a quiet hero, a textbook card title, a chapter that
  does not open where the last one stopped, a planted prop never paid off;
* **story_quality**, the numbers behind them, written into the chapter's
  ``checks`` and printed in the CI transcript.

Only a chapter with a plan entry (:attr:`LessonStoryContext.is_v4`) is
checked; the paths are those of the model's JSON (``scenes[i].steps[j]``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.api.v1.schemas.story_course import ValidationIssue
from app.domain.services.story_props import fold

#: What a teaching moment is made of; a prop's close-up is part of the story.
TEACHING = ("concept", "show", "game", "photo", "ask")
LINE_TYPES = ("say", "narrate")

#: Below this share of story lines, a chapter is too thin (the rally: 0.5).
MIN_STORY_RATIO = 0.6
MIN_RALLY_STORY_RATIO = 0.5
#: Story lines between two teaching moments.
MIN_GAP = 3
#: Story lines of a lesson chapter: at least max(14, 6 × beats); a rally 12.
MIN_LINES, LINES_PER_BEAT, MIN_RALLY_LINES = 14, 6, 12

_META_RE = re.compile(
    r"\b(?:le[cç]ons?|chapitres?|modules?|quiz|lessons?|chapters?)\b"
    r"|dans ce module|ce que tu vas apprendre|points? cl[ée]s"
    r"|^bravo,?\s*\{child\}|cette histoire|this story",
    re.IGNORECASE,
)
#: Margo saying what she is. "AI"/"IA" only as a word of its own: "j'ai" is not one.
_MARGO_INTRO_RE = re.compile(
    r"(?<![\w'’])(?:ai|ia|robot|intelligence artificielle)\b|\bi'?m margo\b|\bi am margo\b"
    r"|\bje suis margo\b",
    re.IGNORECASE,
)
_LECTURE_RE = re.compile(
    r"is defined as|is called|there are \d+ (?:kinds|types)|scientists|remember that"
    r"|in biology|se d[ée]finit|il existe \d+|les scientifiques|les biologistes|retiens"
    r"|en biologie",
    re.IGNORECASE,
)
_TEXTBOOK_TITLE_RE = re.compile(
    r"^(?:signe|niveau|concept|id[ée]e cl[ée]|key idea|level|sign)\s*\d", re.IGNORECASE
)
_WORD_RE = re.compile(r"[a-z0-9]{4,}")


def content_words(text: Any) -> set[str]:
    """Folded words of 4+ letters, placeholders left out."""
    value = fold(re.sub(r"\{(?:child|friend)\}", " ", str(text or "")))
    return set(_WORD_RE.findall(value))


@dataclass
class QuestionFacts:
    """What the checks need to know about one built question."""

    derived: bool
    answers: list[str]
    idea: int | None = None


@dataclass
class _Flat:
    scene: int
    index: int
    step: dict[str, Any]

    @property
    def type(self) -> str:
        return str(self.step.get("type"))

    @property
    def path(self) -> str:
        return str(self.step.get("_src") or f"scenes[{self.scene}]")


@dataclass
class StoryReport:
    lints: list[ValidationIssue] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)


def _is_situation(step: dict[str, Any]) -> bool:
    return step.get("type") == "concept" and str(step.get("id", "")).startswith("situation-")


def _is_closeup(step: dict[str, Any]) -> bool:
    return step.get("type") == "show" and step.get("visual") == "prop"


def _teaching(step: dict[str, Any]) -> bool:
    return step.get("type") in TEACHING and not _is_closeup(step)


def _flat(scenes: list[dict[str, Any]]) -> list[_Flat]:
    return [
        _Flat(s_index, index, step)
        for s_index, scene in enumerate(scenes)
        for index, step in enumerate(scene["steps"])
    ]


def moments(flat: list[_Flat]) -> list[tuple[int, int]]:
    """The teaching moments, as ``(first, last)`` positions in ``flat``.

    A concept card and the questions after it in its scene are one moment
    ("a card with its questions"), whatever lines set those questions up; so
    is a run of questions on their own. A figure, the game and a paper task
    are moments of their own. A code-inserted situation card belongs to the
    question it shows.
    """
    out: list[list[int]] = []
    owner: tuple[int, str] | None = None  # (scene, kind) of the open moment
    for position, item in enumerate(flat):
        step = item.step
        if not _teaching(step):
            continue
        if _is_situation(step) or item.type == "ask":
            if owner is not None and owner[0] == item.scene and owner[1] in ("card", "ask"):
                out[-1][1] = position
            else:
                out.append([position, position])
                owner = (item.scene, "ask")
            continue
        out.append([position, position])
        owner = (item.scene, "card" if item.type == "concept" else item.type)
    return [(a, b) for a, b in out]


def _runs(flat: list[_Flat]) -> list[tuple[int, int]]:
    """Runs of asks (with their situation cards), as positions in ``flat``."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for position, item in enumerate(flat):
        if item.type == "ask" or _is_situation(item.step):
            if start is None or flat[position - 1].scene != item.scene:
                if start is not None:
                    runs.append((start, position - 1))
                start = position
            continue
        if start is not None:
            runs.append((start, position - 1))
            start = None
    if start is not None:
        runs.append((start, len(flat) - 1))
    return [(a, b) for a, b in runs if any(flat[i].type == "ask" for i in range(a, b + 1))]


def check_story(
    ctx: Any,
    scenes: list[dict[str, Any]],
    questions: dict[str, QuestionFacts],
    issue: Any,
    *,
    fallback_cards: int = 0,
) -> StoryReport:
    """Record the story codes with ``issue`` and return the lints and the numbers."""
    report = StoryReport()
    flat = _flat(scenes)
    if not flat:
        return report

    def lint(code: str, path: str, message: str) -> None:
        report.lints.append(
            ValidationIssue(severity="warning", code=code, path=path, message=message)
        )

    # -- questions: set up, followed, never given away ----------------------
    lead_ins_missing = reactions_missing = 0
    for first, last in _runs(flat):
        asks = [flat[i] for i in range(first, last + 1) if flat[i].type == "ask"]
        refs = ", ".join(str(a.step.get("ref")) for a in asks)
        before = (
            flat[first - 1] if first > 0 and flat[first - 1].scene == flat[first].scene else None
        )
        if before is None or before.type != "say":
            lead_ins_missing += 1
            issue(
                "ask_not_set_up",
                asks[0].path,
                f'before ask {refs}, add a "say" line in which a character needs {{child}}'
                " to decide, without the answer",
            )
        else:
            for ask in asks:
                facts = questions.get(str(ask.step.get("ref")))
                for answer in facts.answers if facts else []:
                    needle = fold(answer).strip(" .!?…,;:")
                    if len(needle) >= 4 and any(
                        needle in fold(before.step.get(lang)) for lang in ("en", "fr")
                    ):
                        issue(
                            "lead_in_gives_answer",
                            before.path,
                            f"the line before ask {ask.step.get('ref')} says its answer"
                            f" «{answer}»; set the problem up without it",
                        )
                        break
        after = flat[last + 1] if last + 1 < len(flat) else None
        if after is None or after.scene != flat[last].scene or after.type not in LINE_TYPES:
            reactions_missing += 1
            issue(
                "ask_not_followed",
                asks[-1].path,
                f'after ask {refs}, add a "say" or "narrate" line in which a character'
                " reacts and the story moves on",
            )

    # -- how much of it is story --------------------------------------------
    counted = [f for f in flat if not _is_situation(f.step) and not _is_closeup(f.step)]
    story_lines = sum(1 for f in counted if f.type in LINE_TYPES)
    ratio = story_lines / len(counted) if counted else 0.0
    spans = moments(flat)
    gaps = [
        sum(1 for f in flat[a_end + 1 : b_start] if f.type in LINE_TYPES)
        for (_a, a_end), (b_start, _b) in zip(spans, spans[1:], strict=False)
    ]
    min_gap = min(gaps) if gaps else None
    beats = max(len(ctx.beats), 1)
    floor_lines = MIN_RALLY_LINES if ctx.is_rally else max(MIN_LINES, LINES_PER_BEAT * beats)
    floor_ratio = MIN_RALLY_STORY_RATIO if ctx.is_rally else MIN_STORY_RATIO
    thin: list[str] = []
    if ratio < floor_ratio:
        thin.append(f"only {story_lines} story lines in {len(counted)} steps")
    if min_gap is not None and min_gap < MIN_GAP:
        thin.append(f"only {min_gap} story line(s) between two teaching moments")
    if story_lines < floor_lines:
        thin.append(f"{story_lines} story lines, at least {floor_lines} are needed")
    if thin:
        issue(
            "story_too_thin",
            "scenes",
            "; ".join(thin) + ". Add story (reactions, a joke, what happens next), with at least"
            f" {MIN_GAP} lines between two teaching moments",
        )

    # -- the ending ----------------------------------------------------------
    if flat[-1].type not in LINE_TYPES:
        issue(
            "ending_not_story",
            flat[-1].path,
            f'the chapter ends on a {flat[-1].type}. End on a "say" or "narrate" line'
            " that lands " + ("LAST IMAGE" if ctx.is_rally else "ENDS ON"),
        )

    # -- what no line may say -------------------------------------------------
    blocked = [
        (name, re.compile(rf"(?<!\w){re.escape(fold(name))}(?!\w)"))
        for name in ctx.blocklist
        if len(name) >= 3
    ]
    names_leaked = 0
    for item in flat:
        step = item.step
        if (
            item.type == "say"
            and step.get("who") == "margo"
            and any(_MARGO_INTRO_RE.search(str(step.get(lang) or "")) for lang in ("en", "fr"))
        ):
            issue(
                "margo_self_intro",
                item.path,
                "Margo says what she is inside a scene. The children know her; give"
                " her a hint instead",
            )
        if item.type in LINE_TYPES:
            for lang in ("en", "fr"):
                match = _META_RE.search(str(step.get(lang) or ""))
                if match:
                    issue(
                        "meta_line",
                        item.path,
                        f"this line talks about the {match.group(0).lower()}; say it inside"
                        " the story",
                    )
                    break
        texts = _texts(step)
        for name, pattern in blocked:
            if any(pattern.search(fold(t)) for t in texts):
                names_leaked += 1
                issue(
                    "name_from_lesson",
                    item.path,
                    f"«{name}» belongs to the lesson's own example; use our cast and our places",
                )
                break

    # -- lints ----------------------------------------------------------------
    sentences = _fact_sentences(ctx)
    lecture_lines = card_echoes = 0
    says = [f for f in flat if f.type == "say"]
    for item in says:
        text = str(item.step.get(ctx.target) or "")
        words = text.split()
        tokens = content_words(text)
        lecture = len(words) >= 12 and bool(_LECTURE_RE.search(text))
        if not lecture and len(tokens) >= 5:
            lecture = any(len(tokens & s) / len(tokens) >= 0.6 for s in sentences)
        if lecture:
            lecture_lines += 1
            lint("lecture_line", item.path, "this line recites the lesson: let it happen instead")
    for position, item in enumerate(flat):
        step = item.step
        if item.type != "concept" or _is_situation(step):
            continue
        before = [f for f in flat[max(position - 6, 0) : position] if f.type in LINE_TYPES]
        for row in step.get(ctx.target) or []:
            row_words = content_words(row)
            if len(row_words) >= 3 and any(
                len(row_words & content_words(f.step.get(ctx.target))) / len(row_words) >= 0.7
                for f in before
            ):
                card_echoes += 1
                lint(
                    "card_repeats_dialogue",
                    item.path,
                    "a card row repeats a line just spoken: the card adds what the scene"
                    " did not say",
                )
                break
        title = (step.get("title") or {}).get(ctx.target, "")
        if _TEXTBOOK_TITLE_RE.match(str(title)) or (
            fold(title) and fold(title) == fold(ctx.unit_title.get(ctx.target))
        ):
            lint("card_title_textbook", item.path, f"«{title}» is a textbook heading")
        nxt = next((f for f in flat[position + 1 :] if f.type in ("ask", "concept")), None)
        if nxt is not None and nxt.type == "ask":
            facts = questions.get(str(nxt.step.get("ref")))
            if facts is not None and not facts.derived:
                card_text = " ".join(step.get(ctx.target) or [])
                for answer in facts.answers:
                    needle = fold(answer).strip(" .!?…,;:")
                    if len(needle) >= 4 and needle in fold(card_text):
                        lint(
                            "card_gives_answer",
                            item.path,
                            f"the card before {nxt.step.get('ref')} shows its answer «{answer}»",
                        )
                        break
    mentor = [f for f in says if f.step.get("who") == "mentor"]
    streak = longest = 0
    for f in says:
        streak = streak + 1 if f.step.get("who") == "mentor" else 0
        longest = max(longest, streak)
    if says and (longest >= 3 or len(mentor) / len(says) > 0.35):
        lint("mentor_lectures", "scenes", "the mentor does most of the talking")
    hero = [f for f in says if f.step.get("who") == "hero"]
    if says and len(hero) / len(says) < 0.25:
        lint("hero_too_quiet", "scenes", "{child} says less than a quarter of the lines")
    if ctx.chapter_index > 1 or ctx.is_rally:
        opening = set().union(*(content_words(t) for t in _texts_of(scenes[0])))
        before_words = set().union(
            *(content_words(line) for line in (ctx.previous_scene or {}).get("lines") or [])
        )
        before_words |= content_words((ctx.plan_entry or {}).get("opens_on"))
        if before_words and not (opening & before_words):
            lint(
                "cold_open",
                "scenes[0]",
                "the first scene shares nothing with where the last chapter stopped",
            )
    if ctx.is_rally:
        here = {pid for scene in scenes for pid in scene.get("props") or []}
        for prop in (ctx.plan or {}).get("props") or []:
            pid = prop.get("id") if isinstance(prop, dict) else None
            seen = list((ctx.props_seen or {}).get(pid, [])) if pid else []
            if pid in here:
                seen.append("rally")
            if pid and len(set(seen)) < 2:
                lint(
                    "plant_not_paid_off",
                    "props",
                    f"the plan's prop {pid!r} never comes back after it is planted",
                )

    report.quality = {
        "story_lines": story_lines,
        "steps": len(counted),
        "ratio": round(ratio, 2),
        "min_gap": min_gap,
        "lead_ins_missing": lead_ins_missing,
        "reactions_missing": reactions_missing,
        "lecture_lines": lecture_lines,
        "card_echoes": card_echoes,
        "fallback_cards": fallback_cards,
        "names_leaked": names_leaked,
    }
    return report


def _texts(step: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for lang in ("en", "fr"):
        value = step.get(lang)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            out.extend(str(v) for v in value)
    title = step.get("title")
    if isinstance(title, dict):
        out.extend(str(v) for v in title.values())
    return out


def _texts_of(scene: dict[str, Any]) -> list[str]:
    return [t for step in scene["steps"] for t in _texts(step)]


def _fact_sentences(ctx: Any) -> list[set[str]]:
    rows = list(ctx.lesson_list("concepts")) + list(ctx.lesson_list("key_points"))
    out: list[set[str]] = []
    for row in rows:
        for sentence in re.split(r"(?<=[.!?…])\s+", row):
            words = content_words(sentence)
            if len(words) >= 4:
                out.append(words)
    return out
