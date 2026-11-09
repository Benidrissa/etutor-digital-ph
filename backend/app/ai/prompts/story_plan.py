"""The episode plan's user message (#2680, story generator v4).

The showrunner model plans the whole module as ONE episode before any
chapter is written: the premise, the props that come back, each chapter's
beats (which lesson IDEA cracks which problem), its hook, and the rally. It
sees the course bible, the bible's mission for the module as a seed, every
lesson's fact sheet (never its introduction, field example or synthesis:
those carried the textbook's order and its own people and towns) and every
course question as ``[ref] stem → correct answer`` — never a wrong option, a
misconception or an explanation.

The system prompt (``ai-prompt-story-plan-kids-system`` /
``ai-prompt-story-plan-system``) is an admin-editable setting; the JSON
contract lives here, in code.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.domain.services.story_repair import clean_text

if TYPE_CHECKING:
    from app.domain.services.story_plan import PlanRequest

#: Planning fields are at most this many words; discoveries, card titles and
#: catchphrases have their own limits (see :mod:`story_plan`).
FIELD_WORDS = 30


def _bible_block(request: PlanRequest) -> str:
    bible = request.bible.content
    cast = []
    for member in bible.get("cast") or []:
        cid, name = member["id"], member["name"]
        if cid == "hero":
            name = '{child} (the learner; write exactly "{child}")'
        elif cid == "friend":
            name = '{friend} (the learner types the name; write exactly "{friend}")'
        cast.append(f'- "{cid}" — {name}: {member.get("about", "")}')
    places = [
        f'- "{p["id"]}" — {p["title"]["en"]} / {p["title"]["fr"]}: {p["look"]}'
        for p in bible.get("places") or []
    ]
    facts = [f"- {f['en']}" for f in bible.get("facts") or []]
    mission = request.mission or {}
    lines = [
        "=== THE SERIES BIBLE (the same in every episode) ===",
        "CAST — use these ids:",
        *cast,
        "PLACES — use these ids:",
        *places,
    ]
    if facts:
        lines += ["LOCAL DETAILS you may use:", *facts]
    lines.append(
        "THE BIBLE'S MISSION FOR THIS MODULE (a seed: sharpen it into a premise with a want,"
        f' stakes and a clock): "{mission.get("en", "")}" / "{mission.get("fr", "")}"'
    )
    previous = request.previous
    if previous:
        lines.append(
            f"PREVIOUSLY IN THE SERIES: module {previous.get('number')}"
            f" «{previous.get('title', '')}»: {previous.get('logline', '')}"
        )
    return "\n".join(lines)


def _fact_sheets(request: PlanRequest) -> str:
    lines = ["=== FACT SHEETS — the facts to plan with, NOT the plot ==="]
    if request.blocklist:
        lines.append(
            "Never use these names, which belong to the lessons' own examples: "
            + ", ".join(request.blocklist)
            + "."
        )
    for number, lesson in enumerate(request.lessons, start=1):
        title = lesson.title.get(request.language) or lesson.title.get("en")
        lines.append(f"LESSON {lesson.unit_number} «{title}» → chapter {number}")
        lines += [f"  IDEA {n}: {idea}" for n, idea in enumerate(lesson.sheet.ideas, start=1)]
        if lesson.sheet.key_facts:
            lines.append(
                "  KEY FACTS: "
                + " ".join(f"{n}. {fact}" for n, fact in enumerate(lesson.sheet.key_facts, 1))
            )
    return "\n".join(lines)


def _questions(request: PlanRequest) -> str:
    lines = ["=== COURSE QUESTIONS (ref · question → correct answer; their wording is fixed) ==="]
    for candidate in request.candidates:
        if candidate.only_unit:
            scope = f"quiz of lesson {candidate.only_unit} only"
        elif candidate.covers:
            span = (
                candidate.covers[0]
                if len(candidate.covers) == 1
                else f"{candidate.covers[0]}–{candidate.covers[-1]}"
            )
            scope = f"quiz {candidate.quiz_unit}, covers lessons {span}"
        else:
            scope = f"quiz {candidate.quiz_unit}, for the rally"
        lines.append(
            f"[{candidate.ref}] ({scope}) «{clean_text(candidate.mcq.stem)}» →"
            f" «{clean_text(candidate.mcq.correct_text)}»"
        )
    if not request.candidates:
        lines.append("(none: every chapter's questions will be written for it)")
    return "\n".join(lines)


_OUTPUT = """{
 "episode_title": {"en": "...", "fr": "..."},
 "logline": "English, at most 40 words: who wants what, what is in the way, what is lost if they fail",
 "want": "...", "stakes": "...", "clock": "...",
 "hero_flaw": "a small, funny flaw {child} is past by the rally",
 "voices": {"hero": "...", "friend": "...", "mentor": "...", "family": "...", "margo": "..."},
 "running_gag": "...",
 "catchphrases": [{"who": "friend", "en": "...", "fr": "..."}],
 "props": [{"id": "dry_leaf", "en": "the dry leaf", "fr": "la feuille sèche", "query": "dry brown leaf", "kind": "real", "emoji": "🍂", "at": "ground", "size": "s", "planted": "__FIRST__", "paid_off": "rally"}],
 "chapters": [
  {"unit": "__FIRST__", "title": {"en": "...", "fr": "..."}, "when": "Saturday morning",
   "opens_on": "...", "goal": "...", "obstacle": "...",
   "beats": [{"ideas": [1], "place": "a place id", "cast": ["hero", "friend", "family"],
     "problem": "the problem on stage that only this idea solves",
     "discovery": {"en": "the idea as {child} says it to a friend", "fr": "..."},
     "card_title": {"en": "...", "fr": "..."},
     "questions": ["q2"]}],
   "turn": "...",
   "ends_on": "the exact image or line the chapter stops on, unresolved",
   "game": null,
   "paper_task": "..."}
 ],__RALLY__
 "__complete": true
}"""

_RALLY = """
 "rally": {"title": {"en": "...", "fr": "..."}, "when": "...", "opens_on": "...", "final_obstacle": "...",
   "steps": [{"from_unit": "__FIRST__", "uses": "how that chapter's discovery beats part of the obstacle", "questions": ["q9"]}],
   "payoffs": ["dry_leaf"], "resolution": "what happens on stage that shows the win",
   "last_image": "a warm, funny callback to the running gag", "game": null, "paper_task": "..."},"""


def rally_range(request: PlanRequest) -> tuple[int, int]:
    """How many questions the rally takes: 3 to min(6, candidates)."""
    top = min(6, len(request.candidates))
    return min(3, top), top


def build_plan_user_message(request: PlanRequest) -> str:
    """The plan call's user message (design §2)."""
    n = len(request.lessons)
    units = ", ".join(
        f"{lesson.unit_number} «{lesson.title.get(request.language) or lesson.title.get('en')}»"
        for lesson in request.lessons
    )
    first = request.lessons[0].unit_number if request.lessons else "1.1"
    request_line = (
        f"REQUEST: plan the episode for the module «{request.module_title[request.language]}»"
        f" of «{request.course_title[request.language]}»: {n} chapter{'s' if n > 1 else ''}"
        f" — {units}"
        + (" — then the rally." if request.has_rally else ". This module has no rally.")
    )
    ideas = ", ".join(
        f"lesson {lesson.unit_number} has IDEAS 1–{len(lesson.sheet.ideas)}"
        for lesson in request.lessons
    )
    low, high = rally_range(request)
    rules = [
        "RULES:",
        f"- Planning fields are in English, at most {FIELD_WORDS} words each. Titles,"
        ' discoveries, card titles and catchphrases have "en" (English) and "fr" (French).',
        f'- "chapters": exactly {n} entries, in this order:'
        f" {', '.join(lesson.unit_number for lesson in request.lessons)}. {ideas[:1].upper()}"
        f"{ideas[1:]}.",
        '- "beats": 1 to 4 per chapter; every IDEA of a lesson is in exactly one beat of its'
        " own chapter.",
        '- "discovery" at most 90 characters; "title" and "card_title" at most 40;'
        " catchphrases at most 50.",
        '- "place": a place id of the bible. "cast": 2 or 3 cast ids, "hero" always among them.',
        '- "questions": refs from the list above. At most 2 per beat and 4 per lesson'
        " chapter, never one ref in two lesson chapters. A question goes only to a chapter"
        " of a lesson its quiz covers; a question from a lesson's own quiz goes only to that"
        " lesson's chapter." + (f" The rally takes {low} to {high}." if request.has_rally else ""),
        '- "game": a one-line description in exactly one chapter'
        + (" or the rally" if request.has_rally else "")
        + ", null everywhere else.",
        '- Every "paper_task" is one short task done on paper that the story needs.',
        "- chapters[k].opens_on picks up chapters[k-1].ends_on"
        + (
            "; the rally's opens_on picks up the last chapter's ends_on."
            if request.has_rally
            else "."
        ),
        '- "props": at most 4; each is planted in one chapter ("planted": its unit) and paid'
        ' off later ("paid_off": a later unit or "rally"); "query" is 2 to 5 English words a'
        ' picture search needs; "kind" is "real" or "sticker".',
    ]
    if request.has_rally:
        rules.append(
            '- The rally\'s "steps" use a discovery from every lesson chapter; "payoffs" name'
            " props planted earlier."
        )
    output = _OUTPUT.replace("__RALLY__", _RALLY if request.has_rally else "").replace(
        "__FIRST__", first
    )
    return "\n\n".join(
        [
            request_line,
            _bible_block(request),
            _fact_sheets(request),
            _questions(request),
            "=== OUTPUT ===\nReturn ONE JSON object with exactly these keys:\n"
            + output
            + (
                '\n(The "rally" key is present only when the module has a quiz unit.)'
                if request.has_rally
                else '\n(No "rally" key: this module has no quiz unit.)'
            ),
            "\n".join(rules),
        ]
    )


