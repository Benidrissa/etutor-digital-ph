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

from app.domain.services import story_journey as journey_table
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
    note = _policy_note(request)
    if note:
        lines.append(note)
    if request.linear:
        lines += _quest_lines(request)
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


def _quest_lines(request: PlanRequest) -> list[str]:
    """The course's quest and shadow (#2749), the bible's, when it has them."""
    journey = request.journey or {}
    lines = []
    if journey.get("quest"):
        lines.append(f"THE COURSE QUEST (what the learner can do by the end): {journey['quest']}")
    if journey.get("shadow"):
        lines.append(f"THE SHADOW (the misconception the story undoes): {journey['shadow']}")
    return lines


def journey_stages(request: PlanRequest) -> list[list[int]]:
    from app.domain.services.story_plan import journey_stages as stages_of

    return stages_of(request)


def _journey_block(request: PlanRequest) -> str:
    """The stages each chapter plays (#2749): the table, applied by code, never chosen."""
    stages = journey_stages(request)
    lines = [
        "=== THE JOURNEY (linear): the stages each chapter plays — fixed, not yours to change ===",
        "Each chapter asks its question near the start and answers it by its end. Its goal,"
        " obstacle and turn follow its stages.",
    ]
    names = [
        f"chapter {n} (lesson {lesson.unit_number})"
        for n, lesson in enumerate(request.lessons, start=1)
    ]
    if request.has_rally:
        names.append("the rally")
    for name, chapter_stages in zip(names, stages, strict=False):
        lines.append(f"{name}:")
        lines += [f"  {line}" for line in journey_table.stage_lines(chapter_stages)]
    return "\n".join(lines)


def journey_system_block(request: PlanRequest) -> str:
    """The wording of a journey plan's chapters (#2749), added to the system prompt.

    Rules 5 and 6 of the admin-editable system prompts have each chapter end open
    and the next pick it up; a journey plan has its own wording, built here, so
    an admin override still applies to legacy plans.
    """
    return (
        "=== THIS EPISODE FOLLOWS THE HERO'S JOURNEY (replaces rules 5 and 6 above) ===\n"
        "5. Every chapter has a goal (what the characters try today), an obstacle (what goes"
        " wrong), a turn (the discovery that gets them past it), and a story question that it"
        " asks and answers. Each chapter plays the journey stages the user message lists for"
        " it. A chapter ends on ONE plain statement of what the next chapter is about, never"
        " a question; it never ends on a summary, on praise or on homework.\n"
        "6. Each chapter opens on the topic its predecessor named: the next moment of the"
        " same scene, or a clean cut marked by time or place. Never a recap, never the"
        " mission announced again. The last chapter closes warm and, if a next module is"
        " named, says in one sentence what comes next."
    )


def _journey_rules(request: PlanRequest, last: str) -> list[str]:
    nxt = request.next_module_title
    title = (nxt or {}).get(request.language) or (nxt or {}).get("en")
    close = (
        f"the story closes warm and, in one sentence, names the next module «{title}»"
        if title
        else "the story closes warm; there is no next module to name"
    )
    return [
        '- "question": each lesson chapter has one, in English, at most'
        f" {journey_table.WORD_LIMIT} words: the story question the chapter asks and answers."
        " It is not a quiz question and has nothing to do with the refs in the beats'"
        ' "questions".',
        '- "stages": do not write them; each chapter plays the stages of THE JOURNEY above.',
        '- "ends_on" of every chapter but the last is ONE statement of what the next chapter'
        " is about, never a question.",
        f"- In the last chapter ({'the rally' if request.has_rally else last}) {close}.",
    ]


def _voices(request: PlanRequest) -> str:
    """The ``voices`` keys of the answer; a new plan lists the bible's cast (no mentor when none)."""
    ids = ["hero", "friend", "mentor", "family", "margo"]
    if request.cast_policy is not None:
        ids = [m["id"] for m in request.bible.content.get("cast") or []] or ids
    return ", ".join(f'"{cid}": "..."' for cid in ids)


