"""One neutral storyboard renderer for the paper test (#2737).

The stored chapter (``story-course/1``) and a director script are both turned
into the same list of scenes, then printed by the same template, with no art:
who is on stage, who says what, what is shown, pointed at or run on a machine,
the questions. A reader sees the same layout for both and cannot tell from the
form which one is the new one. The pairs are then labelled A and B in a random
order; the key stays apart until the readers have voted.

No model, no database. Pure functions.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from story_script_grammar import MACROS, Header, Statement

#: Stored cast ids that are not role words.
_ROLE_OF = {"margo": "tutor"}
LABELS = ("A", "B")


@dataclass
class Beat:
    """One line of the storyboard: a kind, an optional speaker, a text and a detail."""

    kind: str  # say | mistake | narrate | show | machine | point | card | ask | open | close | bet | game | note
    who: str = ""
    text: str = ""
    detail: str = ""


@dataclass
class Scene:
    place: str
    cast: list[str]
    beats: list[Beat] = field(default_factory=list)


def _text(value: Any, language: str) -> str:
    if isinstance(value, dict):
        value = value.get(language) or next(iter(value.values()), "")
    return " ".join(str(value or "").split())


# -- the stored chapter ----------------------------------------------------------------


def scenes_from_stored(content: dict[str, Any], language: str) -> list[Scene]:
    """The scenes of a stored chapter document (every chapter of the document, in order)."""
    cast = {m.get("id"): _ROLE_OF.get(m.get("id"), m.get("id")) for m in content.get("cast") or []}
    places = {
        p.get("id"): _text(p.get("title"), language) or str(p.get("id"))
        for p in content.get("places") or []
    }
    props = {
        p.get("id"): _text(p.get("label"), language) or str(p.get("id"))
        for p in content.get("props") or []
    }
    questions = {q.get("id"): q for q in content.get("questions") or [] if isinstance(q, dict)}
    scenes: list[Scene] = []
    for chapter in content.get("chapters") or []:
        for raw in chapter.get("scenes") or []:
            scene = Scene(
                places.get(raw.get("place"), str(raw.get("place"))),
                [str(cast.get(c, c)) for c in raw.get("cast") or []],
            )
            for step in raw.get("steps") or []:
                scene.beats.extend(_stored_beats(step, cast, props, questions, language))
            scenes.append(scene)
    return scenes


def _stored_beats(step, cast, props, questions, language) -> list[Beat]:
    kind = step.get("type")
    pointed = ", ".join(str(props.get(p, p)) for p in step.get("props") or [])
    if kind == "narrate":
        return [Beat("narrate", text=_text(step.get(language), language))]
    if kind == "say":
        who = str(cast.get(step.get("who"), step.get("who")))
        return [
            Beat(
                "say",
                who,
                _text(step.get(language), language),
                f"points at {pointed}" if pointed else "",
            )
        ]
    if kind == "concept":
        rows = " / ".join(str(r) for r in step.get(language) or [])
        return [Beat("card", text=_text(step.get("title"), language), detail=rows)]
    if kind == "ask":
        q = questions.get(step.get("ref")) or {}
        return [Beat("ask", text=_text(q.get("prompt"), language))]
    if kind == "show" and step.get("visual") == "prop":
        return [Beat("show", text=str(props.get((step.get("params") or {}).get("prop"), "")))]
    if kind == "show":
        return [
            Beat(
                "machine",
                text=str(step.get("visual") or "figure"),
                detail=_text(step.get("caption"), language),
            )
        ]
    if kind == "game":
        return [Beat("game")]
    if kind == "photo":
        return [Beat("note", text="a task on paper")]
    return [Beat("note", text=str(kind))]


# -- a script ---------------------------------------------------------------------------


def _describe_machine(stmt: Statement) -> str:
    data = " ".join(f"{k}={v}" for k, v in stmt.named.items())
    return data


def scenes_from_script(
    statements: list[Statement], header: Header, language: str | None = None
) -> list[Scene]:
    """The scenes of a parsed script. Statements that failed to parse are not shown."""
    index = 0
    if language and language in header.languages:
        index = header.languages.index(language)
    scenes: list[Scene] = []
    for stmt in statements:
        if stmt.macro not in MACROS:
            continue
        text = (
            stmt.texts[index] if len(stmt.texts) > index else (stmt.texts[0] if stmt.texts else "")
        )
        a0 = stmt.args[0] if stmt.args else ""
        if stmt.macro == "scene":
            scenes.append(Scene(a0, [c for c in stmt.named.get("cast", "").split(",") if c]))
            continue
        if not scenes:
            scenes.append(Scene("?", []))
        beats = scenes[-1].beats
        if stmt.macro in ("say", "mistake"):
            beats.append(
                Beat(
                    stmt.macro,
                    a0,
                    text,
                    f"mood {stmt.named['mood']}" if "mood" in stmt.named else "",
                )
            )
        elif stmt.macro in ("narrate", "teaser"):
            beats.append(
                Beat("narrate", text=text, detail="next" if stmt.macro == "teaser" else "")
            )
        elif stmt.macro == "show":
            beats.append(Beat("show", text=header.objects.get(a0, a0)))
        elif stmt.macro == "machine":
            beats.append(Beat("machine", text=a0, detail=_describe_machine(stmt)))
        elif stmt.macro == "point":
            beats.append(Beat("point", a0, stmt.named.get("target", "")))
        elif stmt.macro == "card":
            beats.append(Beat("card", text=header.cards.get(a0, a0)))
        elif stmt.macro == "ask":
            for ref in stmt.args:
                beats.append(Beat("ask", text=header.quiz.get(ref, ref)))
        elif stmt.macro in ("open", "close", "bet", "cliff", "recap"):
            beats.append(Beat(stmt.macro, text=text or header.opens.get(a0, ""), detail=a0))
        elif stmt.macro in ("game", "reward"):
            beats.append(Beat(stmt.macro))
    return scenes


# -- the one template ---------------------------------------------------------------------


def render(scenes: list[Scene]) -> str:
    """The same neutral layout for every storyboard."""
    out: list[str] = []
    for number, scene in enumerate(scenes, start=1):
        out.append(f"Scene {number} - {scene.place} - on stage: {', '.join(scene.cast) or '?'}")
        for beat in scene.beats:
            out.append("  " + _line(beat))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _line(beat: Beat) -> str:
    detail = f"  ({beat.detail})" if beat.detail else ""
    if beat.kind in ("say", "mistake"):
        mark = "  [wrong idea]" if beat.kind == "mistake" else ""
        return f"{beat.who}: {beat.text}{mark}{detail}"
    if beat.kind == "narrate":
        return f"(narration) {beat.text}{detail}"
    if beat.kind == "show":
        return f"[on stage: {beat.text}]"
    if beat.kind == "machine":
        return f"[picture: {beat.text}{detail}]"
    if beat.kind == "point":
        return f"[{beat.who} points at {beat.text}]"
    if beat.kind == "card":
        return f"[card: {beat.text}{detail}]"
    if beat.kind == "ask":
        return f"[question for the learner: {beat.text}]"
    if beat.kind == "open":
        return f"[a question is raised: {beat.text}]"
    if beat.kind == "close":
        return f"[the question is answered: {beat.detail}]"
    if beat.kind == "bet":
        return "[the learner bets before the answer is shown]"
    if beat.kind == "game":
        return "[a game]"
    if beat.kind == "reward":
        return "[a reward]"
    return f"[{beat.kind}: {beat.text}]"


def storyboard_stored(content: dict[str, Any], language: str) -> str:
    return render(scenes_from_stored(content, language))


def storyboard_script(
    lines_or_statements: list[Statement], header: Header, language: str | None = None
) -> str:
    return render(scenes_from_script(lines_or_statements, header, language))


# -- the blind pairs ------------------------------------------------------------------------

REVIEW_QUESTIONS = (
    "Which chapter is the better chapter (A or B)?",
    "In which does the picture show what is said (A, B, both, neither)?",
    "Do you see a fact that is wrong (write the line)?",
)


def blind_pairs(
    pairs: list[tuple[str, str, str]], seed: int
) -> tuple[str, dict[str, dict[str, str]]]:
    """``pairs`` is ``[(chapter_id, stored_board, new_board)]``.

    Returns the sheet readers get (A and B in random order per pair, no hint
    of which is which) and the key ``{chapter_id: {"A": "stored"|"new", "B": ...}}``
    to keep apart until every reader has voted.
    """
    rng = random.Random(seed)
    order = list(range(len(pairs)))
    rng.shuffle(order)
    sheet: list[str] = ["# Blind review of story chapters", ""]
    sheet += [f"For each pair: {' / '.join(REVIEW_QUESTIONS)}", ""]
    key: dict[str, dict[str, str]] = {}
    for number, i in enumerate(order, start=1):
        chapter_id, stored, new = pairs[i]
        swap = rng.random() < 0.5
        first, second = (new, stored) if swap else (stored, new)
        key[chapter_id] = {"A": "new" if swap else "stored", "B": "stored" if swap else "new"}
        sheet += [
            f"## Pair {number} (ref {chapter_id[:8]})",
            "",
            "### Chapter A",
            "",
            first,
            "### Chapter B",
            "",
            second,
            "",
        ]
    return "\n".join(sheet), key


def tally(key: dict[str, dict[str, str]], votes: dict[str, list[str]]) -> dict[str, Any]:
    """The new chapter wins a pair when the majority of its readers chose it.

    ``votes`` is ``{chapter_id: ["A", "B", "A"]}``, one entry per reader.
    """
    wins, detail = 0, {}
    for chapter_id, mapping in key.items():
        picks = [mapping.get(v) for v in votes.get(chapter_id, []) if v in mapping]
        new = sum(1 for p in picks if p == "new")
        won = bool(picks) and new * 2 > len(picks)
        wins += int(won)
        detail[chapter_id] = {"new": new, "readers": len(picks), "won": won}
    return {
        "pairs": len(key),
        "new_wins": wins,
        "passes": wins >= 4 and len(key) == 6,
        "detail": detail,
    }


def dump_key(key: dict[str, dict[str, str]]) -> str:
    return json.dumps(key, indent=1, sort_keys=True)
