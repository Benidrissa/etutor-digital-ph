"""The story bible: one cast and one set of places per course (#2674).

Every module story of a course is told by the same characters, in the same
places, so the art made for them (#2675) is made once per course and a
learner meets the same friends from the first module to the last.

The bible is written by **one model call**, made the first time a story of
the course is needed (:meth:`StoryBibleService.get_or_create`), and stored in
``story_course_bibles``; every later module story of the course reuses it.
:func:`normalise_bible` turns whatever the model wrote into the fixed shape
below, filling any gap from a deterministic default, so a bible is always
complete:

* ``cast`` — role ids ``hero`` (the learner, ``name`` ``{child}``, with two
  ``variants`` the learner picks from: ``girl``/``boy`` for kids courses,
  ``woman``/``man`` for adult ones), ``friend`` (``name`` ``{friend}``, typed
  by the learner, else ``default_name``), ``mentor`` (the teacher or
  supervisor), optional ``family`` (a parent or relative for kids, a
  community member for adults) and ``margo`` (the AI tutor, a friendly
  cartoon margouillat who says she is an AI). Each has ``role``, ``kind``,
  ``art`` (a placeholder key of the A.8 catalog), ``look`` (ONE English
  sentence for the image model) and ``voice`` ``{pitch, rate}``; ``about``
  (English, for the screenplay prompt only) is never copied into a story.
  Names carry no honorific that differs between English and French;
* ``places`` — 5 to 8 backdrops: ``id``, a bilingual ``title`` and ``look``
  (English, no people, no text);
* ``facts`` — real local details with their ``source``, or marked
  ``invented``;
* ``missions`` — per module id, the mission its story sets in its first
  chapter and resolves in its last.

The story document carries the bible's cast (:func:`doc_cast`) and places
(:func:`doc_places`) exactly as the contract of #2672 says, so the art
pipeline reads them from any module story of the course and finds the same
values in every one.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

#: Recorded in the bible's content; a different shape would bump it.
BIBLE_VERSION = 1

HERO, FRIEND, MENTOR, FAMILY, TUTOR = "hero", "friend", "mentor", "family", "margo"
#: Cast ids in the order a story lists them.
CAST_IDS = (HERO, FRIEND, MENTOR, FAMILY, TUTOR)
#: ``cast[].role`` per id (contract of #2672).
ROLE_OF = {HERO: "hero", FRIEND: "friend", MENTOR: "mentor", FAMILY: "family", TUTOR: "tutor"}

#: ``{child}`` and ``{friend}`` are replaced by the player before display.
CHILD = "{child}"
FRIEND_NAME = "{friend}"
TUTOR_NAME = "Margo"

MIN_PLACES, MAX_PLACES = 5, 8
MAX_FACTS = 12
LOOK_LIMIT = 300
ABOUT_LIMIT = 200
NAME_LIMIT = 30

_SLUG_RE = re.compile(r"[^a-z0-9]+")
#: Honorifics that differ between English and French ("Mr" / "M."): a name
#: is shown the same in both languages, so they are left to the dialogue.
_HONORIFIC_RE = re.compile(
    r"^(?:mr|mrs|ms|miss|m|mme|mlle|monsieur|madame|mister)\.?\s+", re.IGNORECASE
)

_VOICES: dict[str, dict[str, dict[str, float]]] = {
    "kids": {
        HERO: {"pitch": 1.4, "rate": 1.0},
        FRIEND: {"pitch": 1.5, "rate": 1.05},
        MENTOR: {"pitch": 0.85, "rate": 0.95},
        FAMILY: {"pitch": 0.95, "rate": 0.95},
        TUTOR: {"pitch": 1.8, "rate": 1.05},
    },
    "adult": {
        HERO: {"pitch": 1.1, "rate": 1.0},
        FRIEND: {"pitch": 1.15, "rate": 1.0},
        MENTOR: {"pitch": 0.85, "rate": 0.95},
        FAMILY: {"pitch": 0.95, "rate": 0.95},
        TUTOR: {"pitch": 1.8, "rate": 1.05},
    },
}

#: Placeholder art keys of the A.8 catalog, for players without generated art.
_ART: dict[str, dict[str, str]] = {
    "kids": {
        HERO: "nandi",
        FRIEND: "friend",
        MENTOR: "mr_kabore",
        FAMILY: "maman_olivia",
        TUTOR: "margo",
    },
    "adult": {
        HERO: "m_sanou",
        FRIEND: "maman_olivia",
        MENTOR: "mr_kabore",
        FAMILY: "tonton_issouf",
        TUTOR: "margo",
    },
}

_VARIANT_IDS = {"kids": ("girl", "boy"), "adult": ("woman", "man")}

_DEFAULT_LOOKS: dict[str, dict[str, str]] = {
    "kids": {
        HERO: "an 11-year-old West African child, slim build, dark brown skin,"
        " in a white school shirt and navy uniform, carrying a small backpack",
        "girl": "an 11-year-old West African girl, slim build, dark brown skin, hair in two"
        " puffs, white school shirt and navy pleated skirt, a small blue backpack",
        "boy": "an 11-year-old West African boy, slim build, dark brown skin, short black"
        " hair, white school shirt and navy shorts, a small blue backpack",
        FRIEND: "an 11-year-old West African child, round face, medium brown skin, short"
        " braids, orange patterned dress, a yellow bracelet",
        MENTOR: "a West African teacher in his forties, tall and lean, dark skin, short grey"
        " hair, light blue shirt with a red tie and grey trousers, round glasses",
        FAMILY: "a West African mother in her late thirties, warm smile, dark skin, purple"
        " head wrap and a blue-and-yellow wax print dress, a woven market basket",
        TUTOR: "a friendly cartoon margouillat lizard (West African agama), orange head,"
        " blue body, big round eyes, a tiny green satchel",
    },
    "adult": {
        HERO: "a West African professional in their thirties, medium build, dark brown"
        " skin, smart casual work clothes, an ID badge on a lanyard",
        "woman": "a West African woman in her thirties, medium build, dark brown skin, hair"
        " in neat braids, white blouse and a wax print skirt, an ID badge on a lanyard",
        "man": "a West African man in his thirties, medium build, dark brown skin, short"
        " hair, light green shirt and dark trousers, an ID badge on a lanyard",
        FRIEND: "a West African colleague in her late twenties, slim build, medium brown"
        " skin, short natural hair, yellow wax print shirt, a notebook under her arm",
        MENTOR: "a West African supervisor in his fifties, broad build, dark skin, grey"
        " beard, white shirt and navy waistcoat, reading glasses on a cord",
        FAMILY: "a West African community elder in his sixties, lean build, dark skin,"
        " white kufi cap and a long blue boubou, a wooden walking stick",
        TUTOR: "a friendly cartoon margouillat lizard (West African agama), orange head,"
        " blue body, big round eyes, a tiny green satchel",
    },
}

_DEFAULT_NAMES = {
    "kids": {FRIEND: "Awa", MENTOR: "Kaboré", FAMILY: "Mariam"},
    "adult": {FRIEND: "Awa", MENTOR: "Kaboré", FAMILY: "Issouf"},
}

_DEFAULT_ABOUT = {
    "kids": {
        HERO: "the learner: curious, brave, sometimes gets things wrong and learns from it",
        FRIEND: "the hero's best friend: funny, quick to guess, loves a challenge",
        MENTOR: "the class teacher: patient, asks good questions, loves real examples",
        FAMILY: "the hero's mother: practical, knows the market and the neighbourhood",
        TUTOR: "Margo, the AI tutor: a cheerful margouillat who gives hints, never answers,"
        " and says she is an AI",
    },
    "adult": {
        HERO: "the learner: new to the team, keen, asks practical questions",
        FRIEND: "a colleague: experienced in the field, direct, good humour",
        MENTOR: "the supervisor: calm, rigorous, explains why the rules exist",
        FAMILY: "a respected community member: knows local habits and worries",
        TUTOR: "Margo, the AI tutor: a cheerful margouillat who gives hints, never answers,"
        " and says she is an AI",
    },
}

#: (id, en, fr, look) — used only to fill a bible the model left short.
_DEFAULT_PLACES: dict[str, list[tuple[str, str, str, str]]] = {
    "kids": [
        (
            "home",
            "Home",
            "La maison",
            "the courtyard of a West African family house, mango tree, bench, clay walls,"
            " bright afternoon light",
        ),
        (
            "classroom",
            "The classroom",
            "La classe",
            "a bright West African primary classroom, green chalkboard, wooden desks, a"
            " window onto a sunny yard",
        ),
        (
            "market",
            "The market",
            "Le marché",
            "a busy open-air West African market, colourful stalls of fruit and fabric,"
            " parasols, red earth ground",
        ),
        (
            "school_yard",
            "The school yard",
            "La cour de l'école",
            "a sandy school yard with a big shade tree, painted walls and a water tap",
        ),
        (
            "mango_farm",
            "The orchard",
            "Le verger",
            "a mango orchard at the edge of town, rows of leafy trees, a dirt path, blue sky",
        ),
    ],
    "adult": [
        (
            "desk",
            "The office",
            "Le bureau",
            "a small West African district office, desk with papers and a laptop, wall"
            " map, ceiling fan",
        ),
        (
            "market",
            "The market",
            "Le marché",
            "a busy open-air West African market, colourful stalls, parasols, red earth ground",
        ),
        (
            "field",
            "In the field",
            "Sur le terrain",
            "a village square in the West African Sahel, shade tree, mud-brick houses,"
            " motorbikes parked",
        ),
        (
            "meeting_room",
            "The meeting room",
            "La salle de réunion",
            "a plain meeting room, long table, plastic chairs, a flip chart, morning light",
        ),
        (
            "bus_station",
            "The bus station",
            "La gare routière",
            "a dusty West African bus station, minibuses, vendors with trays, a painted sign"
            " board without words",
        ),
    ],
}


def bible_digest(content: Any) -> str:
    """sha256 of the bible's content as canonical JSON."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _audience(is_kids: bool) -> str:
    return "kids" if is_kids else "adult"


