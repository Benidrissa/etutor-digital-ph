"""Neutral lead-ins for the questions of a story (#2710).

A question must be set up: right before it, a line puts the problem to the
learner. In the studied story the mentor said most of those lines (« L'enveloppe
du jury contient une question… »), eleven times in a story. A story with no
mentor cannot rely on him, and a model that forgets the line costs a paid
repair call, so the code writes a line when there is none.

A lead-in is a ``narrate`` step marked ``"leadin": true``: the storyteller's
voice, third person, never the answer, never about the app. There are twelve,
in French and English, and the one a question gets is chosen from its chapter
and its ref (a hash, never ``random``), so the same chapter always gets the same
lines, and two questions in a row never get the same one.

The check (:mod:`story_checks`) accepts any ``say`` line (a short line from any
cast member) or one of these.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.domain.services.story_poe import is_bet

#: ``(en, fr)``. ``{child}`` is the learner's placeholder, as in every line.
LEADINS: tuple[tuple[str, str], ...] = (
    ("Now {child} has to decide.", "C'est à {child} de décider."),
    ("A choice is waiting for {child}.", "Un choix attend {child}."),
    (
        "All eyes turn to {child}. And now?",
        "Tous les yeux se tournent vers {child}. Et maintenant ?",
    ),
    ("It is {child}'s turn to choose.", "C'est au tour de {child} de choisir."),
    ("The moment to choose has come.", "Le moment de choisir est arrivé."),
    (
        "{child} takes a deep breath and thinks.",
        "{child} respire un grand coup et réfléchit.",
    ),
    (
        "Everyone waits for {child}'s answer.",
        "Tout le monde attend la réponse de {child}.",
    ),
    ("{child} looks closely before deciding.", "{child} regarde bien avant de décider."),
    ("Which way now? {child} has to pick.", "Quelle direction prendre ? {child} doit choisir."),
    ("A tricky moment. {child} thinks it over.", "Un moment délicat. {child} y réfléchit."),
    ("{child} stops and weighs it up.", "{child} s'arrête et pèse le pour et le contre."),
    ("{child} has to settle it, and fast.", "{child} doit trancher, et vite."),
)


def leadin_index(key: str, offset: int = 0) -> int:
    """A stable index in :data:`LEADINS` for ``key`` (``offset`` steps on from it)."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") + offset) % len(LEADINS)


def leadin_step(key: str, offset: int = 0) -> dict[str, Any]:
    """The narrate step of the lead-in chosen for ``key``."""
    en, fr = LEADINS[leadin_index(key, offset)]
    return {"type": "narrate", "en": en, "fr": fr, "leadin": True}


def leadin_keys(step: dict[str, Any]) -> set[tuple[str, str]]:
    """``(lang, line key)`` of a lead-in step (none for any other step), as the
    module validator compares lines."""
    if not is_leadin(step):
        return set()
    from app.domain.services.story_course_validator import line_key

    return {
        (lang, line_key(step.get(lang))) for lang in ("en", "fr") if isinstance(step.get(lang), str)
    }


def pick_leadin(key: str, avoid: set[tuple[str, str]], offset: int = 0) -> dict[str, Any]:
    """The lead-in for ``key`` that is not in ``avoid`` (the first of the twelve, in
    the hash's order, when every one is taken)."""
    first = leadin_step(key, offset)
    for shift in range(len(LEADINS)):
        step = leadin_step(key, offset + shift)
        if not leadin_keys(step) & avoid:
            return step
    return first


def is_leadin(step: dict[str, Any] | None) -> bool:
    return bool(step and step.get("leadin"))


def _closeup(step: dict[str, Any]) -> bool:
    return step.get("type") == "show" and step.get("visual") == "prop"


def _situation(step: dict[str, Any]) -> bool:
    return step.get("type") == "concept" and str(step.get("id", "")).startswith("situation-")


def add_leadins(
    scenes: list[dict[str, Any]], salt: str, *, avoid: set[tuple[str, str]] | None = None
) -> int:
    """Put a lead-in before every run of questions that has no line before it.

    A run is its questions and their situation cards, in one scene; what comes
    before it (a close-up is seen through) must be a ``say`` line or a lead-in.
    Returns how many were added. Deterministic: the same scenes and ``salt``
    (the chapter's unit) always give the same lines. ``avoid`` (#2713, the slot
    builder's chapters): the keys of the lead-ins earlier chapters already have;
    one of those, or one already put in this chapter, is never chosen (the module
    validator refuses a line told twice). ``None``: chosen as ever.
    """
    taken = set(avoid) if avoid is not None else None
    added = 0
    for scene in scenes:
        out: list[dict[str, Any]] = []
        previous: dict[str, Any] | None = None
        in_run = False
        for step in scene.get("steps") or []:
            if _closeup(step) or is_bet(step):
                # A close-up is seen through; a bet (#2711) is set up by the picture
                # before it and needs no lead-in line.
                out.append(step)
                continue
            starts = step.get("type") == "ask" or _situation(step)
            if starts and not in_run:
                if previous is None or not (previous.get("type") == "say" or is_leadin(previous)):
                    key = f"{salt}:{step.get('ref') or step.get('id') or added}"
                    if taken is None:
                        lead = leadin_step(key, added)
                    else:
                        lead = pick_leadin(key, taken, added)
                        taken |= leadin_keys(lead)
                    out.append(lead)
                    added += 1
                in_run = True
            elif not starts:
                in_run = False
            out.append(step)
            previous = step
        scene["steps"] = out
    return added
