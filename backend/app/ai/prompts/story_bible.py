"""The prompt of a course's story bible: its cast and places (#2674).

One call per course writes the characters and backdrops every module story
of the course is told with (:mod:`app.domain.services.story_bible`). The
answer is normalised in code, so a gap costs a default, never the story.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.domain.services.story_bible import BibleModule

_SYSTEM = """You are the art director and showrunner of an animated, bilingual (English/French) \
cartoon series that teaches a course to {audience_label}. You write its "bible": the recurring \
characters and the places where every episode happens. Each module of the course becomes one \
episode; the same characters and places come back in every episode.

The series is set in {country_line}. Characters are West African people living there today; \
places are real kinds of places there (a market, a school, a health centre, a farm, a river \
bank...), drawn as cartoon backdrops. Use real local details only when you are sure of them, \
and give a source for each; anything you make up is marked "invented": true.

{register}

The image model draws from your "look" sentences, so each one must describe the character the \
same way every time: age, build, skin tone, hair, clothes, ONE accessory. No names, no text, \
no brands in a look. A place's look describes the backdrop with no people and no writing.

Names: the learner is the hero, written "{{child}}"; the hero's best friend is "{{friend}}" (the \
learner types the friend's name; you give a default_name). Other names are short West African \
names shown the same way in English and French: never "Mr", "Mrs", "M." or "Mme" in a name.

Margo is the AI tutor: a friendly cartoon margouillat (an agama lizard, common on West African \
walls). She is an AI and says so; she gives hints, never answers.

CRITICAL: answer with ONE valid JSON object only, exactly in the structure the user message \
gives. No preamble, no markdown fences."""

_KIDS_REGISTER = (
    "The audience is children aged {age_range}. The world is the hero's: home, family, school,"
    " friends, the market, the neighbourhood. The mentor is the class teacher; the family"
    " member is a parent, grandparent or older sibling."
)
_ADULT_REGISTER = (
    "The audience is adult learners. The world is their work: the workplace, colleagues, the"
    " field, the community they serve. The friend is a colleague, the mentor a supervisor,"
    " the family member a respected member of the community."
)

_SCHEMA = """Return this JSON object:
{{
  "cast": [
    {{"id": "hero", "about": "personality in a few words (English)",
      "variants": [{{"id": "{v1}", "look": "one English sentence"}}, {{"id": "{v2}", "look": "one English sentence"}}],
      "voice": {{"pitch": 1.4, "rate": 1.0}}}},
    {{"id": "friend", "default_name": "a first name", "about": "...", "look": "one English sentence", "voice": {{"pitch": 1.5, "rate": 1.05}}}},
    {{"id": "mentor", "name": "a name", "about": "...", "look": "one English sentence", "voice": {{"pitch": 0.85, "rate": 0.95}}}},
    {{"id": "family", "name": "a name", "about": "...", "look": "one English sentence", "voice": {{"pitch": 0.95, "rate": 0.95}}}},
    {{"id": "margo", "about": "...", "look": "one English sentence describing the cartoon margouillat", "voice": {{"pitch": 1.8, "rate": 1.05}}}}
  ],
  "places": [
    {{"id": "short_snake_case_id", "title": {{"en": "English title", "fr": "titre français"}},
      "look": "one English sentence: the backdrop, no people, no text"}}
  ],
  "facts": [
    {{"en": "a real local detail", "fr": "le même détail", "source": "where it comes from", "place": "a place id"}},
    {{"en": "an invented detail", "fr": "...", "invented": true}}
  ],
  "missions": [
    {{"module": 1, "en": "the episode's mission, one sentence", "fr": "la mission de l'épisode"}}
  ],
  "__complete": true
}}

RULES:
- "cast": exactly the ids hero, friend, mentor, family, margo. The hero has no name and no single
  look: two "variants", "{v1}" and "{v2}", the same person otherwise (same age, same uniform or
  work clothes). Every look is ONE sentence of at most 40 words.
- "places": {min_places} to {max_places} places where this course's lessons can happen, set in
  {country_line}. Ids are lower-case snake_case.
- "facts": 3 to 8 local details the episodes may use (a place, a food, a festival, a number).
- "missions": one per module below, in order: a small goal the characters chase through the
  episode, tied to what the module teaches, set in the first lesson and reached in the last.
  At most 20 words each, no question marks.
- voice: pitch 0.5 to 2.0, rate 0.7 to 1.3."""


def _modules_block(modules: Sequence[BibleModule]) -> str:
    if not modules:
        return "MODULES: (none listed)"
    rows = [
        f"- Module {m.number}: {m.title['en']} / {m.title['fr']}"
        for m in sorted(modules, key=lambda m: m.number)
    ]
    return "MODULES:\n" + "\n".join(rows)


def build_bible_messages(
    course: Any,
    modules: Sequence[BibleModule],
    *,
    is_kids: bool,
    country: str,
) -> tuple[str, str]:
    """``(system prompt, user message)`` for the course's bible."""
    from app.ai.prompts.audience import detect_audience

    audience = detect_audience(course) if is_kids else None
    age_range = (
        f"{audience.age_min}-{audience.age_max}" if audience and audience.is_kids else "8-14"
    )
    country_line = f"{country} (West Africa)" if country else "West Africa"
    system = _SYSTEM.format(
        audience_label=f"children aged {age_range}" if is_kids else "adult professionals",
        country_line=country_line,
        register=(_KIDS_REGISTER.format(age_range=age_range) if is_kids else _ADULT_REGISTER),
    )
    v1, v2 = ("girl", "boy") if is_kids else ("woman", "man")
    title = {
        "en": str(getattr(course, "title_en", "") or getattr(course, "title_fr", "") or ""),
        "fr": str(getattr(course, "title_fr", "") or getattr(course, "title_en", "") or ""),
    }
    description = str(
        getattr(course, "description_en", "") or getattr(course, "description_fr", "") or ""
    )[:800]
    user = (
        f"COURSE: {json.dumps(title, ensure_ascii=False)}\n"
        f"DESCRIPTION: {description or '(none)'}\n"
        f"AUDIENCE: {'children' if is_kids else 'adults'}\n"
        f"COUNTRY: {country_line}\n"
        f"{_modules_block(modules)}\n\n"
        + _SCHEMA.format(
            v1=v1,
            v2=v2,
            min_places=5,
            max_places=8,
            country_line=country_line,
        )
    )
    return system, user