def _str(value: Any, limit: int | None = None) -> str:
    if value is None or isinstance(value, dict | list | bool):
        return ""
    text = " ".join(str(value).split())
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(" ,;:")
    return text


def _sentence(value: Any, fallback: str) -> str:
    """One English sentence for the image model, without a final period."""
    text = _str(value, LOOK_LIMIT) or fallback
    return text.rstrip(" .")


def _neutral_name(value: Any, fallback: str) -> str:
    name = _HONORIFIC_RE.sub("", _str(value, NAME_LIMIT)).strip()
    if not name or "{" in name or "}" in name:
        return fallback
    return name


def _slug(value: Any) -> str:
    return _SLUG_RE.sub("_", _str(value).lower()).strip("_")[:30]


#: Lengths of a bible's bilingual texts: a place's title, a fact.
TITLE_LIMIT = 80
FACT_LIMIT = 200


def _pair(value: Any, limit: int | None = TITLE_LIMIT) -> dict[str, str] | None:
    """``{"en", "fr"}`` from a model value, each cut at ``limit`` (``None``: not cut)."""
    if isinstance(value, dict):
        en, fr = _str(value.get("en"), limit), _str(value.get("fr"), limit)
        if en or fr:
            return {"en": en or fr, "fr": fr or en}
    return None


