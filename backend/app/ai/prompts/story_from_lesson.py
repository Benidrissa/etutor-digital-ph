"""Prompts of story mode: a chapter's screenplay (#2674).

The model writes the **screenplay** of one chapter — scenes at the course's
places, with its characters teaching through dialogue — and the pedagogy
around it (objectives, misconceptions, questions, exercises, mini-game,
tutor). The application only checks, numbers and resolves what it wrote
(:mod:`app.domain.services.story_repair`).

The system prompt (register, the learner-as-hero rules, the craft of the
screenplay) is an admin-editable platform setting, like every other content
prompt. The course bible, the lesson, the quiz and the JSON contract live in
the user message, which is code: the parser depends on it, so an admin
override of the system prompt must not be able to drop them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.ai.prompts.lesson import (
    COUNTRY_NAMES_EN,
    COUNTRY_NAMES_FR,
    _apply_settings_template,
)
from app.api.v1.schemas.story_course import DRAWN_VISUALS, MOODS, ValidationIssue
from app.domain.services.story_repair import (
    ARC_CLOSES,
    ARC_CONTINUES,
    ARC_OPENS,
    ARC_OPENS_CLOSES,
    CHOICE_IDS,
    MAX_ASKS_IN_A_ROW,
    MAX_OBJECTIVES,
    MAX_SCENES,
    MIN_SCENES,
    STORY_LINE_LIMITS,
    LessonStoryContext,
    clean_text,
    truncate,
)

if TYPE_CHECKING:
    from app.domain.models.course import Course

#: Deprecated since #2680 (the v4 story prompts below replace them): kept
#: defined, unused, so an admin override of them cannot pin the old register.
STORY_SYSTEM_KEY = "ai-prompt-story-system"
STORY_KIDS_SYSTEM_KEY = "ai-prompt-story-kids-system"
#: #2680: the chapter screenplay, the episode plan and the practice pack.
SCREENPLAY_SYSTEM_KEY = "ai-prompt-story-screenplay-system"
SCREENPLAY_KIDS_SYSTEM_KEY = "ai-prompt-story-screenplay-kids-system"
PLAN_SYSTEM_KEY = "ai-prompt-story-plan-system"
PLAN_KIDS_SYSTEM_KEY = "ai-prompt-story-plan-kids-system"
PACK_SYSTEM_KEY = "ai-prompt-story-pack-system"

LANGUAGE_NAMES = {
    "en": {"en": "English", "fr": "French"},
    "fr": {"en": "anglais", "fr": "français"},
}

#: A lesson IDEA as the fact sheet carries it, at most this long.
IDEA_LIMIT = 600
#: The most names a blocklist sends.
MAX_BLOCKLIST = 40
#: Story lines of a lesson chapter: max(14, 6 × beats) to this many.
MAX_STORY_LINES = 34
#: Lines of the previous chapter's last scene shown to the next one.
LAST_SCENE_LINES = 12


def get_story_system_prompt(
    language: str,
    country: str,
    level: int,
    bloom_level: str,
    course_title: str | None = None,
    course_description: str | None = None,
    module_title: str = "",
    unit_title: str = "",
    syllabus_context: str = "",
    course_domain: str = "",
    course: Course | None = None,
) -> str:
    """Render the story system prompt from platform settings.

    Kids courses (taxonomy audience) get their own register via
    ``ai-prompt-story-kids-system``, exactly as lessons and quizzes do.
    """
    from app.ai.prompts.audience import detect_audience, get_audience_guidance

    audience = detect_audience(course)
    key = STORY_KIDS_SYSTEM_KEY if audience.is_kids else STORY_SYSTEM_KEY
    home = "en" if language == "fr" else "fr"
    extra: dict[str, Any] = {
        "target_language": language,
        "home_language": home,
        "target_language_name": LANGUAGE_NAMES["en"][language],
        "home_language_name": LANGUAGE_NAMES["en"][home],
    }
    if audience.is_kids:
        extra["age_range"] = f"{audience.age_min}-{audience.age_max}"
        extra["audience_guidance"] = get_audience_guidance(audience, language)
    return _apply_settings_template(
        key,
        language,
        country,
        level,
        bloom_level,
        course_title,
        course_description,
        module_title,
        unit_title,
        syllabus_context,
        course_domain,
        **extra,
    )


@dataclass(frozen=True)
class StoryPlan:
    """How much the model must write, derived from the lesson and its quiz."""

    objectives: int
    #: Questions to reach in all: derived + extra.
    questions: int
    #: Extra questions to write (without a covering quiz: all of them).
    extra_questions: int

    @property
    def exercises(self) -> int:
        return self.objectives


def plan_for(ctx: LessonStoryContext) -> StoryPlan:
    """Enough questions for one or two after each concept, and 2 per objective (C.5).

    With a covering quiz the number of derived questions is the model's pick,
    so ``extra_questions`` is the total to reach, from which the model
    subtracts the candidates it picked.
    """
    if ctx.is_rally:
        return StoryPlan(objectives=1, questions=4, extra_questions=0)
    concepts = max(len(ctx.lesson_list("concepts")), 1)
    derived = len(ctx.mcqs)
    if derived == 0 or ctx.picks_from_quiz:
        objectives = 2
        total = max(2 * objectives, concepts + 1)
        return StoryPlan(objectives=objectives, questions=total, extra_questions=total)
    objectives = max(1, min(MAX_OBJECTIVES, derived // 2))
    total = max(2 * objectives, concepts + 1, derived)
    return StoryPlan(objectives=objectives, questions=total, extra_questions=total - derived)


# --------------------------------------------------------------------------
# The blocks of the user message
# --------------------------------------------------------------------------

_ARC_LINE = {
    ARC_OPENS: (
        "This is the FIRST chapter of the module: the mission appears here (someone brings"
        " the problem, a challenge is announced, something goes missing...) and the"
        " characters decide to take it on. It is not solved yet."
    ),
    ARC_CONTINUES: (
        "This is a MIDDLE chapter: the mission is already known; this chapter moves it"
        " forward with what the lesson teaches, without solving it."
    ),
    ARC_CLOSES: (
        "This is the LAST chapter of the module: the mission is solved here, thanks to what"
        " the characters learned. End on that success, in the story's own words."
    ),
    ARC_OPENS_CLOSES: (
        "This module has only this chapter: the mission appears at the start and is solved"
        " at the end."
    ),
}


def _bible_block(ctx: LessonStoryContext) -> str:
    bible = ctx.bible_content
    cast_rows = []
    for member in bible.get("cast") or []:
        name = member["name"]
        if member["id"] == "friend":
            name = '{friend} (the learner types the name; write exactly "{friend}")'
        elif member["id"] == "hero":
            name = '{child} (the learner; write exactly "{child}")'
        cast_rows.append(f'- "{member["id"]}" — {name}: {member.get("about", "")}')
    place_rows = [
        f'- "{place["id"]}" — {place["title"]["en"]} / {place["title"]["fr"]}: {place["look"]}'
        for place in bible.get("places") or []
    ]
    fact_rows = [
        f"- {fact['en']}" + ("" if not fact.get("invented") else " (invented)")
        for fact in bible.get("facts") or []
    ]
    mission = ctx.mission or {}
    mission_line = (
        f'THE MODULE\'S MISSION: "{mission.get("en", "")}" / "{mission.get("fr", "")}"\n'
        if mission
        else ""
    )
    return (
        "=== THE COURSE BIBLE (the same in every chapter of every module) ===\n"
        'CAST — use these ids in "who" and in a scene\'s "cast":\n'
        + "\n".join(cast_rows)
        + '\nPLACES — use these ids in a scene\'s "place":\n'
        + "\n".join(place_rows)
        + ("\nLOCAL DETAILS you may use:\n" + "\n".join(fact_rows) if fact_rows else "")
        + "\n\n"
        + mission_line
        + _ARC_LINE.get(ctx.arc, _ARC_LINE[ARC_CONTINUES])
        + "\n"
    )


def _figures_block(ctx: LessonStoryContext) -> str:
    refs = [
        r
        for r in ctx.lesson.get("source_image_refs") or []
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    ]
    if not refs:
        return "FIGURES: none."
    rows = []
    for number, ref in enumerate(refs, start=1):
        caption = clean_text(ref.get("caption_en") or ref.get("caption") or ref.get("caption_fr"))
        rows.append(f"FIGURE {number}: {caption or ref.get('figure_number') or 'a lesson figure'}")
    return "\n".join(rows)


def _lesson_block(ctx: LessonStoryContext) -> str:
    lesson = ctx.lesson
    parts = [f"INTRODUCTION:\n{clean_text(lesson.get('introduction'))}"]
    for number, paragraph in enumerate(ctx.lesson_list("concepts"), start=1):
        parts.append(f"CONCEPT {number}:\n{paragraph}")
    if ctx.lesson_text("aof_example"):
        parts.append(f"FIELD EXAMPLE:\n{ctx.lesson_text('aof_example')}")
    if ctx.lesson_text("synthesis"):
        parts.append(f"SYNTHESIS:\n{ctx.lesson_text('synthesis')}")
    key_points = ctx.lesson_list("key_points")
    if key_points:
        rows = "\n".join(f"{n}. {point}" for n, point in enumerate(key_points, start=1))
        parts.append(f"KEY POINTS:\n{rows}")
    sources = ctx.lesson_list("sources_cited")
    if sources:
        parts.append("SOURCES: " + "; ".join(sources[:10]))
    parts.append(_figures_block(ctx))
    return "\n\n".join(parts)


def _recap_block(ctx: LessonStoryContext) -> str:
    rows = []
    for lesson in ctx.lessons_recap:
        title = lesson.get("title") or {}
        rows.append(f"- {lesson.get('unit_number')}: {title.get(ctx.target) or title.get('en')}")
        for objective in lesson.get("objectives") or []:
            rows.append(f"    · {objective}")
    return "THE MODULE'S LESSONS, already told as chapters:\n" + ("\n".join(rows) or "- (none)")


def _quiz_block(ctx: LessonStoryContext) -> str:
    if not ctx.mcqs:
        return (
            "QUIZ: this unit has no quiz yet. Write every question yourself, as extra"
            ' questions, and leave "derived" as an empty list.'
        )
    if ctx.is_rally:
        lines = [
            "CANDIDATE QUIZ QUESTIONS from the module's quiz. Pick 3 to"
            f" {ctx.max_picks} that together cover the module's lessons — prefer the ones"
            " NOT marked (already asked); a marked one may come back once as a review."
            ' Write a "derived" entry, with its ref, for each one you pick. Picked'
            " questions are fixed: you translate them and explain their wrong options;"
            " you never change them:"
        ]
    elif ctx.picks_from_quiz:
        lines = [
            f"CANDIDATE QUIZ QUESTIONS from the quiz of unit {ctx.quiz_unit_number}, which"
            " covers several lessons of this module. Pick ONLY the questions that test THIS"
            f" lesson's content — at most {ctx.max_picks}, none if none fits — and write a"
            ' "derived" entry, with its ref, for each one you pick. Leave every other'
            " candidate out. Picked questions are fixed: you translate them and explain"
            " their wrong options; you never change them:"
        ]
    else:
        lines = [
            "QUIZ QUESTIONS (fixed: you translate them and explain their wrong options;"
            " you never change them):"
        ]
    for mcq in ctx.mcqs:
        marker = " (already asked)" if mcq.asked_before else ""
        lines.append(f"\n[{mcq.ref}]{marker} {mcq.stem}")
        for index, option in enumerate(mcq.options):
            mark = "  <- correct" if index == mcq.correct_index else ""
            lines.append(f"  {CHOICE_IDS[index]}) {option}{mark}")
            known = (
                mcq.option_misconceptions[index] if index < len(mcq.option_misconceptions) else None
            )
            if known:
                lines.append(f"     why it is wrong (from the course): {known}")
        if mcq.explanation:
            lines.append(f"  explanation: {mcq.explanation}")
    return "\n".join(lines)


def _schema(ctx: LessonStoryContext, plan: StoryPlan) -> str:
    target, home = ctx.target, ctx.home
    concepts = len(ctx.lesson_list("concepts"))
    moods = ", ".join(MOODS)
    visuals = "; ".join(
        f'"{name}" with params {{'
        + ", ".join(
            f'"{param}": {desc}' + ("" if required else " (optional)")
            for param, (required, desc) in params.items()
        )
        + "}"
        for name, params in DRAWN_VISUALS.items()
    )
    en_limit, fr_limit = STORY_LINE_LIMITS["en"], STORY_LINE_LIMITS["fr"]
    title_line = (
        '  "chapter_title": {"en": "the rally\'s title", "fr": "..."},\n' if ctx.is_rally else ""
    )
    concept_rule = (
        f"- Every lesson concept (CONCEPT 1 to {concepts}) is taught in the story: first the"
        " characters meet it in a small situation (a discovery, a mistake, a joke, a real"
        ' local detail), then ONE concept card sums it up, with "teaches": its number.'
        "\n"
        if concepts and not ctx.is_rally
        else ""
    )
    return f"""Return ONE JSON object with exactly these keys. Every {{"en": ..., "fr": ...}} object has English in "en" and French in "fr".

