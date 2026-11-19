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


def is_leadin(step: dict[str, Any] | None) -> bool:
    return bool(step and step.get("leadin"))


def _closeup(step: dict[str, Any]) -> bool:
    return step.get("type") == "show" and step.get("visual") == "prop"


def _situation(step: dict[str, Any]) -> bool:
    return step.get("type") == "concept" and str(step.get("id", "")).startswith("situation-")


def add_leadins(scenes: list[dict[str, Any]], salt: str) -> int:
    """Put a lead-in before every run of questions that has no line before it.

    A run is its questions and their situation cards, in one scene; what comes
    before it (a close-up is seen through) must be a ``say`` line or a lead-in.
    Returns how many were added. Deterministic: the same scenes and ``salt``
    (the chapter's unit) always give the same lines.
    """
    added = 0
    for scene in scenes:
        out: list[dict[str, Any]] = []
        previous: dict[str, Any] | None = None
        in_run = False
        for step in scene.get("steps") or []:
            if _closeup(step):
                out.append(step)
                continue
            starts = step.get("type") == "ask" or _situation(step)
            if starts and not in_run:
                if previous is None or not (previous.get("type") == "say" or is_leadin(previous)):
                    lead = leadin_step(
                        f"{salt}:{step.get('ref') or step.get('id') or added}", added
                    )
                    out.append(lead)
                    added += 1
                in_run = True
            elif not starts:
                in_run = False
            out.append(step)
            previous = step
        scene["steps"] = out
    return added