def build_incremental_block(plan: dict[str, Any], units: list[str]) -> str:
    """The INCREMENTAL MODE block: rewrite only the chapters whose lesson changed."""
    names = ", ".join(units)
    return (
        "=== THE CURRENT PLAN (keep it) ===\n"
        + json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
        + f"\nLesson {names} changed: its new fact sheet is above. Rewrite ONLY the entry of"
        f" chapter {names}: its goal, obstacle, beats, turn and questions. Keep its"
        ' "title", "when", "opens_on" and "ends_on" exactly as they are, so it still joins'
        " the chapters around it. Return the complete plan; every other field stays as it is."
    )


def build_plan_repair_message(
    user_message: str, issues: list[Any], previous: dict[str, Any] | None
) -> str:
    """The one plan repair: the checks it failed, and its JSON."""
    bullets = "\n".join(f"- [{i.code}] {i.path}: {i.message}" for i in issues[:40]) or (
        "- your previous response could not be read as JSON (or was cut off); answer with"
        " complete, valid JSON"
    )
    previous_json = (
        json.dumps(previous, ensure_ascii=False, separators=(",", ":"))
        if previous
        else "(unreadable)"
    )
    return (
        f"{user_message}\n\n=== REPAIR (attempt 1 of 1) ===\n"
        "Your plan failed these checks. Fix every one and return the COMPLETE plan again,"
        f" same structure:\n{bullets}\n\nYour previous JSON: {previous_json}"
    )