{{
{title_line}  "objectives": [{{"id": "o1", "en": "learning objective", "fr": "objectif"}}],
  "misconceptions": [{{"id": "m_short_slug", "en": "Thinks that ...", "fr": "Pense que ..."}}],
  "scenes": [
    {{"place": "a place id", "cast": ["hero", "friend"], "objective": "o1",
      "steps": [
        {{"type": "narrate", "en": "what happens", "fr": "ce qui se passe"}},
        {{"type": "say", "who": "friend", "mood": "surprised", "en": "the words only", "fr": "les mots seulement"}},
        {{"type": "show", "figure": 1}},
        {{"type": "concept", "teaches": 1, "title": {{"en": "...", "fr": "..."}}, "en": ["row", "row"], "fr": ["ligne", "ligne"]}},
        {{"type": "ask", "ref": "q1"}},
        {{"type": "game"}},
        {{"type": "photo", "ref": "E1"}}
      ]}}
  ],
  "derived": [
    {{
      "ref": "q1",
      "objective": "o1",
      "prompt_home": "the question translated into the home language",
      "options_home": ["option a translated", "option b translated", "..."],
      "explanation_home": "the explanation translated into the home language",
      "hint": {{"en": "a general hint that does not give the answer away", "fr": "..."}},
      "distractors": [{{"option": "b", "misconception": "m_short_slug", "hint": {{"en": "aimed at this mistake", "fr": "..."}}}}]
    }}
  ],
  "questions": [
    {{"id": "x1", "type": "choice", "objective": "o1", "prompt": {{"en": "...", "fr": "..."}},
      "choices": [{{"id": "a", "en": "...", "fr": "..."}}, {{"id": "b", "en": "...", "fr": "...", "misconception": "m_short_slug"}}],
      "answer": "a", "hints": [{{"en": "...", "fr": "..."}}],
      "traps": [{{"answer": "b", "misconception": "m_short_slug", "hint": {{"en": "...", "fr": "..."}}}}],
      "explanation": {{"en": "...", "fr": "..."}}}}
  ],
  "exercises": [{{"objective": "o1", "prompt": {{"en": "a short task done on paper", "fr": "..."}},
      "working": {{"en": ["model answer, line by line"], "fr": ["corrigé, ligne par ligne"]}},
      "mark_scheme": {{"en": "what earns the mark", "fr": "..."}}}}],
  "minigame": {{
    "title": {{"en": "...", "fr": "..."}},
    "instruction": {{"en": "...", "fr": "..."}},
    "hint_after_wrong": {{"en": "...", "fr": "..."}},
    "rounds": [{{"prompt": {{"en": "Catch the ...", "fr": "Attrape ..."}},
      "items": [{{"label": {{"en": "true statement or key term", "fr": "..."}}, "correct": true}},
                {{"label": {{"en": "a tempting wrong idea", "fr": "..."}}, "correct": false, "trap": "m_short_slug"}}]}}]
  }},
  "facts": [{{"en": "a real local detail the story uses", "fr": "...", "source": "where it comes from"}}],
  "tutor": {{
    "intro": {{"en": "Margo greets {{child}} and says she is an AI, not a real person", "fr": "... une IA, pas une vraie personne"}},
    "off_topic": {{"en": "kind redirect back to the lesson", "fr": "..."}},
    "worry": {{"en": "if the learner shares a worry: talk to a trusted person now", "fr": "..."}},
    "earlier_weeks": "one line on what came before this unit"
  }},
  "__complete": true
}}

THE SCREENPLAY ("scenes"):
- {MIN_SCENES} to {MAX_SCENES} scenes{" (2 or 3 for the rally)" if ctx.is_rally else ""}, each at ONE place of the bible and with 2 or 3 characters on stage ("cast").
{concept_rule}- A concept card has 2 to 4 short rows, the same number in "en" and "fr". Right after it, 1 or 2 "ask" steps on that concept. Never more than {MAX_ASKS_IN_A_ROW} "ask" steps in a row.
- Ask every question exactly once, by its ref: a "derived" entry by its "ref" (q1, q2...), an extra question by its "id" (x1, x2...).
- "say": "who" is a cast id and "mood" one of {moods}. The line is ONLY the words spoken: never "Name:", "Name says" or "X dit :" in front, no quotation marks around it.
- The hero ({{child}}) speaks in the first person, often: asks, guesses, gets something wrong, works it out. The friend is "{{friend}}", written exactly so. Margo appears at most once or twice, to give a hint, never an answer.
- "narrate" is short stage direction in the present tense: where we are, what happens.
- "show": {{"type": "show", "figure": N}} with a FIGURE listed above, or — only when the lesson's numbers fit one — a drawn visual, {{"type": "show", "visual": ..., "params": {{...}}}}, one of: {visuals}. No other visual exists: the player cannot draw it. Only where it helps.
- {{"type": "game"}} once, where a playful moment fits; {{"type": "photo", "ref": "E1"}} once per exercise (E1, E2... in the order of "exercises"), when a character hands over a task to do on paper.
- Every line is written for its moment: no "This story is about you", no "Well done, the lesson is over", no line that would fit any chapter, nothing about pages, quizzes or the app.
- Story lines at most {en_limit} characters in English and {fr_limit} in French; question prompts at most 150; hints at most 120.

