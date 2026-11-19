"""Predict, observe, name (#2711): the beat of a story told from a NEW plan.

The studied story answered first and asked after: a card, then a multiple-choice
question. A new story bets first. For a lesson idea that has evidence, a beat
plays in this order:

1. the real stimulus (a ``show`` of the course figure or lesson illustration);
2. a short hook (the screenwriter's lines);
3. **predict**: an ungraded bet, two or three chips, the stimulus in view. It is
   an ``ask`` marked ``predict: true`` on a question of its own that carries
   ``points: 0`` (an older player plays it as a plain multiple-choice question);
4. **observe**: a demo (``compare``, ``annotate``, ``sort``, ``timeline``), a
   ``show`` marked ``bet`` so the player puts the learner's bet next to what it
   shows;
5. a reaction keyed to the bet (``question.reveal.right`` / ``.wrong``, shown
   by the player under the demo);
6. the card, with the beat's figure beside its words (``media``);
7. the bank question, with the stimulus as a thumbnail (``question.stimulus``);
8. the transfer question, the same way.

The screenwriter writes the *words* of a bet and a demo (a ``predict`` step of
its screenplay); the code decides everything else: it checks the demo's data,
takes the verdict from that data (never from pixels), numbers the bet, puts the
bet and its demo before the card that names the idea, and sets the pictures.
Anything the model gets wrong here is cleaned up or left out and reported as a
``lint``: never a blocking issue, so it never costs a paid repair call.

A story told from a legacy plan (no ``cast_policy``) is told exactly as before:
none of this runs for it.
"""

from __future__ import annotations

import copy
import math
from typing import Any

#: The ``plan`` key #2710 added to every NEW plan: its presence is the marker of
#: "this story is told the new way" (no version is bumped for it).
NEW_PLAN_KEY = "cast_policy"

DEMO_KINDS = ("compare", "annotate", "sort", "timeline")
SCALES = ("ruler", "bars", "score")
REGIONS = {"halves": 2, "thirds": 3}
LABEL_LIMIT = 40
PROMPT_LIMIT = 160
OPTION_LIMIT = 50
REACTION_LIMIT = 110
UNIT_LIMIT = 8
MAX_VALUE = 100_000
CHOICE_IDS = ("a", "b", "c")
LANGS = ("en", "fr")

#: What the player may be told about an outcome of ``compare``.
OUTCOMES = ("a", "b", "equal")


def is_new_plan(plan: Any) -> bool:
    """Whether ``plan`` is a NEW plan (#2710): the one that carries a ``cast_policy``."""
    return isinstance(plan, dict) and isinstance(plan.get(NEW_PLAN_KEY), dict)


def is_bet(step: dict[str, Any] | None) -> bool:
    """A prediction: an ``ask`` marked ``predict``."""
    return bool(step and step.get("type") == "ask" and step.get("predict"))


def is_demo(step: dict[str, Any] | None) -> bool:
    """The observation of a bet: a ``show`` of a demo primitive."""
    return bool(step and step.get("type") == "show" and step.get("visual") in DEMO_KINDS)


# --------------------------------------------------------------------------
# Small readers
# --------------------------------------------------------------------------


def _text(value: Any, limit: int) -> dict[str, str] | None:
    """``{"en", "fr"}`` of non-empty strings, cut to ``limit`` characters; else ``None``."""
    if not isinstance(value, dict):
        return None
    out: dict[str, str] = {}
    for lang in LANGS:
        raw = value.get(lang)
        if not isinstance(raw, str) or not raw.strip():
            return None
        out[lang] = " ".join(raw.split())[:limit].rstrip()
    return out


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= MAX_VALUE:
        return None
    return float(value)


def _tidy(value: float) -> int | float:
    return int(value) if value == int(value) else round(value, 3)


