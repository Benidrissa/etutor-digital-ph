"""The Hero's Journey as a table applied by code (#2749, story mode v2, phase 3).

The model never chooses the structure of a module story. This module holds the
table: twelve stages in four moments, the blocks each stage plays, and how the
stages are dealt over a module's chapters (the rally counted as one). It is
pure data and arithmetic: no database, no model.

A journey exists on NEW bibles and plans only, as ``cast_policy`` does: a
bible made with the switch :data:`SETTING` on carries ``journey``
(``template``, ``quest``, ``shadow``), its plans carry ``journey``
(``template``, ``mode``), a ``stages`` list on every chapter and the rally, and
a ``question`` on every lesson chapter. A story already stored has none of them
and is read and told exactly as before.
"""

from __future__ import annotations

from typing import Any

#: The platform setting that turns journeys on for NEW course bibles (default off).
SETTING = "story-journey-enabled"

TEMPLATE = "heros_journey"
#: The only mode of this phase; open loops are #2751.
LINEAR = "linear"

#: ``quest`` and ``shadow`` (bible) and ``question`` (a chapter): English, this many words.
WORD_LIMIT = 30

#: ``(stage number, name, what the chapter does with it)``.
STAGES: tuple[tuple[int, str, str], ...] = (
    (1, "Ordinary world", "show what the learner believes before the course"),
    (2, "Call", "the mission, started by a surprising fact"),
    (3, "Refusal", "the misconception is said aloud by a character"),
    (4, "Mentor", "the first tool, from an elder, a book or an object"),
    (5, "Threshold", "the first application: the misconception comes undone"),
    (6, "Tests, allies, enemies", "practice, one typical error per test"),
    (7, "Approach", "prepare the hardest idea"),
    (8, "Ordeal", "the hardest idea"),
    (9, "Reward", "the rule is named"),
    (10, "Road back", "transfer: the rule used somewhere new"),
    (11, "Resurrection", "mixed questions: everything together"),
    (12, "Elixir", "what we take away, and the next topic"),
)

#: The moments of the journey, in order, and their stages.
START = (1, 2, 3, 4, 5)
TRIALS = (6,)
SUMMIT = (7, 8, 9)
RETURN = (10, 11, 12)

MENTOR_STAGE = 4

#: The macro blocks a stage plays, in order (read by the director script, #2746).
BLOCKS: dict[int, tuple[str, ...]] = {
    3: ("bet", "mistake"),
    5: ("machine",),
    6: ("ask",),
    8: ("bet", "mistake"),
    9: ("card",),
    11: ("ask",),
    12: ("teaser",),
}


def stage_name(stage: int) -> str:
    return next((name for number, name, _ in STAGES if number == stage), "")


def stage_purpose(stage: int) -> str:
    return next((purpose for number, _, purpose in STAGES if number == stage), "")


def stage_blocks(stages: list[int]) -> list[str]:
    """The blocks the given stages play, in the order of the stages."""
    return [block for stage in stages for block in BLOCKS.get(stage, ())]


def _moments(chapters: int) -> list[tuple[int, ...]]:
    """The moments each of ``chapters`` chapters plays, the Return in the last one."""
    if chapters <= 1:
        return [START + TRIALS + SUMMIT + RETURN]
    if chapters == 2:
        return [START, TRIALS + SUMMIT + RETURN]
    if chapters == 3:
        return [START, TRIALS + SUMMIT, RETURN]
    # 4: one moment each; beyond 4 the extra chapters are Trials.
    return [START, *([TRIALS] * (chapters - 3)), SUMMIT, RETURN]


def distribute(chapters: int, *, mentor: bool = True) -> list[list[int]]:
    """The stages of each of ``chapters`` chapters, the rally counted as a chapter.

    Stage 4 (the mentor) is left out when ``mentor`` is false: its chapter keeps
    its other stages.
    """
    return [
        [stage for stage in moment if mentor or stage != MENTOR_STAGE]
        for moment in _moments(max(1, chapters))
    ]


def mentor_in_story(cast_policy: str | None) -> bool:
    """Stage 4 is listed only when the plan's mentor policy is ``cameo`` or ``lead``."""
    return cast_policy in ("cameo", "lead")


def words(value: Any, limit: int = WORD_LIMIT) -> str:
    """``value`` as one line of at most ``limit`` words."""
    if value is None or isinstance(value, dict | list | bool):
        return ""
    return " ".join(str(value).split()[:limit])


def question_in_code(title: str) -> str:
    """The chapter question of a plan made in code: built from the lesson's title."""
    return words(f"What is «{title.strip()}» really about?") if title.strip() else ""


def plan_journey() -> dict[str, str]:
    """The plan-level ``journey`` of a new plan."""
    return {"template": TEMPLATE, "mode": LINEAR}


def bible_journey(raw: Any) -> dict[str, str]:
    """The bible-level ``journey`` from the model's answer: quest and shadow, 30 words each."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "template": TEMPLATE,
        "quest": words(raw.get("quest")),
        "shadow": words(raw.get("shadow")),
    }


def is_linear(plan: dict[str, Any] | None) -> bool:
    journey = (plan or {}).get("journey")
    return isinstance(journey, dict) and journey.get("mode") == LINEAR


def stage_lines(stages: Any) -> list[str]:
    """``"3. Refusal: ..."`` for each stage number of a chapter."""
    out = []
    for stage in stages if isinstance(stages, list) else []:
        if isinstance(stage, int) and stage_name(stage):
            out.append(f"{stage}. {stage_name(stage)}: {stage_purpose(stage)}")
    return out