COUNTS AND RULES FOR THIS CHAPTER:
- Language of instruction: "{target}". Home language: "{home}". Write both languages everywhere.
- "objectives": exactly {plan.objectives}, ids o1..o{plan.objectives}.
{_derived_rule(ctx, plan)}
- "exercises": exactly {plan.exercises}, one per objective{" (a short recap task on paper)" if ctx.is_rally else ""}.
- "minigame": 2 or 3 rounds of 4-5 items; at least 2 correct and 1 wrong item per round.
- "facts": the real local details your scenes use, each with its source; a detail you made up has "invented": true instead.
- Every misconception id you use must be in "misconceptions". Never put a misconception on a correct option.
- No prompt or hint may contain the correct answer's words. No two options of a question may be the same.
- The learner is {{child}}: write it exactly like that. Speak to the learner as "you" / "tu".
- {{child}} and {{friend}} may each be a girl or a boy (a woman or a man). Never refer to either with he/she/him/her/his or il/elle/lui/la/le/sa/son/ses: repeat the name, or say "you" / "tu". In French never make an adjective or participle agree with them, in any line — the hero's own included. In the hero's first-person lines write, e.g., « J'ai fait une erreur » (not « Je me suis trompé »), « Aucun doute ! » (not « J'en suis sûr »), « C'est parti ! » (not « Je suis prêt »), « Ça me plaît ! » (not « Je suis content »), « J'ai trouvé ! », « Je comprends maintenant ».
"""


def _derived_rule(ctx: LessonStoryContext, plan: StoryPlan) -> str:
    distractors = (
        'Give EVERY wrong option a "distractors" entry (option letter, misconception id,'
        " targeted hint). Assign each to the objective it tests."
    )
    if ctx.is_rally:
        return (
            f'- "derived": 3 to {ctx.max_picks} entries, one per candidate quiz question you'
            f' picked, with its "ref". {distractors}\n'
            '- "questions": 0 to 2 extra questions (type "choice" or "exact_text") that mix'
            " ideas of two lessons."
        )
    if ctx.picks_from_quiz:
        return (
            f'- "derived": 0 to {ctx.max_picks} entries, one per candidate quiz question'
            ' you picked as testing THIS lesson, with its "ref" from the list above. Never'
            f" pick a question about another lesson. {distractors}\n"
            f'- "questions": {plan.questions} minus the number of "derived" entries'
            ' (never fewer than 0) extra questions (type "choice" or "exact_text"), so that'
            " every concept has a question and every objective at least 2."
        )
    return (
        f'- "derived": exactly {len(ctx.mcqs)} entries, one per quiz question above, with'
        f' the same "ref". {distractors}\n'
        f'- "questions": exactly {plan.extra_questions} extra questions (type "choice" or'
        ' "exact_text"), so that every concept has a question and every objective at least 2.'
    )


def build_story_user_message(ctx: LessonStoryContext, plan: StoryPlan | None = None) -> str:
    """The user message: the bible, the lesson (or the module), the quiz and the contract.

    The bible, the mission and the contract live here, in code, so an admin
    override of the system prompt cannot drop them.
    """
    plan = plan or plan_for(ctx)
    module_title = ctx.module_title[ctx.target]
    if ctx.is_rally:
        request = (
            f'REQUEST: write the screenplay of the RALLY, the last chapter of the module "'
            f'{module_title}": the characters meet once more for a lively challenge that mixes'
            " the module's quiz questions, and the module's mission is solved.\n"
            "STRICT CONSTRAINT: use ONLY the module's lessons and quiz below.\n"
        )
        body = f"{_recap_block(ctx)}\n\n=== QUIZ ===\n{_quiz_block(ctx)}\n\n"
    else:
        unit_title = ctx.unit_title[ctx.target]
        request = (
            f'REQUEST: write the screenplay of the chapter for unit {ctx.unit_number} — "'
            f'{unit_title}" of the module "{module_title}". It is one chapter (one episode)'
            " of the module's story, which runs through its lessons in order.\n"
            "STRICT CONSTRAINT: use ONLY the lesson and quiz below; stay on this unit.\n"
        )
        body = (
            f"=== LESSON ({ctx.target}) ===\n{_lesson_block(ctx)}\n\n"
            f"=== QUIZ ===\n{_quiz_block(ctx)}\n\n"
        )
    return f"{request}\n{_bible_block(ctx)}\n{body}=== OUTPUT ===\n{_schema(ctx, plan)}"


def build_repair_message(
    user_message: str,
    issues: list[ValidationIssue],
    previous_spine: dict[str, Any] | None,
    attempt: int,
    budget: int,
) -> str:
    """Feed the remaining errors back, with the JSON that caused them.

    The builder's paths are those of the model's JSON; the validator's are
    those of the built chapter, and the legend maps them back.
    """
    bullets = "\n".join(f"- [{i.code}] {i.path}: {i.message}" for i in issues[:40]) or (
        "- your previous response could not be read as JSON (or was cut off); "
        "answer with complete, valid JSON and keep every text short"
    )
    previous = (
        json.dumps(previous_spine, ensure_ascii=False, separators=(",", ":"))
        if previous_spine
        else "(unreadable)"
    )
    return (
        f"{user_message}\n\n"
        f"=== REPAIR (attempt {attempt} of {budget}) ===\n"
        "The chapter built from your previous JSON failed these checks. Fix every one"
        " and return the COMPLETE JSON again, same structure:\n"
        f"{bullets}\n\n"
        "How the paths map to your JSON: scenes[i].steps[j] is step j of your scene i (both"
        " from 0); chapters[ch1].scenes[sN] is your scenes[N-1]; questions[qN] is your"
        " 'derived' entry with that ref; questions[<id>] is your extra question with that"
        " id; choices[i] is option letter a, b, c, d for i = 0, 1, 2, 3; exercises[EN] is"
        " your N-th exercise; minigames[g1].rounds[i] is your mini-game round i (from 0);"
        " lesson.concepts[N] is CONCEPT N of the lesson. A [missing_translation] path is"
        " already the path of a field of YOUR JSON (e.g. derived[q2].options_home,"
        ' scenes[0].steps[2].fr): write it in that language, with "en" in English and'
        ' "fr" in French.\n\n'
        f"Your previous JSON:\n{previous}"
    )


# --------------------------------------------------------------------------
# v4 (#2680): plan, then tell
# --------------------------------------------------------------------------
#
# A chapter's screenplay is written from the module's episode plan
# (:mod:`app.ai.prompts.story_plan`), after the chapter before it, with its
# practice items (questions, paper task, game) written apart in a "pack".
# The system prompts are admin-editable settings; every JSON contract, the
# bible, the plan and the fact sheet live here, in the code-built user
# message, so an admin override cannot drop them.


def get_story_v4_system_prompt(
    kind: str,
    *,
    language: str,
    country: str,
    course: Course | None,
    course_title: str | None,
    module_title: str,
) -> str:
    """The system prompt of a v4 story call: ``"plan"``, ``"screenplay"`` or ``"pack"``.

    Fills ``{story_register}`` (:func:`audience.story_register`) instead of
    the lesson pedagogy of ``{audience_guidance}``, and no Level or Bloom.
    """
    from app.ai.prompts.audience import detect_audience, story_register

    audience = detect_audience(course)
    kids = audience.is_kids
    key = {
        "plan": PLAN_KIDS_SYSTEM_KEY if kids else PLAN_SYSTEM_KEY,
        "screenplay": SCREENPLAY_KIDS_SYSTEM_KEY if kids else SCREENPLAY_SYSTEM_KEY,
        "pack": PACK_SYSTEM_KEY,
    }[kind]
    home = "en" if language == "fr" else "fr"
    age_range = f"{audience.age_min or 6}-{audience.age_max or 12}" if kids else ""
    extra: dict[str, Any] = {
        "story_register": story_register(audience),
        "age_range": age_range,
        "audience_label": f"children aged {age_range}" if kids else "adult professionals",
        "target_language_name": LANGUAGE_NAMES["en"][language],
        "home_language_name": LANGUAGE_NAMES["en"][home],
    }
    return _apply_settings_template(
        key,
        language,
        country,
        1,
        "",
        course_title,
        None,
        module_title,
        "",
        "",
        "",
        **extra,
    )


# -- the fact sheet and the blocklist -----------------------------------------


@dataclass(frozen=True)
class FactSheet:
    """What is true in a lesson, without its order, examples, people or towns.

    IDEAS (the lesson's concepts, at most :data:`IDEA_LIMIT` characters each),
    KEY FACTS (its key points) and FIGURES (its figure refs). The lesson's
    introduction, field example, synthesis and sources are left out: they
    carried the textbook's order and its foreign characters and towns.
    """

    ideas: tuple[str, ...]
    key_facts: tuple[str, ...]
    #: ``(id, caption_en, caption_fr)`` of each figure ref, as stored.
    figures: tuple[tuple[str, str, str], ...]

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            [list(self.ideas), list(self.key_facts), [list(f) for f in self.figures]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _lesson_rows(lesson: dict[str, Any], key: str) -> list[str]:
    value = lesson.get(key)
    rows = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return [clean_text(r) for r in rows if isinstance(r, str | int | float) and clean_text(r)]


def build_fact_sheet(lesson: dict[str, Any] | None) -> FactSheet:
    lesson = lesson or {}
    ideas = tuple(truncate(idea, IDEA_LIMIT) for idea in _lesson_rows(lesson, "concepts"))
    facts = tuple(_lesson_rows(lesson, "key_points"))
    refs = lesson.get("source_image_refs")
    figures = tuple(
        (
            str(ref.get("id")),
            clean_text(ref.get("caption_en") or ref.get("caption")),
            clean_text(ref.get("caption_fr") or ref.get("caption")),
        )
        for ref in (refs if isinstance(refs, list) else [])
        if isinstance(ref, dict) and str(ref.get("id") or "").strip()
    )
    return FactSheet(ideas=ideas, key_facts=facts, figures=figures)


def fact_sheet_digest(lesson: dict[str, Any] | None) -> str:
    """The digest a chapter's freshness compares: a prose rewrite that keeps the
    ideas, key points and figures does not change it."""
    return build_fact_sheet(lesson).digest


#: Capitalised words that start sentences, never names.
_STOPWORDS = frozenset(
    [
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "du",
        "de",
        "dans",
        "quand",
        "si",
        "mais",
        "et",
        "ou",
        "en",
        "au",
        "aux",
        "ce",
        "cette",
        "ces",
        "il",
        "elle",
        "ils",
        "elles",
        "on",
        "nous",
        "vous",
        "tu",
        "je",
        "lorsque",
        "pour",
        "par",
        "avec",
        "sans",
        "sur",
        "sous",
        "chaque",
        "tout",
        "tous",
        "toutes",
        "comme",
        "car",
        "donc",
        "alors",
        "ainsi",
        "puis",
        "enfin",
        "ensuite",
        "the",
        "a",
        "an",
        "in",
        "when",
        "if",
        "but",
        "and",
        "or",
        "on",
        "at",
        "this",
        "that",
        "these",
        "those",
        "it",
        "they",
        "we",
        "you",
        "i",
        "for",
        "with",
        "without",
        "each",
        "every",
        "all",
        "as",
        "so",
        "then",
        "thus",
        "finally",
        "next",
        "leçon",
        "lecon",
        "chapitre",
        "module",
        "unité",
        "unite",
        "lesson",
        "chapter",
        "unit",
        "figure",
        "fig",
        "exemple",
        "example",
        "idée",
        "idee",
        "concept",
        "introduction",
        "synthèse",
        "synthese",
    ]
)
_CAPITALISED_RE = re.compile(r"(?<![\w'’-])([A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'’-]{2,})")
_WORDS_RE = re.compile(r"[\wÀ-ÿ'-]+")
#: What may come before a sentence's first word: spaces (no-break ones too),
#: quotes, brackets, dashes and the bullets markdown leaves.
_OPENERS = ' «"“(-—–*•+#\u00a0\u202f\t'

#: Weekdays and months, in English and French: a story's clock, never a name.
_CALENDAR = frozenset(
    [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "lundi",
        "mardi",
        "mercredi",
        "jeudi",
        "vendredi",
        "samedi",
        "dimanche",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "janvier",
        "fevrier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "aout",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "decembre",
        "décembre",
    ]
)

#: The lesson fields the fact sheet keeps (what the story must use) and those
#: that are no text.
_FACT_FIELDS = ("concepts", "key_points")
_NOT_TEXT = ("source_image_refs",)


def _texts_of(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [t for v in value for t in _texts_of(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts_of(v)]
    return []


def _words(value: Any) -> set[str]:
    return {w.casefold() for text in _texts_of(value) for w in _WORDS_RE.findall(text)}


def country_names(code: str | None) -> list[str]:
    """A country's name in English and French, from its code (or the name itself)."""
    value = str(code or "").strip()
    names = [COUNTRY_NAMES_EN.get(value.upper()), COUNTRY_NAMES_FR.get(value.upper())]
    return [n for n in names if n] or ([value] if len(value) > 3 else [])


def build_name_blocklist(
    lessons: list[dict[str, Any]],
    stems: list[str],
    bible: dict[str, Any] | None,
    *,
    country: str | None = None,
) -> list[str]:
    """Names of the lessons' own examples: capitalised words and pairs used mid-sentence.

    Read from what the fact sheet leaves out — the introduction, the field
    example, the synthesis, the sources — and from the quiz stems. Never
    blocked: a word of the fact sheet (IDEAS and KEY FACTS: the story must
    use them), a word of the bible (its country, cast, places, facts and
    missions), the name of a country of the region in either language (the
    course's own ``country`` and the bible's among them), a weekday or a
    month, a word that only ever starts a sentence, an acronym and a stoplist.
    """
    bible = bible or {}
    allowed: set[str] = set(_CALENDAR) | _words(bible)
    for lesson in lessons:
        allowed |= _words([lesson.get(key) for key in _FACT_FIELDS])
    for code in (country, bible.get("country")):
        allowed |= _words(country_names(code))
    allowed |= _words([*COUNTRY_NAMES_EN.values(), *COUNTRY_NAMES_FR.values()])
    counts: dict[str, int] = {}
    texts = [
        t
        for lesson in lessons
        for key, value in lesson.items()
        if key not in _FACT_FIELDS and key not in _NOT_TEXT
        for t in _texts_of(value)
    ] + list(stems)
    for text in texts:
        # Line by line: a bullet, a heading or a bold label starts a sentence.
        plain = "\n".join(clean_text(line) for line in text.splitlines())
        for sentence in re.split(r"(?<=[.!?…:;])\s+|\n+", plain):
            words = list(_CAPITALISED_RE.finditer(sentence))
            previous_end = -2
            previous_word = ""
            for match in words:
                word = match.group(1).strip("'’-")
                start = match.start(1)
                mid_sentence = sentence[:start].strip(_OPENERS) != ""
                folded = word.casefold()
                usable = (
                    mid_sentence
                    and folded not in _STOPWORDS
                    and folded not in allowed
                    and not word.isupper()
                    and not any(c.isdigit() for c in word)
                )
                if usable:
                    counts[word] = counts.get(word, 0) + 1
                    gap = sentence[previous_end:start]
                    if previous_word and previous_end >= 0 and gap.strip() == "":
                        pair = f"{previous_word} {word}"
                        counts[pair] = counts.get(pair, 0) + 1
                    previous_word, previous_end = word, match.end(1)
                else:
                    previous_word, previous_end = "", -2
    ranked = sorted(counts, key=lambda w: (-counts[w], w))
    return ranked[:MAX_BLOCKLIST]


# -- blocks of a v4 message ---------------------------------------------------


def _t(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return clean_text(value.get(lang) or value.get("en") or value.get("fr"))
    return clean_text(value)


def _bible_block_v4(ctx: LessonStoryContext) -> str:
    bible = ctx.bible_content
    voices = (ctx.plan or {}).get("voices") or {}
    flaw = clean_text((ctx.plan or {}).get("hero_flaw"))
    rows = []
    for member in bible.get("cast") or []:
        cid = member["id"]
        name = member["name"]
        if cid == "friend":
            name = '{friend} (write exactly "{friend}")'
        elif cid == "hero":
            name = '{child} (the learner; write exactly "{child}")'
        row = f'- "{cid}" — {name}: {member.get("about", "")}'
        voice = clean_text(voices.get(cid)) if isinstance(voices, dict) else ""
        if voice:
            row += f". In this episode: {voice}"
        if cid == "hero" and flaw:
            row += f"; flaw: {flaw}"
        rows.append(row)
    places = [
        f'- "{p["id"]}" — {p["title"]["en"]} / {p["title"]["fr"]}: {p["look"]}'
        for p in bible.get("places") or []
    ]
    facts = [f"- {f['en']}" for f in bible.get("facts") or []]
    return (
        "=== THE BIBLE (the same in every chapter) ===\n"
        'CAST — use these ids in "who" and in a scene\'s "cast":\n'
        + "\n".join(rows)
        + '\nPLACES — use these ids in a scene\'s "place":\n'
        + "\n".join(places)
        + ("\nLOCAL DETAILS you may use:\n" + "\n".join(facts) if facts else "")
    )


def _plan_props_line(plan: dict[str, Any], lang: str) -> list[str]:
    rows = []
    for prop in plan.get("props") or []:
        if isinstance(prop, dict) and prop.get("id"):
            label = _t(prop.get("label") or prop, lang)
            rows.append(
                f"{prop['id']} — {label} (planted in {prop.get('planted') or '?'}, paid off in"
                f" {prop.get('paid_off') or 'the rally'})"
            )
    return rows


def _plan_block(ctx: LessonStoryContext) -> str:
    plan = ctx.plan or {}
    lang = ctx.target
    lines = [
        "=== THE EPISODE PLAN ===",
        f"LOGLINE: {clean_text(plan.get('logline'))}",
        f"WANT: {clean_text(plan.get('want'))} · STAKES: {clean_text(plan.get('stakes'))}"
        f" · CLOCK: {clean_text(plan.get('clock'))}",
        f"RUNNING GAG: {clean_text(plan.get('running_gag'))}",
    ]
    phrases = [
        f'{c.get("who")}: "{clean_text(c.get("en"))}" / "{clean_text(c.get("fr"))}"'
        for c in plan.get("catchphrases") or []
        if isinstance(c, dict)
    ]
    if phrases:
        lines.append(
            'CATCHPHRASES (may come back word for word; mark such a line "refrain": true): '
            + " · ".join(phrases)
        )
    props = _plan_props_line(plan, lang)
    if props:
        lines.append("PROPS: " + " · ".join(props))
    lines.append("THE CHAPTERS:")
    for number, chapter in enumerate(plan.get("chapters") or [], start=1):
        title = _t(chapter.get("title"), lang)
        when = clean_text(chapter.get("when"))
        if not ctx.is_rally and number == ctx.chapter_index:
            lines.append(f"► {number}. «{title}» ({when}): YOU WRITE THIS ONE")
        else:
            lines.append(
                f"  {number}. «{title}» ({when}): {clean_text(chapter.get('goal'))} → ends on:"
                f" {clean_text(chapter.get('ends_on'))}"
            )
    rally = plan.get("rally")
    if isinstance(rally, dict):
        marker = "►" if ctx.is_rally else " "
        tail = "YOU WRITE THIS ONE" if ctx.is_rally else clean_text(rally.get("final_obstacle"))
        lines.append(f"{marker} Rally «{_t(rally.get('title'), lang)}»: {tail}")
    return "\n".join(lines)


def _beat_line(ctx: LessonStoryContext, number: int, beat: dict[str, Any]) -> str:
    lang = ctx.target
    ideas = [i for i in beat.get("ideas") or [] if isinstance(i, int)]
    label = "IDEA" if len(ideas) == 1 else "IDEAS"
    cast = ", ".join(str(c) for c in beat.get("cast") or [])
    refs = list(beat.get("questions") or [])
    then = ", ".join(refs) if refs else "no course question"
    return (
        f"BEAT {number} — {label} {', '.join(str(i) for i in ideas)} — at"
        f' "{beat.get("place")}" with {cast} — the problem: {clean_text(beat.get("problem"))}'
        f" — the discovery: «{_t(beat.get('discovery'), lang)}» — card title:"
        f" «{_t(beat.get('card_title'), lang)}» — then: {then}"
    )


def _callbacks_line(ctx: LessonStoryContext) -> str:
    plan = ctx.plan or {}
    unit = "rally" if ctx.is_rally else ctx.unit_number
    states = {p.get("id"): clean_text(p.get("state")) for p in ctx.props_now if isinstance(p, dict)}
    callbacks, plants = [], []
    for prop in plan.get("props") or []:
        if not isinstance(prop, dict) or not prop.get("id"):
            continue
        planted = str(prop.get("planted") or "")
        if planted == unit:
            plants.append(str(prop["id"]))
        elif planted and prop["id"] in states:
            callbacks.append(f"{prop['id']} (planted in {planted}; now: {states[prop['id']]})")
    parts = []
    if callbacks:
        parts.append("CALLBACKS to use: " + "; ".join(callbacks) + ".")
    if plants:
        parts.append("PLANT for later: " + ", ".join(plants) + ".")
    return " ".join(parts)


def _closes_the_episode(ctx: LessonStoryContext) -> bool:
    """The last lesson chapter of a module without a rally: it resolves the episode."""
    return (
        not ctx.is_rally
        and ctx.plan_entry is not None
        and not (ctx.plan or {}).get("rally")
        and ctx.chapter_index >= ctx.chapter_count
    )


def _this_chapter_block(ctx: LessonStoryContext, pack: dict[str, Any]) -> str:
    entry = ctx.plan_entry or {}
    lines = ["=== THIS CHAPTER ==="]
    for label, key in (
        ("WHEN", "when"),
        ("OPENS ON", "opens_on"),
        ("GOAL", "goal"),
        ("OBSTACLE", "obstacle"),
    ):
        lines.append(f"{label}: {clean_text(entry.get(key))}")
    for number, beat in enumerate(ctx.beats, start=1):
        lines.append(_beat_line(ctx, number, beat))
    lines.append(f"TURN: {clean_text(entry.get('turn'))}")
    lines.append(f"ENDS ON: {clean_text(entry.get('ends_on'))}")
    if _closes_the_episode(ctx):
        lines.append(
            "THE LAST CHAPTER: this module has no rally, so this chapter is the climax. The"
            " TURN beats the episode's obstacle for good and the WANT is won on stage;"
            " {child}'s flaw meets its last test; every prop planted earlier is paid off."
            " ENDS ON is the episode's warm last image, a callback to the running gag."
        )
    callbacks = _callbacks_line(ctx)
    if callbacks:
        lines.append(callbacks)
    game = clean_text(entry.get("game"))
    lines.append(f'GAME: "{game}"' if game and ctx.has_game else "GAME: none in this chapter.")
    lines.append(f"PAPER TASK: «{clean_text(entry.get('paper_task'))}» (ref E1)")
    return "\n".join(lines)


def _rally_block(ctx: LessonStoryContext) -> str:
    entry = ctx.plan_entry or {}
    lines = ["=== THE RALLY ==="]
    for label, key in (
        ("WHEN", "when"),
        ("OPENS ON", "opens_on"),
        ("FINAL OBSTACLE", "final_obstacle"),
    ):
        lines.append(f"{label}: {clean_text(entry.get(key))}")
    lines.append("STEPS:")
    for step in entry.get("steps") or []:
        if isinstance(step, dict):
            refs = ", ".join(step.get("questions") or []) or "no course question"
            lines.append(
                f"- from {step.get('from_unit')}: {clean_text(step.get('uses'))} — then {refs}"
            )
    lines.append("PAYOFFS: " + (", ".join(str(p) for p in entry.get("payoffs") or []) or "none"))
    lines.append(f"RESOLUTION: {clean_text(entry.get('resolution'))}")
    lines.append(f"LAST IMAGE: {clean_text(entry.get('last_image'))}")
    callbacks = _callbacks_line(ctx)
    if callbacks:
        lines.append(callbacks)
    game = clean_text(entry.get("game"))
    lines.append(f'GAME: "{game}"' if game and ctx.has_game else "GAME: none in the rally.")
    lines.append(f"PAPER TASK: «{clean_text(entry.get('paper_task'))}» (ref E1)")
    return "\n".join(lines)


def _story_so_far_block(ctx: LessonStoryContext) -> str:
    lines = ["=== STORY SO FAR ==="]
    if not ctx.story_so_far:
        lines.append("This is the first chapter: the story starts here.")
    for number, chapter in enumerate(ctx.story_so_far, start=1):
        recap = clean_text(chapter.get("recap")) or "(not told yet)"
        lines.append(f"Chapter {number} «{_t(chapter.get('title'), ctx.target)}»: {recap}")
    if ctx.props_now:
        lines.append(
            "PROPS NOW: "
            + "; ".join(
                f"{p.get('id')} — {clean_text(p.get('state'))}"
                for p in ctx.props_now
                if isinstance(p, dict)
            )
        )
    return "\n".join(lines)


def _scene_lines(scene: dict[str, Any]) -> str:
    lines = [f"[{scene.get('place') or ''}]"]
    lines += [str(line) for line in (scene.get("lines") or [])[:LAST_SCENE_LINES]]
    return "\n".join(lines)


def _last_scene_block(ctx: LessonStoryContext) -> str:
    if ctx.previous_missing:
        return (
            "=== WHERE THE LAST CHAPTER STOPPED ===\n"
            "The previous chapter is not written yet: open on OPENS ON."
        )
    if not ctx.previous_scene:
        return ""
    return (
        "=== WHERE THE LAST CHAPTER STOPPED (already written; never repeat these lines) ===\n"
        + _scene_lines(ctx.previous_scene)
        + "\nYour first scene picks up from here."
    )


def _next_scene_block(ctx: LessonStoryContext) -> str:
    if not ctx.next_scene:
        return ""
    return (
        "=== WHERE THE NEXT CHAPTER STARTS (already written; your ending must lead into it) ===\n"
        + _scene_lines(ctx.next_scene)
    )


def _figure_lines(ctx: LessonStoryContext) -> str:
    refs = ctx.figure_refs()
    if not refs:
        return "FIGURES: none."
    rows = ["FIGURES you may show:"]
    for number, ref in enumerate(refs, start=1):
        kind = clean_text(ref.get("figure_kind") or ref.get("image_type")) or "figure"
        en = clean_text(ref.get("caption_en") or ref.get("caption")) or ref.get("figure_number")
        fr = clean_text(ref.get("caption_fr") or ref.get("caption")) or en
        rows.append(f"FIGURE {number} [{kind}]: {en} | {fr}")
    return "\n".join(rows)


def _fact_sheet_block(ctx: LessonStoryContext) -> str:
    sheet = build_fact_sheet(ctx.lesson)
    language = LANGUAGE_NAMES["en"][ctx.target]
    lines = [f"=== FACT SHEET — lesson {ctx.unit_number} ({language}): what is true ==="]
    lines += [f"IDEA {n}: {idea}" for n, idea in enumerate(sheet.ideas, start=1)]
    if sheet.key_facts:
        lines.append("KEY FACTS:")
        lines += [f"{n}. {fact}" for n, fact in enumerate(sheet.key_facts, start=1)]
    lines.append(_figure_lines(ctx))
    if ctx.blocklist:
        lines.append(
            "Never use these names, which belong to the lesson's own examples: "
            + ", ".join(ctx.blocklist)
            + "."
        )
    return "\n".join(lines)


def _episode_ideas_block(ctx: LessonStoryContext) -> str:
    lines = ["=== IDEAS OF THE EPISODE (the only facts you may use) ==="]
    for chapter in ctx.episode_ideas:
        lines.append(f"Chapter «{_t(chapter.get('title'), ctx.target)}» ({chapter.get('unit')}):")
        for card in chapter.get("cards") or []:
            rows = " | ".join(clean_text(r) for r in card.get("rows") or [])
            lines.append(f"  [card «{clean_text(card.get('title'))}»: {rows}]")
    if ctx.blocklist:
        lines.append("Never use these names: " + ", ".join(ctx.blocklist) + ".")
    return "\n".join(lines)


def _pack_items(pack: dict[str, Any]) -> tuple[dict[str, dict], list[dict]]:
    derived = {str(d.get("ref")): d for d in (pack.get("derived") or []) if isinstance(d, dict)}
    own = [q for q in (pack.get("questions") or []) if isinstance(q, dict)]
    return derived, own


def _questions_block_v4(ctx: LessonStoryContext, pack: dict[str, Any]) -> str:
    lang = ctx.target
    derived, own = _pack_items(pack)
    lines = ["=== THE QUESTIONS (fixed: the app shows them word for word) ==="]
    assigned = set(ctx.assigned_refs)
    for mcq in ctx.mcqs:
        if mcq.ref not in assigned:
            continue
        idea = (derived.get(mcq.ref) or {}).get("idea")
        tests = f" tests IDEA {idea}" if isinstance(idea, int) and not ctx.is_rally else ""
        lines.append(
            f"[{mcq.ref}]{tests}: «{mcq.stem}». Correct answer: «{mcq.correct_text}». Your"
            " lead-in never says it."
        )
    for number, question in enumerate(own, start=1):
        qid = clean_text(question.get("id")) or f"x{number}"
        idea = question.get("idea")
        tests = f" tests IDEA {idea}" if isinstance(idea, int) and not ctx.is_rally else ""
        answer = question.get("answer")
        for choice in question.get("choices") or []:
            if isinstance(choice, dict) and choice.get("id") == answer:
                answer = choice.get(lang)
        lines.append(
            f"[{qid}]{tests}: «{_t(question.get('prompt'), lang)}». Correct answer:"
            f" «{clean_text(answer)}»."
        )
    for number, exercise in enumerate(pack.get("exercises") or [], start=1):
        if isinstance(exercise, dict):
            lines.append(f"[E{number}] paper task: «{_t(exercise.get('prompt'), lang)}»")
    game = pack.get("minigame")
    if ctx.has_game and isinstance(game, dict):
        lines.append(f"[game] «{_t(game.get('title'), lang)}»")
    return "\n".join(lines)


def _props_block(ctx: LessonStoryContext) -> str:
    """PROPS ALREADY IN THE STORY: the plan's and earlier chapters', to be reused."""
    if not ctx.known_props:
        return ""
    rows = ["PROPS ALREADY IN THE STORY — reuse these ids for the same things:"]
    for prop in ctx.known_props:
        label = prop.get("label") or {}
        held = f", held by {prop['holder']}" if prop.get("holder") else ""
        origin = prop.get("origin") or "module"
        where = "module prop" if origin == "module" else f"chapter {origin}"
        rows.append(
            f'- "{prop["id"]}": {label.get("en")} / {label.get("fr")} ({prop.get("kind")}{held})'
            f" — {where}"
        )
    return "\n".join(rows)


_PROPS_RULES = """THE PROPS — the cartoon SHOWS what its characters talk about:
- Every concrete thing a line names, points at or handles is a PROP the learner sees on stage: an object, a food, a tool, an animal, a plant or a part of one, a stone, a body part, a feature of the place (a tree, a river, a well). Ideas (life, energy, a rule, a number) are not props: they go on a concept card. People are never props: they are the cast.
- Declare each prop ONCE in "props", with:
  - "id": snake_case, unique ("snail", "nere_tree").
  - "label": the name tag the learner reads, {"en": ..., "fr": ...}: a short noun with its article, at most 4 words and 40 characters ("a snail" / "un escargot", "the jar" / "le bocal"). It names what the thing IS, never what it looks like or holds: "le bocal", never "le bocal fermé avec quelque chose de gris"; a line of the story says the rest.
  - "query": 2 to 5 English words naming exactly what a photo must show, as a picture search needs it: "garden snail", "baobab tree", "onion skin cells microscope" — never just "tree" or "cells". No person, no brand, no written text.
  - "kind": "figure" with "figure": N when FIGURE N above shows this thing; "real" when seeing the real thing teaches something (an organism, a specimen, a rock, an instrument of the lesson, a natural process); "sticker" for an everyday thing the story only handles (a basket, a cup, a bench).
  - "educational": true for "figure" and "real", false for "sticker".
  - "emoji": one emoji that looks like it, or leave it out.
  - "at": "ground", "table", "held" (then "holder": the cast id holding it), "sky", or "back" (big scenery behind the cast: a tree, a hut, a hill).
  - "size": "s" (fits in a hand), "m" (up to a child's height) or "l" (taller than a person, only with "at": "back").
- A scene lists in "props" the props present there, at most 5, and only things that belong at its place: no mango tree in the classroom unless a line brings one in.
- A "say", "narrate" or "concept" step that names or handles a prop lists its id in "props" (at most 2): the prop pops up and bounces while the line plays. A line about the snail without "props": ["snail"] shows nothing.
- Right after the line that first points at an educational prop, close up on it: {"type": "show", "prop": "snail"}. One close-up per prop, at most 2 per scene, never on a sticker. Name a prop for the first time before a question's lead-in, never in the lead-in itself nor in the chapter's last line: a close-up never comes between a lead-in and its "ask", nor after the last line.
- Reuse the ids of PROPS ALREADY IN THE STORY for the same thing; never declare them again. At most 12 new props in this chapter, and every prop you declare is named by a line."""

_RALLY_PROPS_RULE = (
    "\n- In the rally, reuse the props already in the story; declare a new one only for"
    " what the celebration brings."
)

_STORY_EXAMPLE = """{
 "props": [{"id": "snail", "label": {"en": "a snail", "fr": "un escargot"}, "query": "garden snail", "kind": "real", "educational": true, "emoji": "🐌", "at": "ground", "size": "s"},
           {"id": "basket", "label": {"en": "Grandma's basket", "fr": "le panier de Grand-mère"}, "query": "woven straw basket", "kind": "sticker", "educational": false, "emoji": "🧺", "at": "held", "holder": "family", "size": "s"}],
 "scenes": [
  {"place": "a place id", "cast": ["hero", "friend", "family"], "props": ["snail", "basket"],
   "steps": [
    {"type": "narrate", "en": "a vivid storyteller line", "fr": "...", "props": ["basket"]},__FIGURE__
    {"type": "say", "who": "friend", "mood": "surprised", "en": "the words only", "fr": "...", "props": ["snail"]},
    {"type": "show", "prop": "snail"},
    {"type": "say", "who": "hero", "mood": "think", "en": "...", "fr": "..."},
    {"type": "say", "who": "family", "mood": "talk", "en": "a question back, not an explanation", "fr": "..."},
    {"type": "say", "who": "hero", "mood": "surprised", "en": "the discovery, in the hero's words", "fr": "..."},
    {"type": "concept", "teaches": __TEACHES__, "title": {"en": "__CARD__", "fr": "..."}, "en": ["the proper word for it", "the rule the scene did not say"], "fr": ["...", "..."]},
    {"type": "say", "who": "friend", "mood": "talk", "en": "lead-in: the characters need {child} to decide", "fr": "..."},
    {"type": "ask", "ref": "__REF__"},
    {"type": "say", "who": "hero", "mood": "happy", "en": "reaction: the story moves on", "fr": "..."}
   ]}
 ],
 "recap": "English, 2 or 3 sentences: what happened in this chapter, for the writer of the next one",
 "props_now": [{"id": "dry_leaf", "state": "where it is now and what is still unknown"}],
 "facts": [{"en": "a real local detail a scene uses", "fr": "...", "source": "where it comes from"}],
 "__complete": true
}"""


def _story_output(ctx: LessonStoryContext, pack: dict[str, Any]) -> str:
    derived, own = _pack_items(pack)
    refs = [m.ref for m in ctx.mcqs if m.ref in set(ctx.assigned_refs)]
    refs += [clean_text(q.get("id")) or f"x{n}" for n, q in enumerate(own, start=1)]
    example = (
        _STORY_EXAMPLE.replace("__REF__", refs[0] if refs else "q1")
        .replace("__TEACHES__", "[]" if ctx.is_rally else "[1]")
        .replace("__CARD__", "the final deduction" if ctx.is_rally else "the beat's card title")
        .replace(
            "__FIGURE__",
            '\n    {"type": "show", "figure": 1},'
            if ctx.figure_refs() and not ctx.is_rally
            else "",
        )
    )
    moods = ", ".join(MOODS)
    en_limit, fr_limit = STORY_LINE_LIMITS["en"], STORY_LINE_LIMITS["fr"]
    beats = len(ctx.beats)
    ideas = len(build_fact_sheet(ctx.lesson).ideas)
    show_rule = (
        '- "show": {"type": "show", "prop": id} for the close-up of an educational prop (see'
        ' THE PROPS); {"type": "show", "figure": N} for a FIGURE that no prop stands for (a'
        " chart, a table), only when a character looks at or holds it up."
    )
    if _is_maths(ctx):
        visuals = "; ".join(
            f'"{name}" with params {{'
            + ", ".join(
                f'"{param}": {desc}' + ("" if required else " (optional)")
                for param, (required, desc) in params.items()
            )
            + "}"
            for name, params in DRAWN_VISUALS.items()
        )
        show_rule += (
            ' Or — only when the lesson\'s numbers fit one — a drawn visual, {"type":'
            f' "show", "visual": ..., "params": {{...}}}}, one of: {visuals}. No other'
            " visual exists: the player cannot draw it."
        )
    if ctx.is_rally:
        scene_rules = (
            "- 2 or 3 scenes, at the places the plan's steps need, 2 or 3 characters each,"
            " the hero in every scene.\n"
            '- 0 or 1 concept card, only for the final deduction ("teaches": []), never a'
            " recap card.\n"
            "- Ask every question listed above exactly once, by its ref, each as one step of"
            ' the solution. At most 2 "ask" steps in a row. A "say" lead-in comes right'
            ' before each run, and a "say" or "narrate" reaction right after it.\n'
            f'- Story lines ("say" + "narrate"): 14 to 28 in all. At least {3} between two'
            " teaching moments.\n"
            "- The first scene continues WHERE THE LAST CHAPTER STOPPED. The last step is a"
            ' "say" or "narrate" line that lands LAST IMAGE.\n'
        )
    else:
        lines_floor = max(14, 6 * max(beats, 1))
        scene_rules = (
            f"- {max(2, beats)} scenes, one per beat of the plan, in the plan's order (a"
            " chapter of one beat tells it in 2), each at the beat's place with the beat's"
            " cast: 2 or 3 characters, the hero in every scene.\n"
            '- One concept card per beat, right after its discovery: "teaches" lists that'
            " beat's IDEA numbers, and \"title\" is the beat's card title. Every IDEA from 1"
            f" to {ideas} is on a card. Each card has 2 to 4 rows, the same number in"
            ' "en" and "fr"; no row repeats a line of the dialogue.\n'
            "- Ask every question listed above exactly once, by its ref, in the scene of the"
            ' IDEA it tests, after that IDEA\'s card. At most 2 "ask" steps in a row. A "say"'
            ' lead-in comes right before each run, and a "say" or "narrate" reaction right'
            " after it.\n"
            f'- Story lines ("say" + "narrate"): {lines_floor} to {MAX_STORY_LINES} in all. At'
            " least 3 between two teaching moments (a card with its questions, a figure, the"
            " game, the paper task). At least 3 steps in 5 are story lines.\n"
            "- The first scene continues WHERE THE LAST CHAPTER STOPPED (chapter 1: OPENS"
            ' ON). The last step is a "say" or "narrate" line that lands ENDS ON'
            + (
                ": this is the last chapter of the episode, so ENDS ON is its warm last"
                " image, never a cliffhanger.\n"
                if _closes_the_episode(ctx)
                else ".\n"
            )
        )
    game_rule = (
        '- {"type": "game"}: once, where the plot turns into a challenge.'
        if ctx.has_game
        else '- No "game" step: this chapter has no game.'
    )
    return (
        "=== OUTPUT ===\n"
        'Return ONE JSON object with exactly these keys. Every {"en": ..., "fr": ...} object'
        ' has English in "en" and French in "fr".\n'
        f"{example}\n"
        "(The example scene has 6 story lines to 1 card and 1 question"
        + (
            "; its figure comes early, 4 story lines before the card."
            if ctx.figure_refs() and not ctx.is_rally
            else "."
        )
        + ")\n\n"
        "THE SCREENPLAY:\n"
        f"{scene_rules}"
        f'- "say": "who" is a cast id; "mood" is one of {moods}. The line is ONLY the words'
        ' spoken: never "Name:", "Name says" or "X dit :" in front, and no quotation marks'
        " around it.\n"
        '- "narrate": the storyteller, in the present tense and the third person.\n'
        f"{show_rule}\n"
        f"{game_rule}\n"
        '- Margo speaks only in a scene whose "cast" lists "margo": 2 or 3 characters with'
        " her, the hero among them. She never joins a scene of 3 others.\n"
        '- {"type": "photo", "ref": "E1"}: once, when a character hands over the paper task.'
        " Neither the game nor the paper task is among the last 3 steps.\n"
        "- No line said in an earlier chapter comes back, except a catchphrase marked"
        ' "refrain": true.\n'
        f"- Story lines are at most {en_limit} characters in English and {fr_limit} in"
        " French.\n"
        '- "props_now": every prop of the plan that has appeared so far, with its state at'
        " the end of this chapter.\n"
        "- {child} and {friend} may each be a girl or a boy (a woman or a man): never he/she"
        " or il/elle; in French no adjective or participle agrees with them.\n\n"
        + _PROPS_RULES
        + (_RALLY_PROPS_RULE if ctx.is_rally else "")
    )


def _is_maths(ctx: LessonStoryContext) -> bool:
    title = " ".join(
        str(v) for v in [*ctx.course_title.values(), *ctx.module_title.values()]
    ).lower()
    return bool(re.search(r"math|arithm|calcul|algèbre|algebra|géométr|geometr|nombre", title))


def build_chapter_story_message(ctx: LessonStoryContext, pack: dict[str, Any]) -> str:
    """The user message of a lesson chapter's story call (v4).

    Only what this chapter's writer needs and nothing the next one could not
    see: the bible, the plan (one line per chapter, ► on this one), this
    chapter's entry, the story so far, the previous chapter's real last
    scene, the fact sheet, the pack's questions and the contract.
    """
    plan = ctx.plan or {}
    title = _t((ctx.plan_entry or {}).get("title"), ctx.target)
    request = (
        f"REQUEST: write chapter {ctx.chapter_index} of {ctx.chapter_count} of the episode"
        f" «{_t(plan.get('episode_title'), ctx.target)}»: «{title}». It brings the IDEAS of"
        f" lesson {ctx.unit_number} into the story, through the plot below. The chapters"
        " before and after yours are written from the same plan; yours must join them."
    )
    blocks = [
        request,
        _bible_block_v4(ctx),
        _plan_block(ctx),
        _this_chapter_block(ctx, pack),
        _story_so_far_block(ctx),
        _last_scene_block(ctx),
        _next_scene_block(ctx),
        _props_block(ctx),
        _fact_sheet_block(ctx),
        _questions_block_v4(ctx, pack),
        _story_output(ctx, pack),
    ]
    return "\n\n".join(b for b in blocks if b)


def build_rally_story_message(ctx: LessonStoryContext, pack: dict[str, Any]) -> str:
    """The user message of the rally's story call: the climax of the episode."""
    plan = ctx.plan or {}
    payoffs = ", ".join(str(p) for p in (ctx.plan_entry or {}).get("payoffs") or []) or "the props"
    request = (
        "REQUEST: write the RALLY, the last chapter and the climax of"
        f" «{_t(plan.get('episode_title'), ctx.target)}»:"
        f" «{_t((ctx.plan_entry or {}).get('title'), ctx.target)}». The final obstacle"
        " arrives. {child} beats it step by step, each step using a discovery from an"
        " earlier chapter. That is where the questions come: each question is one step of"
        " the solution, set up by a character and paid off by the next line. Pay off"
        f" {payoffs}, and give the flaw of {{child}} its last test. The game (if it is"
        " here) and the paper task come before the final step, as the last practice. The"
        " win is shown on stage (what happens, who reacts), never a recap of what was"
        " learned, never a list. End on the plan's LAST IMAGE, a warm callback to the"
        " running gag."
    )
    blocks = [
        request,
        _bible_block_v4(ctx),
        _plan_block(ctx),
        _rally_block(ctx),
        _story_so_far_block(ctx),
        _last_scene_block(ctx),
        _props_block(ctx),
        _episode_ideas_block(ctx),
        _questions_block_v4(ctx, pack),
        _story_output(ctx, pack),
    ]
    return "\n\n".join(b for b in blocks if b)


# -- the practice pack ---------------------------------------------------------


def pack_counts(ctx: LessonStoryContext) -> dict[str, int]:
    """How many items a pack writes: objectives, own questions, exercises."""
    ideas = len(build_fact_sheet(ctx.lesson).ideas)
    derived = len(ctx.assigned_refs)
    if ctx.is_rally:
        return {"objectives": 1, "own": 0 if derived >= 3 else 2, "exercises": 1}
    objectives = 2 if ideas >= 4 else 1
    covered: set[int] = set()
    # The IDEAS without a course question get one of their own first.
    for beat in ctx.beats:
        if beat.get("questions"):
            covered |= {i for i in beat.get("ideas") or [] if isinstance(i, int)}
    uncovered = [n for n in range(1, ideas + 1) if n not in covered]
    own = max(len(uncovered), 2 - derived, 0)
    own = min(own, max(5 - derived, 0))
    return {"objectives": objectives, "own": own, "exercises": 1}


def build_pack_message(ctx: LessonStoryContext) -> str:
    """The user message of a practice pack: the questions, paper task and game of a chapter."""
    plan = ctx.plan or {}
    entry = ctx.plan_entry or {}
    lang = ctx.target
    home = LANGUAGE_NAMES["en"][ctx.home]
    counts = pack_counts(ctx)
    title = _t(entry.get("title"), lang)
    if ctx.is_rally:
        request = (
            f"REQUEST: write the practice items of the RALLY «{title}» of the episode"
            f" «{_t(plan.get('episode_title'), lang)}», which mixes the module's lessons."
            " You do not write the story; the screenwriter will set your questions up in it."
        )
        facts = _episode_ideas_block(ctx)
        beats = ["STEPS:"] + [
            f"- from {s.get('from_unit')}: {clean_text(s.get('uses'))} · course questions:"
            f" {', '.join(s.get('questions') or []) or 'none'}"
            for s in entry.get("steps") or []
            if isinstance(s, dict)
        ]
    else:
        request = (
            f"REQUEST: write the practice items of chapter {ctx.chapter_index} «{title}»"
            f" (lesson {ctx.unit_number}) of the episode «{_t(plan.get('episode_title'), lang)}»."
            " You do not write the story; the screenwriter will set your questions up in it."
        )
        sheet = build_fact_sheet(ctx.lesson)
        facts = "\n".join(
            [f"=== FACT SHEET — lesson {ctx.unit_number} ==="]
            + [f"IDEA {n}: {idea}" for n, idea in enumerate(sheet.ideas, start=1)]
            + (["KEY FACTS:"] if sheet.key_facts else [])
            + [f"{n}. {fact}" for n, fact in enumerate(sheet.key_facts, start=1)]
        )
        beats = ["BEATS:"]
        for number, beat in enumerate(ctx.beats, start=1):
            ideas = [str(i) for i in beat.get("ideas") or [] if isinstance(i, int)]
            label = "IDEA" if len(ideas) == 1 else "IDEAS"
            refs = ", ".join(beat.get("questions") or []) or "none"
            beats.append(
                f"- {number}: {label} {', '.join(ideas)} · {clean_text(beat.get('problem'))}"
                f" · course questions: {refs}"
            )
    places = sorted({str(b.get("place")) for b in ctx.beats if b.get("place")})
    props = [str(p.get("id")) for p in plan.get("props") or [] if isinstance(p, dict)]
    game = clean_text(entry.get("game"))
    lines = [
        request,
        facts,
        "=== THE EPISODE ===",
        f"LOGLINE: {clean_text(plan.get('logline'))} · THIS CHAPTER'S GOAL:"
        f" {clean_text(entry.get('goal') or entry.get('final_obstacle'))}",
        *beats,
        "PROPS AND PLACES you may use in your questions: "
        + (", ".join(props + places) or "the story's own"),
        f"PAPER TASK the plot needs: «{clean_text(entry.get('paper_task'))}»",
        f'GAME: yes, "{game}"' if ctx.has_game and game else "GAME: no",
        f"=== COURSE QUESTIONS ASSIGNED TO THIS CHAPTER (fixed: translate them faithfully"
        f" into {home}; explain each wrong option; never change them) ===",
    ]
    assigned = set(ctx.assigned_refs)
    for mcq in ctx.mcqs:
        if mcq.ref not in assigned:
            continue
        lines.append(f"[{mcq.ref}] {mcq.stem}")
        for index, option in enumerate(mcq.options):
            mark = "  <- correct" if index == mcq.correct_index else ""
            lines.append(f"  {CHOICE_IDS[index]}) {option}{mark}")
            known = (
                mcq.option_misconceptions[index] if index < len(mcq.option_misconceptions) else None
            )
            if known:
                lines.append(f"     why it is wrong (from the course): {known}")
        if mcq.explanation:
            lines.append(f"  explanation: {mcq.explanation}")
    if not assigned:
        lines.append("(none)")
    own_rule = (
        f"- questions: exactly {counts['own']} of your own (choice or exact_text), each"
        " mixing two lessons."
        if ctx.is_rally
        else f"- questions: exactly {counts['own']} of your own (choice or exact_text), first"
        " for the IDEAS without a course question, so every IDEA has at least one question"
        " and the chapter has 2 to 5 in all."
    )
    lines += [
        "=== OUTPUT ===",
        'Return ONE JSON object with exactly these keys. Every {"en": ..., "fr": ...} object'
        ' has English in "en" and French in "fr". Each derived entry and each question adds'
        ' "idea": the IDEA number it tests' + (" (0 in the rally)." if ctx.is_rally else "."),
        _PACK_EXAMPLE,
        "COUNTS:",
        f"- objectives: exactly {counts['objectives']}, ids o1..o{counts['objectives']}.",
        "- derived: exactly one per course question above, with its ref.",
        own_rule,
        "- exercises: exactly 1, the paper task" + (" (a short recap)." if ctx.is_rally else "."),
        (
            "- minigame: 2 or 3 rounds of 4-5 items, at least 2 correct and 1 wrong item per round."
            if ctx.has_game
            else "- minigame: leave the key out."
        ),
        '- Every misconception id you use is in "misconceptions"; never one on a correct'
        ' option. Give EVERY wrong option a "distractors" entry (option letter,'
        " misconception id, targeted hint).",
        "- No prompt or hint contains the correct answer's words. No two options of a"
        " question are the same.",
        "- The learner is {child} and the friend {friend}: write them exactly so. Speak to the"
        ' learner as "you" / "tu".',
    ]
    return "\n".join(lines)


_PACK_EXAMPLE = """{"objectives": [{"id": "o1", "en": "learning objective", "fr": "objectif"}],
 "misconceptions": [{"id": "m_slug", "en": "Thinks that ...", "fr": "Pense que ..."}],
 "derived": [{"ref": "q4", "idea": 1, "objective": "o1", "prompt_home": "the question in the home language", "options_home": ["option a", "option b", "..."], "explanation_home": "...", "hint": {"en": "points back to the story moment", "fr": "..."}, "distractors": [{"option": "a", "misconception": "m_slug", "hint": {"en": "aimed at this mistake", "fr": "..."}}]}],
 "questions": [{"id": "x1", "idea": 3, "type": "choice", "objective": "o1", "prompt": {"en": "...", "fr": "..."}, "choices": [{"id": "a", "en": "...", "fr": "..."}, {"id": "b", "en": "...", "fr": "...", "misconception": "m_slug"}], "answer": "a", "hints": [{"en": "...", "fr": "..."}], "traps": [{"answer": "b", "misconception": "m_slug", "hint": {"en": "...", "fr": "..."}}], "explanation": {"en": "...", "fr": "..."}}],
 "exercises": [{"objective": "o1", "prompt": {"en": "a short task done on paper", "fr": "..."}, "working": {"en": ["model answer, line by line"], "fr": ["..."]}, "mark_scheme": {"en": "what earns the mark", "fr": "..."}}],
 "minigame": {"title": {"en": "...", "fr": "..."}, "instruction": {"en": "...", "fr": "..."}, "hint_after_wrong": {"en": "...", "fr": "..."}, "rounds": [{"prompt": {"en": "Catch the ...", "fr": "Attrape ..."}, "items": [{"label": {"en": "a true statement", "fr": "..."}, "correct": true}, {"label": {"en": "a tempting wrong idea", "fr": "..."}, "correct": false, "trap": "m_slug"}]}]},
 "__complete": true}"""


# -- repairs ---------------------------------------------------------------------


def _bullets(issues: list[ValidationIssue]) -> str:
    return "\n".join(f"- [{i.code}] {i.path}: {i.message}" for i in issues[:40]) or (
        "- your previous response could not be read as JSON (or was cut off); "
        "answer with complete, valid JSON and keep every text short"
    )


def _previous(previous: dict[str, Any] | None) -> str:
    return (
        json.dumps(previous, ensure_ascii=False, separators=(",", ":"))
        if previous
        else "(unreadable)"
    )


def build_story_repair_message(
    user_message: str,
    issues: list[ValidationIssue],
    previous: dict[str, Any] | None,
    attempt: int,
    budget: int,
) -> str:
    """A story repair: the scenes only, with the story checks' own fix texts."""
    return (
        f"{user_message}\n\n"
        f"=== REPAIR (attempt {attempt} of {budget}) ===\n"
        "The chapter built from your screenplay failed these checks. Fix every one and"
        " return the COMPLETE JSON again (props, scenes, recap, props_now, facts), same"
        " structure:\n"
        f"{_bullets(issues)}\n\n"
        "Paths: scenes[i].steps[j] is step j of your scene i (both from 0); lesson.concepts[N]"
        " is IDEA N. Prop paths: props[i].label.fr, props[i].query, scenes[i].props,"
        " scenes[i].steps[j].props. Prop issues are settled by the builder; they are listed"
        " only because the chapter needs a repair for another reason.\n\n"
        f"Your previous JSON:\n{_previous(previous)}"
    )


#: A pack issue is one on these paths (the story checks never are).
PACK_PATH_RE = re.compile(
    r"^(?:objectives|misconceptions|derived|questions|exercises|minigames?)\b"
)


def build_pack_repair_message(
    user_message: str,
    issues: list[ValidationIssue],
    previous: dict[str, Any] | None,
    attempt: int,
    budget: int,
) -> str:
    """A pack repair: the practice items only."""
    return (
        f"{user_message}\n\n"
        f"=== REPAIR (attempt {attempt} of {budget}) ===\n"
        "The practice items built from your previous JSON failed these checks. Fix every"
        " one and return the COMPLETE practice-items JSON again, same structure:\n"
        f"{_bullets(issues)}\n\n"
        "How the paths map to your JSON: questions[qN] is your 'derived' entry with that"
        " ref; questions[<id>] is your own question with that id; choices[i] is option"
        " letter a, b, c, d for i = 0, 1, 2, 3; exercises[EN] is your N-th exercise;"
        " minigames[g1].rounds[i] is your mini-game round i (from 0). A"
        " [missing_translation] path is already the path of a field of YOUR JSON (e.g."
        ' derived[q2].options_home): write it in that language, with "en" in English and'
        ' "fr" in French.\n\n'
        f"Your previous JSON:\n{_previous(previous)}"
    )
