"""Audience detection and age-tier guidance for kids-adaptive prompt routing.

Detects whether a course targets children via taxonomy_categories slugs, then
provides age-tier-specific pedagogical instructions for prompt templates.

Zero impact on adult courses: detect_audience(None) always returns is_kids=False.
All new params in callers default to None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models.course import Course

KIDS_AUDIENCE_SLUGS: frozenset[str] = frozenset(
    {"kindergarten", "primary_school", "secondary_school"}
)

_SLUG_AGE_RANGES: dict[str, tuple[int, int]] = {
    "kindergarten": (3, 6),
    "primary_school": (6, 12),
    "secondary_school": (12, 18),
}

_AGE_PATTERN_EN = re.compile(r"\(\s*[Aa]ges?\s+(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\s*\)")
_AGE_PATTERN_FR = re.compile(r"\(\s*(\d{1,2})\s*(?:à|-)\s*(\d{1,2})\s*ans?\s*\)", re.IGNORECASE)


@dataclass
class AudienceContext:
    is_kids: bool
    age_min: int | None = None
    age_max: int | None = None
    audience_slugs: list[str] = field(default_factory=list)


def detect_audience(course: Course | None) -> AudienceContext:
    """Detect whether a course targets children via taxonomy_categories.

    Checks for kids audience slugs in taxonomy_categories, then attempts to
    parse an age range from the course title. Falls back to slug-based age
    ranges if no title match is found.

    Args:
        course: SQLAlchemy Course object (with lazy="selectin" taxonomy_categories)
                or None for adult / unauthenticated callers.

    Returns:
        AudienceContext with is_kids=False when course is None or adult.
    """
    if course is None:
        return AudienceContext(is_kids=False)

    cats = getattr(course, "taxonomy_categories", None) or []
    audience_slugs = [
        tc.slug
        for tc in cats
        if getattr(tc, "type", None) == "audience" and tc.slug in KIDS_AUDIENCE_SLUGS
    ]

    if not audience_slugs:
        return AudienceContext(is_kids=False)

    age_min, age_max = _parse_age_from_title(course) or _age_from_slugs(audience_slugs)

    return AudienceContext(
        is_kids=True,
        age_min=age_min,
        age_max=age_max,
        audience_slugs=audience_slugs,
    )


def _parse_age_from_title(course: Course) -> tuple[int, int] | None:
    """Try to extract age range from the course title (EN or FR)."""
    for title in (
        getattr(course, "title_en", None),
        getattr(course, "title_fr", None),
    ):
        if not title:
            continue
        for pattern in (_AGE_PATTERN_EN, _AGE_PATTERN_FR):
            m = pattern.search(title)
            if m:
                return int(m.group(1)), int(m.group(2))
    return None


def _age_from_slugs(slugs: list[str]) -> tuple[int, int]:
    """Infer age range from the set of audience slugs."""
    mins, maxs = [], []
    for slug in slugs:
        if slug in _SLUG_AGE_RANGES:
            lo, hi = _SLUG_AGE_RANGES[slug]
            mins.append(lo)
            maxs.append(hi)
    if mins and maxs:
        return min(mins), max(maxs)
    return (6, 12)


def _age_tier(age_min: int | None, age_max: int | None) -> str:
    """Map age range to one of three pedagogical tiers."""
    effective_max = age_max or 12
    if effective_max >= 13:
        return "teen"
    mid = ((age_min or 0) + effective_max) / 2
    if mid <= 8:
        return "early"
    return "middle"


_GUIDANCE_FR: dict[str, str] = {
    "early": (
        "PÉDAGOGIE ENFANTS (5-8 ans) :\n"
        "- Phrases très courtes (10-15 mots maximum)\n"
        "- Objets concrets du quotidien (fruits, jouets, animaux)\n"
        "- Un personnage mascotte récurrent pour raconter l'histoire\n"
        "- Jeux de comptage et répétitions rythmiques\n"
        "- Ton très encourageant : « Bravo ! », « Super ! », « Tu peux le faire ! »\n"
        "- Une seule idée principale par section\n"
        "- Propose une activité simple à faire à la maison\n"
        "- Évite tout vocabulaire abstrait ou technique"
    ),
    "middle": (
        "PÉDAGOGIE ENFANTS (9-12 ans) :\n"
        "- Phrases simples (15-20 mots)\n"
        "- Histoires situées dans un marché, une école ou un village africain\n"
        "- Explications visuelles étape par étape\n"
        "- Section « Essaie toi-même ! » avec une mini-activité\n"
        "- Langage encourageant : « C'est ta mission ! », « Tu es un explorateur ! »\n"
        "- Exemples tirés de la vie quotidienne d'un enfant de 10 ans\n"
        "- Analogies amusantes (ex. le corps comme une ville avec des gardiens)\n"
        "- Évite le jargon professionnel"
    ),
    "teen": (
        "PÉDAGOGIE ADOLESCENTS (13-15 ans) :\n"
        "- Vocabulaire accessible sans jargon technique excessif\n"
        "- Scénarios de problèmes réels à résoudre\n"
        "- Défis de raisonnement et de pensée critique\n"
        "- Connexions avec des carrières et des métiers concrets\n"
        "- Ton respectueux et stimulant intellectuellement\n"
        "- Exemples en lien avec des enjeux actuels (santé, environnement, société)\n"
        "- Questions ouvertes pour stimuler la réflexion\n"
        "- Évite un ton trop infantilisant"
    ),
}

_GUIDANCE_EN: dict[str, str] = {
    "early": (
        "CHILDREN'S PEDAGOGY (ages 5-8):\n"
        "- Very short sentences (10-15 words maximum)\n"
        "- Concrete everyday objects (fruits, toys, animals)\n"
        "- A recurring mascot character to tell the story\n"
        "- Counting games and rhythmic repetition\n"
        "- Very encouraging tone: 'Great job!', 'You can do it!', 'Amazing!'\n"
        "- Only one main idea per section\n"
        "- Include a simple take-home activity\n"
        "- Avoid all abstract or technical vocabulary"
    ),
    "middle": (
        "CHILDREN'S PEDAGOGY (ages 9-12):\n"
        "- Simple sentences (15-20 words)\n"
        "- Stories set in an African market, school, or village\n"
        "- Step-by-step visual explanations\n"
        "- A 'Try it yourself!' section with a mini-activity\n"
        "- Encouraging language: 'It's your mission!', 'You are an explorer!'\n"
        "- Examples from the daily life of a 10-year-old\n"
        "- Fun analogies (e.g. the body as a city with guardians)\n"
        "- Avoid professional jargon"
    ),
    "teen": (
        "TEEN PEDAGOGY (ages 13-15):\n"
        "- Accessible vocabulary without excessive technical jargon\n"
        "- Real-world problem scenarios to solve\n"
        "- Reasoning challenges and critical thinking prompts\n"
        "- Connections to careers and concrete professions\n"
        "- Respectful and intellectually stimulating tone\n"
        "- Examples linked to current issues (health, environment, society)\n"
        "- Open questions to stimulate reflection\n"
        "- Avoid an overly childish tone"
    ),
}


def detect_audience_from_slugs(
    audience_type: list[str] | None,
    title_en: str | None = None,
    title_fr: str | None = None,
) -> AudienceContext:
    """Detect kids audience from raw slug list and optional title strings.

    Lightweight variant of detect_audience() for callers that don't have a
    Course ORM object (e.g. CourseAgentService._build_prompt).

    Args:
        audience_type: List of taxonomy slugs (e.g. ["primary_school", "mathematics"]).
        title_en: Optional English course title for age-range extraction.
        title_fr: Optional French course title for age-range extraction.

    Returns:
        AudienceContext with is_kids=False when audience_type is None/empty or adult.
    """
    if not audience_type:
        return AudienceContext(is_kids=False)

    kids_slugs = [s for s in audience_type if s in KIDS_AUDIENCE_SLUGS]
    if not kids_slugs:
        return AudienceContext(is_kids=False)

    age_range: tuple[int, int] | None = None
    for title in (title_en, title_fr):
        if not title:
            continue
        for pattern in (_AGE_PATTERN_EN, _AGE_PATTERN_FR):
            m = pattern.search(title)
            if m:
                age_range = (int(m.group(1)), int(m.group(2)))
                break
        if age_range:
            break

    if age_range is None:
        age_range = _age_from_slugs(kids_slugs)

    return AudienceContext(
        is_kids=True,
        age_min=age_range[0],
        age_max=age_range[1],
        audience_slugs=kids_slugs,
    )


def get_audience_guidance(audience: AudienceContext, language: str) -> str:
    """Return age-tier-specific pedagogical instructions for prompt injection.

    Args:
        audience: AudienceContext produced by detect_audience().
        language: Content language — "fr" or "en".

    Returns:
        A multi-line guidance block for the {audience_guidance} template variable.
        Empty string if is_kids is False.
    """
    if not audience.is_kids:
        return ""
    tier = _age_tier(audience.age_min, audience.age_max)
    table = _GUIDANCE_FR if language == "fr" else _GUIDANCE_EN
    return table.get(tier, "")
