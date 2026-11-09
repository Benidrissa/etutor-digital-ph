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

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.ai.prompts.lesson import _apply_settings_template
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
)

if TYPE_CHECKING:
    from app.domain.models.course import Course

STORY_SYSTEM_KEY = "ai-prompt-story-system"
STORY_KIDS_SYSTEM_KEY = "ai-prompt-story-kids-system"

LANGUAGE_NAMES = {
    "en": {"en": "English", "fr": "French"},
    "fr": {"en": "anglais", "fr": "français"},
}


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