def _voice(value: Any, default: dict[str, float]) -> dict[str, float]:
    out = dict(default)
    if isinstance(value, dict):
        for key, low, high in (("pitch", 0.5, 2.0), ("rate", 0.7, 1.3)):
            raw = value.get(key)
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                out[key] = round(min(max(float(raw), low), high), 2)
    return out


def _by_role(raw_cast: Any) -> dict[str, dict[str, Any]]:
    """The model's cast entries keyed by the role id they claim."""
    aliases = {
        HERO: HERO,
        "learner": HERO,
        "child": HERO,
        FRIEND: FRIEND,
        "peer": FRIEND,
        "colleague": FRIEND,
        MENTOR: MENTOR,
        "teacher": MENTOR,
        "supervisor": MENTOR,
        FAMILY: FAMILY,
        "parent": FAMILY,
        "community": FAMILY,
        TUTOR: TUTOR,
        "tutor": TUTOR,
    }
    out: dict[str, dict[str, Any]] = {}
    for item in raw_cast if isinstance(raw_cast, list) else []:
        if not isinstance(item, dict):
            continue
        for key in (_str(item.get("id")).lower(), _str(item.get("role")).lower()):
            role = aliases.get(key)
            if role and role not in out:
                out[role] = item
                break
    return out


def _cast(raw_cast: Any, audience: str) -> list[dict[str, Any]]:
    given = _by_role(raw_cast)
    looks = _DEFAULT_LOOKS[audience]
    kind = "child" if audience == "kids" else "adult"
    cast: list[dict[str, Any]] = []
    for member_id in CAST_IDS:
        raw = given.get(member_id, {})
        if member_id == FAMILY and not raw and given:
            # Optional: a model that wrote a cast but no family member chose so.
            continue
        member: dict[str, Any] = {
            "id": member_id,
            "role": ROLE_OF[member_id],
            "kind": "ai_tutor" if member_id == TUTOR else kind,
            "art": _ART[audience][member_id],
        }
        if member_id == HERO:
            member["name"] = CHILD
        elif member_id == FRIEND:
            member["name"] = FRIEND_NAME
            member["default_name"] = _neutral_name(
                raw.get("default_name") or raw.get("name"), _DEFAULT_NAMES[audience][FRIEND]
            )
        elif member_id == TUTOR:
            member["name"] = TUTOR_NAME
        else:
            member["name"] = _neutral_name(raw.get("name"), _DEFAULT_NAMES[audience][member_id])
        if member_id in (MENTOR, FAMILY) and audience == "kids":
            member["kind"] = "adult"
        member["look"] = _sentence(raw.get("look"), looks[member_id])
        if member_id == HERO:
            raw_variants = raw.get("variants") if isinstance(raw.get("variants"), list) else []
            variant_looks = {
                _str(v.get("id")).lower(): v.get("look")
                for v in raw_variants
                if isinstance(v, dict)
            }
            member["variants"] = [
                {"id": vid, "look": _sentence(variant_looks.get(vid), looks[vid])}
                for vid in _VARIANT_IDS[audience]
            ]
        member["voice"] = _voice(raw.get("voice"), _VOICES[audience][member_id])
        member["about"] = _str(raw.get("about"), ABOUT_LIMIT) or _DEFAULT_ABOUT[audience][member_id]
        cast.append(member)
    return cast