def _policy_note(request: PlanRequest) -> str:
    """What the mentor policy (#2710) tells the planner; nothing for a legacy plan."""
    if request.cast_policy == "none":
        return (
            "NO MENTOR: there is no teacher or supervisor in this series. Never use the id"
            ' "mentor". The children find things out themselves; the friend is the sceptical'
            ' one ("how do you know?"), and the family member or Margo gives a clue at most.'
        )
    if request.cast_policy == "cameo":
        return (
            'MENTOR CAMEO: the "mentor" appears only in the FIRST beat of the first chapter'
            " and the LAST beat of the last chapter, to open or close the story. He never"
            " explains and never hands a question over; the friend does the doubting."
        )
    return ""


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
 "voices": {__VOICES__},
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


def _figures_block(request: PlanRequest) -> str:
    """The course's own pictures the module may use (#2709), built by code before this call."""
    from app.domain.services.story_assets import plan_figures_block  # noqa: PLC0415

    block = plan_figures_block(request.catalogue)
    return f"=== COURSE FIGURES ===\n{block}" if block else ""


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
        '- "place": a place id of the bible. "cast": 2 or 3 cast ids, "hero" always among them.'
        ' Margo speaks only in a beat whose "cast" lists "margo" (2 or 3 ids with her).',
        '- "questions": refs from the list above. At most 2 per beat and 4 per lesson'
        " chapter, never one ref in two lesson chapters. A question goes only to a chapter"
        " of a lesson its quiz covers; a question from a lesson's own quiz goes only to that"
        " lesson's chapter."
        + (
            (
                f" The rally takes up to {high}, and ONLY questions no chapter takes: a"
                " question asked in a chapter is never asked again (fewer is fine)."
                if request.cast_policy is not None
                else f" The rally takes {low} to {high}."
            )
            if request.has_rally
            else ""
        ),
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
        ' picture search needs; "kind" is "real" or "sticker" — or "figure" with "figure": "A1"'
        " when a COURSE FIGURES entry shows this very thing (then use it: the course owns the picture). "
        '"en" and "fr" are the name'
        ' tag: a short noun with its article, at most 4 words and 40 characters ("the'
        ' jar", "le bocal"), never a description ("le bocal fermé avec quelque chose de'
        ' gris" is wrong).',
    ]
    last = request.lessons[-1].unit_number if request.lessons else first
    if request.has_rally:
        rules.append(
            '- The rally\'s "steps" use a discovery from every lesson chapter; "payoffs" name'
            " props planted earlier."
        )
    else:
        rules.append(
            f"- This module has no rally: chapter {last} is the climax. Its turn beats the"
            " episode's obstacle for good and wins the want on stage; {child}'s flaw meets"
            f' its last test; every prop is paid off by then ("paid_off": at the latest'
            f' "{last}"). Its "ends_on" is a warm last image, a callback to the running gag:'
            " never a cliffhanger."
            + ("" if request.linear else " Every other chapter ends unresolved.")
        )
    if request.linear:
        rules += _journey_rules(request, last)
    output = _OUTPUT.replace("__RALLY__", _RALLY if request.has_rally else "").replace(
        "__VOICES__", _voices(request)
    )
    if request.linear:
        output = output.replace(
            '"ends_on": "the exact image or line the chapter stops on, unresolved"',
            '"ends_on": "one statement of what the next chapter is about, not a question"',
        ).replace(
            '"title": {"en": "...", "fr": "..."}, "when": "Saturday morning",',
            '"title": {"en": "...", "fr": "..."}, "question": "the story question this chapter'
            ' asks and answers", "when": "Saturday morning",',
        )
    if not request.has_rally:
        output = output.replace('"paid_off": "rally"', '"paid_off": "__LAST__"').replace(
            "is past by the rally", "is past by the last chapter"
        )
    output = output.replace("__FIRST__", first).replace("__LAST__", last)
    return "\n\n".join(
        [
            request_line,
            _bible_block(request),
            *([_journey_block(request)] if request.linear else []),
            _fact_sheets(request),
            _figures_block(request),
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