def _whole(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return None
    return value


# --------------------------------------------------------------------------
# The demos: checked, cleaned, and their verdict read from the data
# --------------------------------------------------------------------------


def demo_problem(visual: str, params: Any) -> str | None:
    """Why the player cannot draw demo ``visual`` with ``params``, or ``None``."""
    return None if clean_demo(visual, params) is not None else _why(visual, params)


def _why(visual: str, params: Any) -> str:
    return f"{visual} needs well-formed params (see its description): {_hint(visual)}"


def _hint(visual: str) -> str:
    return {
        "compare": "values [a, b] and labels [{en, fr}, {en, fr}]",
        "annotate": "labels (one per region), expected (the region's number)",
        "sort": "items [{label, bin}] and bins [{en, fr}]",
        "timeline": "events [{label, at}]",
    }.get(visual, "known params")


def clean_demo(visual: str, params: Any, *, image: dict[str, Any] | None = None) -> dict | None:
    """The params of a demo as the player reads them, or ``None`` when they cannot be.

    Everything the model may get wrong is repaired here, never reported as an
    error: ``equal`` is recomputed from ``values``, a region count is read from
    the labels, extra keys are dropped. ``image`` is the figure an ``annotate``
    demo sits on (the code's choice: the stimulus it follows).
    """
    if not isinstance(params, dict):
        return None
    if visual == "compare":
        values = params.get("values")
        labels = params.get("labels")
        if not (isinstance(values, list) and len(values) == 2 and isinstance(labels, list)):
            return None
        numbers = [_number(v) for v in values]
        names = [_text(label, LABEL_LIMIT) for label in labels[:2]]
        if None in numbers or len(names) != 2 or None in names:
            return None
        first, second = numbers  # type: ignore[misc]
        scale = params.get("scale") if params.get("scale") in SCALES else "bars"
        out: dict[str, Any] = {
            "values": [_tidy(first), _tidy(second)],
            "labels": names,
            "scale": scale,
            # The verdict comes from the numbers, whatever the model wrote.
            "equal": first == second,
        }
        unit = params.get("unit")
        if isinstance(unit, str) and unit.strip():
            out["unit"] = unit.strip()[:UNIT_LIMIT]
        return out
    if visual == "annotate":
        labels = params.get("labels")
        if not isinstance(labels, list):
            return None
        names = [_text(label, LABEL_LIMIT) for label in labels]
        wanted = REGIONS.get(str(params.get("regions")), len(names))
        if wanted not in (2, 3) or len(names) != wanted or None in names:
            return None
        expected = _whole(params.get("expected"), 1, wanted)
        if expected is None:
            return None
        out = {
            "regions": "halves" if wanted == 2 else "thirds",
            "labels": names,
            "expected": expected,
        }
        figure = image or {}
        for key in ("source_image_id", "generated_image_id"):
            if isinstance(figure.get(key), str) and figure[key]:
                out[key] = figure[key]
        for key in ("source_image_id", "generated_image_id"):
            if isinstance(params.get(key), str) and params[key] and key not in out:
                out[key] = params[key]
        if "source_image_id" in out and "generated_image_id" in out:
            del out["generated_image_id"]
        if "source_image_id" not in out and "generated_image_id" not in out:
            return None  # regions of nothing: no picture, no demo
        if isinstance(figure.get("alt"), dict):
            out["alt"] = figure["alt"]
        return out
    if visual == "sort":
        bins = params.get("bins")
        items = params.get("items")
        if not (isinstance(bins, list) and isinstance(items, list)):
            return None
        box = [_text(b, LABEL_LIMIT) for b in bins]
        if not 2 <= len(box) <= 3 or None in box:
            return None
        rows = []
        for item in items[:6]:
            label = _text(item.get("label") if isinstance(item, dict) else None, LABEL_LIMIT)
            at = _whole(item.get("bin") if isinstance(item, dict) else None, 1, len(box))
            if label is None or at is None:
                return None
            rows.append({"label": label, "bin": at})
        if len(rows) < 2 or len({r["bin"] for r in rows}) < 2:
            return None
        return {"bins": box, "items": rows}
    if visual == "timeline":
        events = params.get("events")
        if not isinstance(events, list) or not 2 <= len(events) <= 6:
            return None
        rows = []
        for event in events:
            label = _text(event.get("label") if isinstance(event, dict) else None, LABEL_LIMIT)
            at = _number(event.get("at") if isinstance(event, dict) else None)
            if label is None or at is None:
                return None
            rows.append({"label": label, "at": _tidy(at)})
        if len({r["at"] for r in rows}) != len(rows):
            return None
        return {"events": rows}
    return None


def demo_outcome(visual: str, params: dict[str, Any]) -> str | int | None:
    """The verdict a demo's data gives: ``compare`` → a/b/equal, ``annotate`` → region number."""
    if visual == "compare":
        first, second = params["values"]
        return "equal" if first == second else "a" if first > second else "b"
    if visual == "annotate":
        return int(params["expected"])
    return None


# --------------------------------------------------------------------------
# A bet
# --------------------------------------------------------------------------


class Bet:
    """One prediction, built: its question, its ask, its demo (all documents)."""

    def __init__(
        self,
        question: dict[str, Any],
        ask: dict[str, Any],
        demo: dict[str, Any],
        idea: int | None,
    ) -> None:
        self.question = question
        self.ask = ask
        self.demo = demo
        self.idea = idea


def _options(raw: Any, visual: str, demo: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The chips of a bet: 2 or 3 ``{en, fr}``, each maybe naming its outcome (``is``)."""
    if visual == "annotate":
        # The chips ARE the regions: the model cannot disagree with its own figure.
        return [dict(label) for label in demo["labels"]]
    if not isinstance(raw, list) or not 2 <= len(raw) <= 3:
        return None
    options = []
    for item in raw:
        text = _text(item, OPTION_LIMIT)
        if text is None:
            return None
        if isinstance(item, dict) and item.get("is") in OUTCOMES:
            text["is"] = item["is"]
        options.append(text)
    return options


def build_bet(
    raw: dict[str, Any],
    number: int,
    *,
    image: dict[str, Any] | None,
    lints: list[tuple[str, str]],
    path: str,
) -> Bet | None:
    """A bet from the screenwriter's ``predict`` step, or ``None`` (reported in ``lints``).

    ``lints`` gets ``(code, message)`` pairs: a bet that cannot be built is left
    out, the story is told without it.
    """
    demo_raw = raw.get("demo") if isinstance(raw.get("demo"), dict) else {}
    visual = str(demo_raw.get("visual") or "")
    if visual not in DEMO_KINDS:
        lints.append(("bet_dropped", f"{path}: the demo is not one of {', '.join(DEMO_KINDS)}"))
        return None
    params = clean_demo(visual, demo_raw.get("params"), image=image)
    if params is None:
        lints.append(("bet_dropped", f"{path}: the {visual} demo's data cannot be drawn"))
        return None
    prompt = _text(
        {lang: raw.get(lang) for lang in LANGS} if "en" in raw else raw.get("prompt"),
        PROMPT_LIMIT,
    )
    options = _options(raw.get("options"), visual, params)
    if prompt is None or options is None:
        lints.append(("bet_dropped", f"{path}: a bet needs its question and 2 or 3 options"))
        return None
    answer = _answer(raw, visual, params, options)
    if answer is None:
        lints.append(("bet_dropped", f"{path}: the right option cannot be told from the data"))
        return None
    right = _text(raw.get("react_right"), REACTION_LIMIT)
    wrong = _text(raw.get("react_wrong"), REACTION_LIMIT)
    if right is None or wrong is None:
        lints.append(("bet_reaction_missing", f"{path}: write react_right and react_wrong"))
        fallback = {"en": "Look at what it shows.", "fr": "Regarde ce que cela montre."}
        right, wrong = right or fallback, wrong or fallback
    qid = f"p{number}"
    question: dict[str, Any] = {
        "id": qid,
        "type": "choice",
        "prompt": prompt,
        "choices": [
            {"id": CHOICE_IDS[i], "en": o["en"], "fr": o["fr"]} for i, o in enumerate(options)
        ],
        "answer": CHOICE_IDS[answer],
        "traps": [],
        "hints": [],
        "points": 0,
        "predict": True,
        "reveal": {"right": right, "wrong": wrong},
    }
    idea = _idea(raw.get("teaches"))
    ask: dict[str, Any] = {"type": "ask", "ref": qid, "predict": True}
    if idea is not None:
        ask["teaches"] = idea
    demo: dict[str, Any] = {"type": "show", "visual": visual, "params": params, "bet": qid}
    caption = _text(demo_raw.get("caption"), 90)
    if caption:
        demo["caption"] = caption
    return Bet(question, ask, demo, idea)


def _answer(
    raw: dict[str, Any], visual: str, params: dict[str, Any], options: list[dict[str, Any]]
) -> int | None:
    """The 0-based index of the right chip, from the demo's data when it speaks."""
    outcome = demo_outcome(visual, params)
    if visual == "annotate":
        return int(outcome) - 1  # type: ignore[arg-type]
    if visual == "compare":
        named = [i for i, o in enumerate(options) if o.get("is") == outcome]
        if len(named) == 1:
            return named[0]
    expected = _whole(raw.get("expected"), 1, len(options))
    return None if expected is None else expected - 1


def _idea(value: Any) -> int | None:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, str) and item.strip().isdigit():
            item = int(item.strip())
        if isinstance(item, int) and not isinstance(item, bool) and item > 0:
            return item
    return None


# --------------------------------------------------------------------------
# The beat's order and its pictures
# --------------------------------------------------------------------------


def _flat(scenes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int, dict[str, Any]]]:
    return [(scene, i, step) for scene in scenes for i, step in enumerate(scene["steps"])]


