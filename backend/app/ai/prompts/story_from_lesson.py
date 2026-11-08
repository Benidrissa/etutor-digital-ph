"""Prompts for a lesson's story mode.

The model is asked for a *spine* only — pedagogy and translations — and the
application assembles the ``story-course/1`` week around it
(:mod:`app.domain.services.story_repair`). Keeping the split explicit in the
prompt is what makes zero validator errors structural rather than hoped for.

The system prompt (register, the learner-as-hero rules, hard rules) is an
admin-editable platform setting, like every other content prompt. The JSON
contract lives in the user message, which is code: the parser depends on it,
so an admin override of the system prompt must not be able to drop it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.ai.prompts.lesson import _apply_settings_template
from app.api.v1.schemas.story_course import PLACES, ValidationIssue
from app.domain.services.story_repair import (
    CHOICE_IDS,
    MAX_OBJECTIVES,
    MAX_PICKED_MCQS,
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
    """How much the model must write, derived from the unit's quiz."""

    objectives: int
    extra_questions: int

    @property
    def exercises(self) -> int:
        return self.objectives


def plan_for(ctx: LessonStoryContext) -> StoryPlan:
    """Enough objectives to be meaningful, each with 2 questions (C.5).

    With a covering quiz the number of derived questions is the model's pick,
    so ``extra_questions`` is the total to reach: 2 per objective, from which
    the model subtracts the candidates it picked.
    """
    derived = len(ctx.mcqs)
    if derived == 0 or ctx.picks_from_quiz:
        return StoryPlan(objectives=2, extra_questions=4)
    objectives = max(1, min(MAX_OBJECTIVES, derived // 2))
    return StoryPlan(objectives=objectives, extra_questions=max(0, 2 * objectives - derived))


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
    return "\n\n".join(parts)


def _quiz_block(ctx: LessonStoryContext) -> str:
    if not ctx.mcqs:
        return (
            "QUIZ: this unit has no quiz yet. Write every question yourself, as extra"
            ' questions, and leave "derived" as an empty list.'
        )
    if ctx.picks_from_quiz:
        lines = [
            f"CANDIDATE QUIZ QUESTIONS from the quiz of unit {ctx.quiz_unit_number}, which"
            " covers several lessons of this module. Pick ONLY the questions that test THIS"
            f" lesson's content — at most {MAX_PICKED_MCQS}, none if none fits — and write a"
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
        lines.append(f"\n[{mcq.ref}] {mcq.stem}")
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
    concept_count = max(len(ctx.lesson_list("concepts")), 1)
    key_point_count = len(ctx.lesson_list("key_points"))
    places = ", ".join(PLACES)
    return f"""Return ONE JSON object with exactly these keys. Every {{"en": ..., "fr": ...}} object has English in "en" and French in "fr".

{{
  "objectives": [{{"id": "o1", "en": "learning objective", "fr": "objectif"}}],
  "misconceptions": [{{"id": "m_short_slug", "en": "Thinks that ...", "fr": "Pense que ..."}}],
  "characters": {{"mentor": "name of a mentor or teacher fitting the lesson", "peer": "name of a colleague or classmate"}},
  "chapter_titles": [{{"en": "...", "fr": "..."}}, {{"en": "...", "fr": "..."}}, {{"en": "...", "fr": "..."}}],
  "story": {{
    "opening": {{"en": "max 90 chars, speaks to {{child}}", "fr": "max 90 caractères"}},
    "mentor_intro": {{"en": "the mentor greets {{child}} and sets the mission", "fr": "..."}},
    "example_intro": {{"en": "...", "fr": "..."}},
    "example_dialogue": [{{"who": "mentor" or "peer", "en": "...", "fr": "..."}}],
    "wrap_up": {{"en": "...", "fr": "..."}}
  }},
  "concepts": [{{"title": {{"en": "...", "fr": "..."}}, "en": ["row", "row"], "fr": ["ligne", "ligne"]}}],
  "example": {{"place": "one of: {places}", "title": {{"en": "...", "fr": "..."}}, "en": ["row"], "fr": ["ligne"]}},
  "key_points_home": ["each lesson key point translated into the home language"],
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
  "tutor": {{
    "intro": {{"en": "Margo greets {{child}} and says she is an AI, not a real person", "fr": "... une IA, pas une vraie personne"}},
    "off_topic": {{"en": "kind redirect back to the lesson", "fr": "..."}},
    "worry": {{"en": "if the learner shares a worry: talk to a trusted person now", "fr": "..."}},
    "earlier_weeks": "one line on what came before this unit"
  }},
  "__complete": true
}}

COUNTS AND RULES FOR THIS UNIT:
- Language of instruction: "{target}". Home language: "{home}". Write both languages everywhere.
- "objectives": exactly {plan.objectives}, ids o1..o{plan.objectives}.
- "concepts": exactly {concept_count}, one per lesson concept, in order; 2-4 short rows each, same number of rows in "en" and "fr".
- "key_points_home": exactly {key_point_count} entries, same order as the lesson's key points.
{_derived_rule(ctx, plan)}
- "exercises": exactly {plan.exercises}, one per objective.
- "minigame": 2 or 3 rounds of 4-5 items; at least 2 correct and 1 wrong item per round.
- Every misconception id you use must be in "misconceptions". Never put a misconception on a correct option.
- No prompt or hint may contain the correct answer's words. No two options of a question may be the same.
- Story lines at most 90 characters per language; prompts at most 150; hints at most 120.
- The learner is {{child}}: write it exactly like that. Speak to the learner as "you" / "tu"; French stays gender-neutral for the learner.
"""


def _derived_rule(ctx: LessonStoryContext, plan: StoryPlan) -> str:
    distractors = (
        'Give EVERY wrong option a "distractors" entry (option letter, misconception id,'
        " targeted hint). Assign each to the objective it tests."
    )
    if ctx.picks_from_quiz:
        return (
            f'- "derived": 0 to {MAX_PICKED_MCQS} entries, one per candidate quiz question'
            ' you picked as testing THIS lesson, with its "ref" from the list above. Never'
            f" pick a question about another lesson. {distractors}\n"
            f'- "questions": {plan.extra_questions} minus the number of "derived" entries'
            ' (never fewer than 0) extra questions (type "choice" or "exact_text"), so that'
            " every objective has at least 2 questions."
        )
    return (
        f'- "derived": exactly {len(ctx.mcqs)} entries, one per quiz question above, with'
        f' the same "ref". {distractors}\n'
        f'- "questions": exactly {plan.extra_questions} extra questions (type "choice" or'
        ' "exact_text"), so that every objective has at least 2 questions.'
    )


def build_story_user_message(ctx: LessonStoryContext, plan: StoryPlan | None = None) -> str:
    """The user message: the lesson, the quiz to derive from, and the contract."""
    plan = plan or plan_for(ctx)
    unit_title = ctx.unit_title[ctx.target]
    return (
        f'REQUEST: write the story-mode spine for unit {ctx.unit_number} — "{unit_title}"'
        f' of the module "{ctx.module_title[ctx.target]}".\n'
        "STRICT CONSTRAINT: use ONLY the lesson and quiz below; stay on this unit.\n\n"
        f"=== LESSON ({ctx.target}) ===\n{_lesson_block(ctx)}\n\n"
        f"=== QUIZ ===\n{_quiz_block(ctx)}\n\n"
        f"=== OUTPUT ===\n{_schema(ctx, plan)}"
    )


def build_repair_message(
    user_message: str,
    issues: list[ValidationIssue],
    previous_spine: dict[str, Any] | None,
    attempt: int,
    budget: int,
) -> str:
    """Feed the validator's remaining errors back, with the spine that caused them.

    Paths are those of the assembled story; the legend maps them onto the
    spine the model wrote.
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
        "The story built from your previous JSON failed these checks. Fix every one"
        " and return the COMPLETE JSON again, same structure:\n"
        f"{bullets}\n\n"
        "How the paths map to your JSON: questions[qN] is your 'derived' entry with"
        " that ref; questions[<id>] is your extra question with that id; choices[i]"
        " is option letter a, b, c, d for i = 0, 1, 2, 3; exercises[EN] is your N-th"
        " exercise; minigames[g1].rounds[i] is your mini-game round i (from 0)."
        " A [missing_translation] path is already the path of a field of YOUR JSON"
        " (e.g. derived[q2].options_home, concepts[0].fr, story.opening.fr): write it"
        ' in that language, with "en" in English and "fr" in French.\n\n'
        f"Your previous JSON:\n{previous}"
    )