def _given_places(raw_places: Any) -> list[dict[str, Any]]:
    """The places of the model's answer that pass the checks (at most MAX_PLACES)."""
    places: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_places if isinstance(raw_places, list) else []:
        if not isinstance(item, dict) or len(places) >= MAX_PLACES:
            continue
        title = _pair(item.get("title"))
        place_id = _slug(item.get("id")) or (_slug(title["en"]) if title else "")
        look = _str(item.get("look"), LOOK_LIMIT)
        if not place_id or place_id in seen or title is None or not look:
            continue
        seen.add(place_id)
        places.append({"id": place_id, "title": title, "look": look.rstrip(" .")})
    return places


def _places(raw_places: Any, audience: str) -> list[dict[str, Any]]:
    places = _given_places(raw_places)
    seen = {place["id"] for place in places}
    for place_id, en, fr, look in _DEFAULT_PLACES[audience]:
        if len(places) >= MIN_PLACES:
            break
        if place_id not in seen:
            seen.add(place_id)
            places.append({"id": place_id, "title": {"en": en, "fr": fr}, "look": look})
    return places


def _facts(raw_facts: Any, place_ids: set[str]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for item in raw_facts if isinstance(raw_facts, list) else []:
        if not isinstance(item, dict) or len(facts) >= MAX_FACTS:
            continue
        text = _pair({"en": item.get("en"), "fr": item.get("fr")}, FACT_LIMIT)
        if text is None:
            continue
        source = _str(item.get("source"), 200)
        fact: dict[str, Any] = {"en": text["en"], "fr": text["fr"]}
        # A fact without a source is never presented as checked.
        if source and item.get("invented") is not True:
            fact["source"] = source
            fact["invented"] = False
        else:
            fact["invented"] = True
        place = _slug(item.get("place"))
        if place in place_ids:
            fact["place"] = place
        facts.append(fact)
    return facts


@dataclass(frozen=True)
class BibleModule:
    """A module of the course, as the bible's missions see it."""

    module_id: uuid.UUID
    number: int
    title: dict[str, str]


def _default_mission(module: BibleModule) -> dict[str, str]:
    return {
        "en": f"Crack the mystery of “{module.title['en']}” before the end of the week",
        "fr": f"Percer le mystère « {module.title['fr']} » avant la fin de la semaine",
    }


def _missions(raw_missions: Any, modules: Sequence[BibleModule]) -> dict[str, dict[str, str]]:
    by_number: dict[int, dict[str, str]] = {}
    for item in raw_missions if isinstance(raw_missions, list) else []:
        if not isinstance(item, dict):
            continue
        number = item.get("module")
        if isinstance(number, str) and number.strip().isdigit():
            number = int(number.strip())
        text = _pair({"en": _str(item.get("en"), 160), "fr": _str(item.get("fr"), 180)}, None)
        if isinstance(number, int) and not isinstance(number, bool) and text:
            by_number.setdefault(number, text)
    return {
        str(module.module_id): by_number.get(module.number) or _default_mission(module)
        for module in modules
    }


def normalise_bible(
    raw: Any,
    *,
    is_kids: bool,
    modules: Sequence[BibleModule] = (),
    country: str = "",
) -> dict[str, Any]:
    """A complete bible from whatever the model wrote; deterministic.

    Every gap is filled from the audience's defaults, so ``normalise_bible({})``
    is a usable (if generic) bible.
    """
    raw = raw if isinstance(raw, dict) else {}
    audience = _audience(is_kids)
    places = _places(raw.get("places"), audience)
    return {
        "version": BIBLE_VERSION,
        "audience": audience,
        "country": _str(country, 40),
        "cast": _cast(raw.get("cast"), audience),
        "places": places,
        "facts": _facts(raw.get("facts"), {p["id"] for p in places}),
        "missions": _missions(raw.get("missions"), modules),
    }


# --------------------------------------------------------------------------
# What a story document carries
# --------------------------------------------------------------------------

_DOC_CAST_KEYS = ("id", "name", "kind", "art", "voice", "role", "look", "variants", "default_name")


def doc_cast(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The cast as a story document carries it (``about`` stays in the bible)."""
    return [
        {key: copy.deepcopy(member[key]) for key in _DOC_CAST_KEYS if key in member}
        for member in content.get("cast") or []
    ]


def doc_places(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The top-level ``places`` of a story document."""
    return [
        {"id": p["id"], "title": dict(p["title"]), "look": p["look"]}
        for p in content.get("places") or []
    ]


def doc_facts(content: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in fact.items() if k in ("en", "fr", "source", "invented")}
        for fact in content.get("facts") or []
    ]


def default_place(content: dict[str, Any], is_kids: bool) -> str:
    """Where a scene with no usable place is set: the bible's first place."""
    places = content.get("places") or []
    if places:
        return str(places[0]["id"])
    return "classroom" if is_kids else "desk"


def mission_of(content: dict[str, Any], module_id: uuid.UUID | str | None) -> dict[str, str] | None:
    missions = content.get("missions")
    if not isinstance(missions, dict) or module_id is None:
        return None
    mission = missions.get(str(module_id))
    return dict(mission) if isinstance(mission, dict) else None


def mission_for(
    content: dict[str, Any],
    module_id: uuid.UUID | str,
    number: int | None,
    title: dict[str, str],
) -> dict[str, str]:
    """The module's mission: the bible's, else one built from the module's title.

    A module added after the bible has none stored; the fallback is
    deterministic, so it never makes a chapter stale, and the stored bible
    (and its digest) is left as it is.
    """
    stored = mission_of(content, module_id)
    if stored:
        return stored
    module = BibleModule(
        module_id if isinstance(module_id, uuid.UUID) else uuid.UUID(str(module_id)),
        int(number or 1),
        {
            "en": title.get("en") or title.get("fr", ""),
            "fr": title.get("fr") or title.get("en", ""),
        },
    )
    return _default_mission(module)


def usable_answer(raw: Any) -> dict[str, Any] | None:
    """The model's bible answer, unwrapped, or ``None`` when it gives nothing usable.

    A lone wrapper key (``{"bible": {...}}``) is opened. An answer with no cast
    member under a known role and no place that passes the checks is not
    usable: stored, it would be the defaults forever.
    """
    if not isinstance(raw, dict):
        return None
    answer = {k: v for k, v in raw.items() if k != "__complete"}
    if "cast" not in answer and "places" not in answer and len(answer) == 1:
        (inner,) = answer.values()
        if isinstance(inner, dict):
            answer = {k: v for k, v in inner.items() if k != "__complete"}
    if not _by_role(answer.get("cast")) and not _given_places(answer.get("places")):
        return None
    return answer


@dataclass(frozen=True)
class StoryBible:
    """A course bible as the generator uses it: its content and digest."""

    content: dict[str, Any]
    digest: str

    @classmethod
    def of(cls, content: dict[str, Any]) -> StoryBible:
        return cls(content=content, digest=bible_digest(content))

    @property
    def is_kids(self) -> bool:
        return self.content.get("audience") == "kids"


def default_bible(is_kids: bool, modules: Sequence[BibleModule] = ()) -> StoryBible:
    """The bible of a module that belongs to no course: never stored."""
    return StoryBible.of(normalise_bible({}, is_kids=is_kids, modules=modules))


# --------------------------------------------------------------------------
# Storage and the one model call
# --------------------------------------------------------------------------


class StoryBibleUnavailable(RuntimeError):
    """The model's answers for the bible could not be read or used."""


class StoryProviderUnavailable(StoryBibleUnavailable):
    """The model could not be called at all — an outage (401, 429, 529, timeout).

    Nothing is stored: an outage never freezes a bible of defaults (#2680).
    """


#: ``story_course_bibles.model`` of a bible made of defaults because the
#: model's answers could not be used (twice): the next story of the course
#: tries once more.
DEFAULTED = "defaulted"
#: ... and once that retry gave unusable answers too: kept (no retry, no
#: churn) until an admin resets it (:func:`reset_defaulted_bible`).
DEFAULTED_KEPT = "defaulted-kept"


async def find_bible(
    session: AsyncSession, course_id: uuid.UUID, *, fresh: bool = False
) -> Any | None:
    """The stored bible row of a course, if any.

    ``fresh``: read from the database even when the session already holds the
    row (after waiting on the creation lock, another worker may have
    replaced it).
    """
    from app.domain.models.story_bible import StoryCourseBible

    statement = select(StoryCourseBible).where(StoryCourseBible.course_id == course_id)
    if fresh:
        statement = statement.execution_options(populate_existing=True)
    return (await session.execute(statement)).scalar_one_or_none()


async def reset_defaulted_bible(session: AsyncSession, course_id: uuid.UUID) -> str | None:
    """An admin's reset of a course's bible of defaults; returns what was removed.

    Only a bible made of defaults (:data:`DEFAULTED`, :data:`DEFAULTED_KEPT`)
    is removed — the next story of the course makes a real one. A real bible
    is never touched here (its art is keyed on it): ``None`` is returned and
    nothing changes. Commits.
    """
    row = await find_bible(session, course_id, fresh=True)
    if row is None or row.model not in (DEFAULTED, DEFAULTED_KEPT):
        return None
    model = row.model
    await session.delete(row)
    await session.commit()
    logger.info("Story bible of defaults reset by an admin", course_id=str(course_id))
    return model


async def find_bible_digest(session: AsyncSession, course_id: uuid.UUID | None) -> str | None:
    """Only the digest of a course's bible: what freshness compares.

    ``None`` for a bible of defaults still waiting for its retry
    (:data:`DEFAULTED`): its stories are not fresh, so the next one retries.
    """
    if course_id is None:
        return None
    from app.domain.models.story_bible import StoryCourseBible

    row = (
        await session.execute(
            select(StoryCourseBible.digest, StoryCourseBible.model).where(
                StoryCourseBible.course_id == course_id
            )
        )
    ).first()
    if row is None or row.model == DEFAULTED:
        return None
    return row.digest


def _lock_key(course_id: uuid.UUID) -> int:
    """A signed 64-bit advisory-lock key from the course id."""
    return int.from_bytes(course_id.bytes[:8], "big", signed=True)


async def _lock(session: AsyncSession, course_id: uuid.UUID) -> None:
    """Serialise bible creation per course, until the transaction ends (PostgreSQL)."""
    try:
        dialect = session.get_bind().dialect.name
    except Exception:  # pragma: no cover - a session without a bind
        dialect = ""
    if dialect == "postgresql":
        await session.execute(select(func.pg_advisory_xact_lock(_lock_key(course_id))))


class StoryBibleService:
    """Makes a course's bible with one model call, once, and reads it after that."""

    #: Readable answers needed; an unreadable or unusable one is asked again once.
    MAX_CALLS = 2

    def __init__(self, claude_service: Any) -> None:
        self.claude_service = claude_service

    async def get_or_create(
        self,
        session: AsyncSession,
        course: Any,
        modules: Sequence[BibleModule],
        *,
        country: str = "",
    ) -> StoryBible:
        """The course's bible; the first call for a course writes it and commits.

        Creation is serialised per course (an advisory lock held until the
        commit), and the row is read again from the database after the lock,
        so two module stories of one course started together make one bible,
        with one model call.

        Two failures are told apart (#2680):

        * **an outage** — the provider cannot be called (401, 429, 529,
          timeout): :class:`StoryProviderUnavailable` is raised at once, after
          one call, and nothing is stored; a bible of defaults waiting for its
          retry keeps waiting. The next story of the course asks again.
        * **unusable answers** — twice an answer that cannot be read or has no
          cast or place: a bible of defaults is stored, marked
          :data:`DEFAULTED`, so the course still gets a story; the next story
          of the course tries once more and replaces it, or keeps it
          (:data:`DEFAULTED_KEPT`) until an admin resets it
          (:func:`reset_defaulted_bible`).
        """
        row = await find_bible(session, course.id)
        if row is not None and row.model != DEFAULTED:
            return StoryBible(content=row.content, digest=row.digest)
        await _lock(session, course.id)
        row = await find_bible(session, course.id, fresh=True)
        if row is not None and row.model != DEFAULTED:
            return StoryBible(content=row.content, digest=row.digest)

        from app.ai.prompts.audience import detect_audience
        from app.domain.models.story_bible import StoryCourseBible

        is_kids = detect_audience(course).is_kids
        try:
            raw = await self._call(course, modules, is_kids=is_kids, country=country)
            model = (
                _str(
                    getattr(self.claude_service, "model", None)
                    or getattr(self.claude_service, "_model", None),
                    100,
                )
                or None
            )
        except StoryProviderUnavailable:
            # Never freeze anything on an outage: not the defaults, not the retry.
            await session.rollback()
            raise
        except StoryBibleUnavailable:
            if row is not None:
                # The one retry of a bible of defaults gave unusable answers too.
                row.model = DEFAULTED_KEPT
                await session.commit()
                logger.warning("Story bible of defaults kept", course_id=str(course.id))
                return StoryBible(content=row.content, digest=row.digest)
            raw, model = {}, DEFAULTED
            logger.warning(
                "Story bible answers unusable: defaults stored", course_id=str(course.id)
            )
        content = normalise_bible(raw, is_kids=is_kids, modules=modules, country=country)
        bible = StoryBible.of(content)
        if row is not None:
            row.content, row.digest, row.model = content, bible.digest, model
        else:
            session.add(
                StoryCourseBible(
                    id=uuid.uuid4(),
                    course_id=course.id,
                    content=content,
                    digest=bible.digest,
                    model=model,
                )
            )
        await session.commit()
        logger.info(
            "Story bible created",
            course_id=str(course.id),
            audience=content["audience"],
            cast=[m["id"] for m in content["cast"]],
            places=[p["id"] for p in content["places"]],
            digest=bible.digest[:12],
            model=model,
        )
        return bible

    async def _call(
        self,
        course: Any,
        modules: Sequence[BibleModule],
        *,
        is_kids: bool,
        country: str,
    ) -> dict[str, Any]:
        """A usable answer, in at most :data:`MAX_CALLS` calls.

        An unreadable or unusable answer is asked again once, then
        :class:`StoryBibleUnavailable`. A provider error (anything but an
        unreadable answer) is an outage: :class:`StoryProviderUnavailable` at
        once — a timeout has already used the provider's whole read timeout,
        so a second call would only push the task past its time limit.
        """
        from app.ai.prompts.story_bible import build_bible_messages
        from app.ai.usage_context import ai_usage_context
        from app.domain.models.ai_usage_event import FEATURE_STORY_GENERATION

        system, user = build_bible_messages(course, modules, is_kids=is_kids, country=country)
        with ai_usage_context(
            FEATURE_STORY_GENERATION, course_id=getattr(course, "id", None), only_if_unset=True
        ):
            from app.domain.services.story_calls import (
                StoryCallTimeout,
                TruncatedResponse,
                concise,
                structured_call,
            )

            message = user
            for attempt in range(self.MAX_CALLS):
                try:
                    raw = await structured_call(self.claude_service, system, message, kind="bible")
                except SoftTimeLimitExceeded:
                    raise
                except StoryCallTimeout as exc:
                    if exc.at_deadline:
                        raise
                    # Past its cap with time left: an outage, nothing stored.
                    raise StoryProviderUnavailable(
                        f"The bible call ran past its cap for course {course.id}"
                    ) from exc
                except TruncatedResponse as exc:
                    # Asked again once, concise (#2702); never at a bigger budget.
                    logger.warning(
                        "Story bible answer cut at max_tokens",
                        attempt=attempt + 1,
                        output_tokens=exc.output_tokens,
                    )
                    message = concise(user)
                    continue
                except ValueError as exc:
                    logger.warning(
                        "Story bible answer unusable", attempt=attempt + 1, error=str(exc)
                    )
                    continue
                except Exception as exc:
                    logger.warning(
                        "Story bible model call failed: provider unavailable",
                        attempt=attempt + 1,
                        error_type=type(exc).__name__,
                        error=str(exc)[:300],
                    )
                    raise StoryProviderUnavailable(
                        f"The model could not be called for course {course.id}:"
                        f" {type(exc).__name__}"
                    ) from exc
                answer = None if isinstance(raw, dict) and raw.get("raw_response") else raw
                answer = usable_answer(answer)
                if answer is not None:
                    return answer
                logger.warning("Story bible answer gave no cast or place", attempt=attempt + 1)
        raise StoryBibleUnavailable(f"No usable story bible for course {course.id}")