def _taught(step: dict[str, Any]) -> set[int]:
    value = step.get("teaches")
    values = value if isinstance(value, list) else [value]
    return {v for v in values if isinstance(v, int) and not isinstance(v, bool) and v > 0}


def _is_card(step: dict[str, Any]) -> bool:
    return step.get("type") == "concept" and not str(step.get("id", "")).startswith("situation-")


def _is_figure(step: dict[str, Any]) -> bool:
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    return (
        step.get("type") == "show"
        and step.get("visual") == "image"
        and bool(params.get("source_image_id") or params.get("generated_image_id"))
    )


def figure_of(step: dict[str, Any]) -> dict[str, Any]:
    """The picture ids (and alt text) a figure ``show`` names, as a stimulus."""
    params = step.get("params") or {}
    out: dict[str, Any] = {}
    for key in ("source_image_id", "generated_image_id"):
        if params.get(key):
            out[key] = params[key]
            break
    if out and isinstance(params.get("alt"), dict):
        out["alt"] = copy.deepcopy(params["alt"])
    if out and isinstance(step.get("caption"), dict):
        out["caption"] = copy.deepcopy(step["caption"])
    return out


def preceding_figure(scenes: list[dict[str, Any]], scene: dict[str, Any], index: int) -> dict:
    """The figure the scene showed most recently before ``scene.steps[index]`` (else ``{}``)."""
    for step in reversed(scene["steps"][:index]):
        if _is_figure(step):
            return figure_of(step)
    return {}


