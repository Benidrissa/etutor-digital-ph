"""Whether a story has a mentor, and how much he talks (#2710).

The mentor (the class teacher, the supervisor) used to be hard-wired into every
story. On the studied story he said 16 lines of 155, about 11 of them only
handing a question over, and he was absent from four scenes out of seven, yet
the story worked. He also costs about four AI images per course. So the mentor
is now a **cast policy**, chosen in code and stored with the new bible and the
new plan:

* ``none`` — no mentor: not in the cast, not in the art, not in any line. The
  friend takes the sceptical "how do you know?" role;
* ``cameo`` — the mentor opens or closes the story and nothing more: he never
  explains and never hands a question over;
* ``lead`` — the mentor is a regular character (today's behaviour).

The policy is chosen by :func:`choose_cast_policy`, from the course and module
(title, description, audience age) and an admin override
(``story-mentor-policy``: ``auto``, ``never`` or ``always``).

A stored bible or plan **without** a ``cast_policy`` is a legacy one and keeps
behaving exactly as before (:func:`policy_of`), so no existing story's digest
moves and nothing is regenerated.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.domain.services.story_props import fold

NONE, CAMEO, LEAD = "none", "cameo", "lead"
POLICIES = (NONE, CAMEO, LEAD)
#: The admin setting's values.
OVERRIDES = ("auto", "never", "always")
OVERRIDE_SETTING = "story-mentor-policy"

#: The key a new bible and a new plan carry: ``{"mentor": <policy>}``.
KEY = "cast_policy"

_RANK = {NONE: 0, CAMEO: 1, LEAD: 2}

#: Safety and high-risk health topics: the learner needs a trusted adult.
_SAFETY_RE = re.compile(
    r"\b(?:safety|first aid|emergenc\w*|hazard\w*|danger\w*|poison\w*|toxic\w*|overdose"
    r"|choking|drown\w*|snake ?bites?|resuscitat\w*|vaccin\w*|outbreaks?|epidemic\w*"
    r"|cholera|ebola|malaria|hiv|tubercul\w*|maternal|pregnan\w*|dosage|medicat\w*"
    r"|safeguard\w*|abuse|violence|high-risk|sexual health|infection control"
    r"|securite|premiers secours|secours|urgences?|dangers?|dangereu\w*|poison|intoxication"
    r"|noyade|etouffement|vaccin\w*|epidemi\w*|paludisme|tuberculose|maternel\w*"
    r"|grossesse|posologie|medicament\w*|violences?|haut risque|a risque|vih|sida)\b"
)
#: A trade or craft learned beside an experienced adult.
_APPRENTICE_RE = re.compile(
    r"\b(?:apprentice\w*|craft\w*|trades?|workshops?|artisan\w*|tailoring|carpentry|welding"
    r"|mechanics?|vocational|apprenti\w*|metiers?|ateliers?|couture|menuiserie|soudure"
    r"|mecanique|formation professionnelle)\b"
)
#: Inquiry and experiment: the child finds out; nobody explains.
_INQUIRY_RE = re.compile(
    r"\b(?:experiments?|investigat\w*|inquiry|hypothes\w*|observ\w*|discover\w*|science"
    r"|sciences|scientific|experiences?|enquetes?|decouvr\w*|scientifiques?|laboratoire"
    r"|laboratory)\b"
)

#: A course whose learners average under this age gets a cameo mentor.
CAMEO_BELOW_AGE = 10


def _strings(obj: Any) -> list[str]:
    """The titles and descriptions of a course, module or bible module (any shape)."""
    out: list[str] = []
    if obj is None:
        return out
    for attr in ("title_en", "title_fr", "description_en", "description_fr"):
        value = getattr(obj, attr, None)
        if isinstance(value, str):
            out.append(value)
    title = getattr(obj, "title", None)
    if isinstance(title, dict):
        out.extend(v for v in title.values() if isinstance(v, str))
    elif isinstance(title, str):
        out.append(title)
    return out


def _audience(course: Any, audience: Any) -> tuple[bool, int | None, int | None]:
    """``(is_kids, age_min, age_max)`` from an audience context, a label or the course."""
    from app.ai.prompts.audience import detect_audience

    if hasattr(audience, "is_kids"):
        return bool(audience.is_kids), audience.age_min, audience.age_max
    detected = detect_audience(course) if course is not None else None
    if isinstance(audience, bool):
        is_kids = audience
    elif isinstance(audience, str):
        is_kids = audience.lower() in ("kids", "kid", "children", "child")
    else:
        is_kids = bool(detected and detected.is_kids)
    if detected and detected.is_kids:
        return is_kids, detected.age_min, detected.age_max
    return is_kids, None, None


def normalise_override(value: Any) -> str:
    """``auto``, ``never`` or ``always``; anything else is ``auto``."""
    text = str(value or "").strip().lower()
    return text if text in OVERRIDES else "auto"


def choose_cast_policy(
    course: Any,
    module: Any,
    audience: Any = None,
    *,
    override: Any = "auto",
    modules: Iterable[Any] = (),
) -> str:
    """The mentor policy of a course (``module`` ``None``) or of one of its modules.

    In order, the first rule that applies wins:

    1. the admin override: ``never`` is ``none``, ``always`` is ``lead``;
    2. a safety or high-risk health topic (course, module or any of ``modules``
       mentions first aid, danger, poison, vaccines, outbreaks, pregnancy,
       dosage...) is ``lead``;
    3. an apprenticeship topic (a trade, a craft, a workshop) is ``cameo``;
    4. an inquiry or experiment topic (science, experiment, observe,
       investigate, discover) is ``none``;
    5. kids whose average age is under :data:`CAMEO_BELOW_AGE` (6-9 years, so a
       6-12 primary course too) is ``cameo``;
    6. everything else (learners of 10 and up, adults, unknown ages) is ``none``.

    ``audience`` is an :class:`AudienceContext`, ``"kids"``/``"adult"``, a bool
    or ``None`` (then read from the course).
    """
    mode = normalise_override(override)
    if mode == "never":
        return NONE
    if mode == "always":
        return LEAD
    text = fold(" ".join([*_strings(course), *_strings(module), *_all(modules)]))
    if _SAFETY_RE.search(text):
        return LEAD
    if _APPRENTICE_RE.search(text):
        return CAMEO
    if _INQUIRY_RE.search(text):
        return NONE
    is_kids, age_min, age_max = _audience(course, audience)
    if (
        is_kids
        and age_min is not None
        and age_max is not None
        and (age_min + age_max) / 2 < CAMEO_BELOW_AGE
    ):
        return CAMEO
    return NONE


def _all(modules: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for item in modules:
        out.extend(_strings(item))
    return out


def course_cast_policy(
    course: Any,
    modules: Iterable[Any],
    audience: Any = None,
    *,
    override: Any = "auto",
) -> str:
    """The policy of a course's bible: the strongest any of its modules needs.

    The bible draws the mentor once for the whole course, so he is drawn when
    any module wants him; each module then narrows it (:func:`module_policy`).
    """
    modules = list(modules)
    found = [choose_cast_policy(course, None, audience, override=override, modules=modules)]
    found += [choose_cast_policy(course, m, audience, override=override) for m in modules]
    return max(found, key=_RANK.__getitem__)


def bible_policy(bible_content: Any) -> str | None:
    """The mentor policy a stored bible carries; ``None`` for a legacy bible."""
    policy = bible_content.get(KEY) if isinstance(bible_content, dict) else None
    value = policy.get("mentor") if isinstance(policy, dict) else None
    return value if value in POLICIES else None


def module_policy(bible_content: Any, chosen: str) -> str | None:
    """The policy of a new plan: ``chosen``, never above what its bible drew.

    ``None`` for a legacy bible (no ``cast_policy``): the plan then behaves as
    it always did and carries no policy, so its digest does not move.
    """
    drawn = bible_policy(bible_content)
    if drawn is None:
        return None
    return chosen if _RANK[chosen] <= _RANK[drawn] else drawn


def policy_of(content: Any) -> str:
    """The mentor policy of a bible or plan: a legacy one (no key) is ``lead``."""
    return bible_policy(content) or LEAD


def with_policy(policy: str) -> dict[str, str]:
    return {"mentor": policy if policy in POLICIES else LEAD}