def _index_of(steps: list[dict[str, Any]], step: dict[str, Any]) -> int:
    return next(i for i, s in enumerate(steps) if s is step)


def order_bets(scenes: list[dict[str, Any]]) -> int:
    """Put every bet (and its demo) before the card that names its idea. Returns how many moved.

    A bet written after its card is no bet: the answer was given. It moves
    right before the card.
    """
    moved = 0
    for bet_scene, _i, step in list(_flat(scenes)):
        if not is_bet(step) or not step.get("teaches"):
            continue
        idea = step["teaches"]
        order = _flat(scenes)
        card_at = next(
            (n for n, (_, _, s) in enumerate(order) if _is_card(s) and idea in _taught(s)), None
        )
        bet_at = next((n for n, (_, _, s) in enumerate(order) if s is step), None)
        if card_at is None or bet_at is None or bet_at < card_at:
            continue
        card_scene, _j, card = order[card_at]
        position = _index_of(bet_scene["steps"], step)
        group = [step]
        if position + 1 < len(bet_scene["steps"]) and is_demo(bet_scene["steps"][position + 1]):
            group.append(bet_scene["steps"][position + 1])
        bet_scene["steps"][position : position + len(group)] = []
        at = _index_of(card_scene["steps"], card)
        card_scene["steps"][at:at] = group
        moved += 1
    return moved


def attach_card_media(scenes: list[dict[str, Any]]) -> int:
    """The picture beside each card: the figure its scene showed. Returns how many got one.

    A figure only: a demo is something to DO, and the card is where the idea is
    named, so it never carries one.
    """
    attached = 0
    for scene in scenes:
        for index, step in enumerate(scene["steps"]):
            if not _is_card(step) or step.get("media"):
                continue
            figure = preceding_figure(scenes, scene, index)
            if figure:
                step["media"] = {"visual": "image", "params": figure}
                attached += 1
    return attached


def set_stimuli(
    scenes: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    exercises: list[dict[str, Any]],
    ideas: dict[str, int | None],
) -> int:
    """``stimulus`` on each question and exercise, from the beat that taught its idea.

    A question's stimulus is the picture of the card that names its idea
    (``ideas``: question id → idea number), else the figure its scene showed
    before it. An exercise takes the figure shown most recently before it.
    A bet is shown over its own stimulus by the player and gets none here.
    Only a picture the story SHOWS before the question can be its stimulus.
    Returns how many were set.
    """
    by_id = {q["id"]: q for q in questions}
    ex_by_id = {e["id"]: e for e in exercises}
    cards: dict[int, dict[str, Any]] = {}
    for _scene, _i, step in _flat(scenes):
        if _is_card(step) and isinstance(step.get("media"), dict):
            media = step["media"]
            if media.get("visual") == "image" and media.get("params"):
                for idea in _taught(step):
                    cards.setdefault(idea, dict(media["params"]))
    seen: list[dict[str, Any]] = []  # figures shown so far, in played order
    set_count = 0
    for scene, index, step in _flat(scenes):
        if _is_figure(step):
            seen.append(figure_of(step))
            continue
        if step.get("type") not in ("ask", "photo") or step.get("predict"):
            continue
        target = (
            by_id.get(step.get("ref")) if step["type"] == "ask" else ex_by_id.get(step.get("ref"))
        )
        if target is None or target.get("stimulus"):
            continue
        wanted = cards.get(ideas.get(str(step.get("ref"))) or 0) if step["type"] == "ask" else None
        pick = wanted if wanted and any(_same(wanted, s) for s in seen) else None
        if pick is None and seen:
            nearby = preceding_figure(scenes, scene, index)
            pick = nearby or (seen[-1] if step["type"] == "photo" else {})
        if pick:
            target["stimulus"] = {
                k: copy.deepcopy(v) for k, v in pick.items() if k in _STIMULUS_KEYS
            }
            set_count += 1
    return set_count


_STIMULUS_KEYS = ("source_image_id", "generated_image_id", "alt", "caption")


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return any(a.get(k) and a.get(k) == b.get(k) for k in ("source_image_id", "generated_image_id"))


def stimulus_gaps(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """``(path, id)`` of each stimulus whose picture is not shown before its question.

    Played order: the document's chapters, scenes and steps in order. Used by
    the metrics (warnings): a thumbnail of a picture the learner never saw.
    """
    shown: set[str] = set()
    questions = {q.get("id"): q for q in doc.get("questions") or [] if isinstance(q, dict)}
    exercises = {e.get("id"): e for e in doc.get("exercises") or [] if isinstance(e, dict)}
    gaps: list[tuple[str, str]] = []
    for chapter in doc.get("chapters") or []:
        for scene in chapter.get("scenes") or []:
            for step in scene.get("steps") or []:
                if _is_figure(step):
                    for key in ("source_image_id", "generated_image_id"):
                        if (step.get("params") or {}).get(key):
                            shown.add(str(step["params"][key]))
                    continue
                if step.get("type") not in ("ask", "photo"):
                    continue
                source = (questions if step["type"] == "ask" else exercises).get(step.get("ref"))
                stimulus = source.get("stimulus") if isinstance(source, dict) else None
                if not isinstance(stimulus, dict):
                    continue
                ids = [
                    str(stimulus[k])
                    for k in ("source_image_id", "generated_image_id")
                    if stimulus.get(k)
                ]
                if ids and not any(i in shown for i in ids):
                    gaps.append((f"{step['type']}:{step.get('ref')}", ids[0]))
    return gaps
