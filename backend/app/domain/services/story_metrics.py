"""What a story shows, and how it talks: measured on the stored document (#2708).

Pure functions over the story's JSON (``story-course/1``), shared by the
validator (warnings and ``checks.story_metrics``) and by the read-only audit
script (``scripts/audit_story_assets.py``). Nothing here reads a database or
changes a document, and nothing is a blocking error: a text-only course must
still publish.

An educational prop is one the learner must see (a close-up). The player
always plays its close-up (a name card when there is no picture), so these
checks tell the author what is missing, they do not decide what plays.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.domain.services.story_poe import is_bet, stimulus_gaps
from app.domain.services.story_props import fold

LINE_TYPES = ("say", "narrate")

#: The warnings of this module (never errors).
ASSET_CODES = frozenset(
    {"educational_prop_without_art", "dangling_deixis", "unseen_stimulus", "lang_integrity"}
)
#: #2711: only a story with a stimulus on its questions, or told with bets, can raise these.
POE_CODES = frozenset({"stimulus_not_shown", "few_acts"})

#: A line that points at something: "look", "regardez", "voici"...
DEIXIS_RE = re.compile(
    r"\blook\b|\bhere(?:'s| is| are)\b|\bthere it is\b|\bcheck (?:this|it) out\b"
    r"|\bregard(?:e|ez|ons)\b|\bvoici\b|\bvoil[àa]\b|\bvoyez\b|\bregarde-moi\b",
    re.IGNORECASE,
)
#: How far a close-up may be from the line that says "look" (steps, both ways).
DEIXIS_WINDOW = 2

#: French words an English line never has (two or more in one string flag it).
#: Left out on purpose: words that are English too ("son", "ton", "pour", "pas").
_FRENCH_STOPWORDS = frozenset(
    [
        "le",
        "les",
        "des",
        "une",
        "est",
        "sont",
        "dans",
        "avec",
        "qui",
        "que",
        "vous",
        "nous",
        "je",
        "cette",
        "mais",
        "ont",
        "du",
        "aux",
        "ça",
        "où",
        "très",
        "ta",
        "tes",
        "ses",
        "elle",
        "ils",
        "elles",
        "être",
        "c'est",
        "qu'est",
    ]
)
_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)
#: Strings shorter than this are not judged ("Le Caire").
_MIN_LANG_WORDS = 3

_ARTICLE_RE = re.compile(r"^(?:the|a|an|some|le|la|les|l'|un|une|des|du|de la|de l')\s*", re.I)


@dataclass(frozen=True)
class Step:
    """One step with the chapter it is in and its path in the document."""

    chapter: int
    index: int
    step: dict[str, Any]
    path: str

    @property
    def type(self) -> str:
        return str(self.step.get("type"))


def _steps(doc: dict[str, Any]) -> list[Step]:
    out: list[Step] = []
    for c_index, chapter in enumerate(doc.get("chapters") or []):
        position = 0
        for s_index, scene in enumerate(chapter.get("scenes") or []):
            for t_index, step in enumerate(scene.get("steps") or []):
                path = (
                    f"chapters[{chapter.get('id')}].scenes[{scene.get('id', s_index)}]"
                    f".steps[{t_index}]"
                )
                out.append(Step(c_index, position, step, path))
                position += 1
    return out


def is_closeup(step: dict[str, Any]) -> bool:
    return step.get("type") == "show" and step.get("visual") == "prop"


def _target(doc: dict[str, Any]) -> str:
    languages = doc.get("languages")
    return str(languages.get("target") or "en") if isinstance(languages, dict) else "en"


def _words(value: Any) -> int:
    if isinstance(value, list):
        return sum(_words(v) for v in value)
    return len(str(value or "").split())


def _is_situation(step: dict[str, Any]) -> bool:
    return step.get("type") == "concept" and str(step.get("id", "")).startswith("situation-")


# -- Props and their art -----------------------------------------------------------


def props_of(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(p["id"]): p for p in doc.get("props") or [] if isinstance(p, dict) and p.get("id")}


def has_art(doc: dict[str, Any], prop_id: str) -> bool:
    """A prop with a course figure, or a picture/sticker in the document's ``art.props``."""
    prop = props_of(doc).get(prop_id) or {}
    if prop.get("figure"):
        return True
    art = doc.get("art")
    entry = (art.get("props") or {}).get(prop_id) if isinstance(art, dict) else None
    return bool(entry)


def educational_props(doc: dict[str, Any]) -> list[str]:
    return [pid for pid, prop in props_of(doc).items() if prop.get("educational")]


def educational_without_art(doc: dict[str, Any]) -> list[str]:
    return [pid for pid in educational_props(doc) if not has_art(doc, pid)]


def closeup_ids(doc: dict[str, Any]) -> list[str]:
    """The prop of each close-up step, in order (a prop shown twice is listed twice)."""
    return [
        str((s.step.get("params") or {}).get("prop"))
        for s in _steps(doc)
        if is_closeup(s.step) and (s.step.get("params") or {}).get("prop")
    ]


# -- The numbers -------------------------------------------------------------------


def say_run_max(doc: dict[str, Any]) -> int:
    """The longest run of ``say`` lines in a row (a talking-heads stretch)."""
    longest = run = 0
    previous = None
    for item in _steps(doc):
        if item.chapter != previous:
            run = 0
        run = run + 1 if item.type == "say" else 0
        previous = item.chapter
        longest = max(longest, run)
    return longest


def mentor_share(doc: dict[str, Any]) -> float:
    says = [s for s in _steps(doc) if s.type == "say"]
    if not says:
        return 0.0
    return round(sum(1 for s in says if s.step.get("who") == "mentor") / len(says), 2)


def refrain_count(doc: dict[str, Any]) -> int:
    return sum(1 for s in _steps(doc) if s.step.get("refrain"))


def card_words(doc: dict[str, Any]) -> list[int]:
    """Words of each concept card (its rows and its title, in the target language)."""
    target = _target(doc)
    out = []
    for item in _steps(doc):
        if item.type != "concept" or _is_situation(item.step):
            continue
        title = item.step.get("title")
        out.append(
            _words(item.step.get(target))
            + (_words(title.get(target)) if isinstance(title, dict) else 0)
        )
    return out


def words_before_first_card(doc: dict[str, Any]) -> int:
    """The most story words a chapter tells before its first card (0 with no card)."""
    target = _target(doc)
    worst = 0
    chapters: dict[int, list[Step]] = {}
    for item in _steps(doc):
        chapters.setdefault(item.chapter, []).append(item)
    for items in chapters.values():
        words = 0
        for item in items:
            if item.type == "concept" and not _is_situation(item.step):
                worst = max(worst, words)
                break
            if item.type in LINE_TYPES:
                words += _words(item.step.get(target))
    return worst


def story_metrics(doc: dict[str, Any]) -> dict[str, Any]:
    """The numbers written into ``checks.story_metrics`` and printed by the audit."""
    closeups = closeup_ids(doc)
    cards = card_words(doc)
    out = {
        "say_run_max": say_run_max(doc),
        "closeups": len(closeups),
        "closeups_with_art": sum(1 for pid in closeups if has_art(doc, pid)),
        "words_before_first_card": words_before_first_card(doc),
        "card_words_max": max(cards) if cards else 0,
        "refrain_count": refrain_count(doc),
        "mentor_share": mentor_share(doc),
    }
    acts = acts_per_chapter(doc)
    if acts:
        # #2711: only a story told with bets has these, so no stored story's
        # numbers change.
        out["bets"] = sum(acts)
        out["acts_per_chapter_min"] = min(acts)
    return out


def acts_per_chapter(doc: dict[str, Any]) -> list[int]:
    """Bets (predictions) in each chapter of ``doc`` that has at least one; empty if none."""
    counts: dict[int, int] = {}
    for item in _steps(doc):
        if is_bet(item.step):
            counts[item.chapter] = counts.get(item.chapter, 0) + 1
    if not counts:
        return []
    carded = {i.chapter for i in _steps(doc) if i.type == "concept" and not _is_situation(i.step)}
    return [counts.get(c, 0) for c in sorted(carded)]


# -- Findings (all warnings) -------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def dangling_deixis(doc: dict[str, Any]) -> list[Finding]:
    """A "look / regardez / voici" line with no ``show`` within two steps."""
    out: list[Finding] = []
    chapters: dict[int, list[Step]] = {}
    for item in _steps(doc):
        chapters.setdefault(item.chapter, []).append(item)
    for items in chapters.values():
        for position, item in enumerate(items):
            if item.type not in LINE_TYPES:
                continue
            if not any(DEIXIS_RE.search(str(item.step.get(lang) or "")) for lang in ("en", "fr")):
                continue
            near = items[max(position - DEIXIS_WINDOW, 0) : position + DEIXIS_WINDOW + 1]
            if not any(n.type == "show" for n in near):
                out.append(
                    Finding(
                        "dangling_deixis",
                        item.path,
                        "this line says to look at something but nothing is shown within"
                        f" {DEIXIS_WINDOW} steps",
                    )
                )
    return out


def _core(label: str) -> str:
    return fold(_ARTICLE_RE.sub("", label.strip())).strip()


def _names(prop: dict[str, Any]) -> set[str]:
    """What a text may call a prop: its label without the article, and its head noun."""
    label = prop.get("label") if isinstance(prop.get("label"), dict) else {}
    names: set[str] = set()
    for lang, head_last in (("en", True), ("fr", False)):
        core = _core(str(label.get(lang) or ""))
        if len(core) >= 3:
            names.add(core)
        words = [w for w in core.split() if len(w) >= 4]
        if words:
            names.add(words[-1] if head_last else words[0])
    return names


def _mentions(text: str, names: set[str]) -> bool:
    folded = fold(text)
    return any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", folded) for n in names)


def _texts(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _texts(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)


def unseen_stimulus(doc: dict[str, Any]) -> list[Finding]:
    """A question or paper task that names an educational prop not shown before it."""
    questions = {q.get("id"): q for q in doc.get("questions") or [] if isinstance(q, dict)}
    exercises = {e.get("id"): e for e in doc.get("exercises") or [] if isinstance(e, dict)}
    props = props_of(doc)
    names = {pid: _names(props[pid]) for pid in educational_props(doc)}
    shown: set[str] = set()
    out: list[Finding] = []
    for item in _steps(doc):
        step = item.step
        if is_closeup(step):
            pid = (step.get("params") or {}).get("prop")
            if pid:
                shown.add(str(pid))
            continue
        if item.type == "ask":
            source = questions.get(step.get("ref"))
            text = " ".join(_texts(source.get("prompt") or source.get("stem"))) if source else ""
        elif item.type == "photo":
            source = exercises.get(step.get("ref"))
            text = " ".join(_texts(source.get("prompt"))) if source else ""
        else:
            continue
        for pid, prop_names in names.items():
            if pid not in shown and text and _mentions(text, prop_names):
                out.append(
                    Finding(
                        "unseen_stimulus",
                        item.path,
                        f"{step.get('ref')} names {pid!r}, which is not shown before it",
                    )
                )
    return out


def stimulus_not_shown(doc: dict[str, Any]) -> list[Finding]:
    """A question or task whose stimulus picture is not shown before it (#2711)."""
    return [
        Finding(
            "stimulus_not_shown",
            where,
            f"the thumbnail of {where} is a picture the story has not shown yet ({picture})",
        )
        for where, picture in stimulus_gaps(doc)
    ]


def few_acts(doc: dict[str, Any]) -> list[Finding]:
    """A chapter of a story told with bets that asks the learner to bet fewer than 3 times."""
    acts = acts_per_chapter(doc)
    if not acts:
        return []
    return [
        Finding("few_acts", "chapters", f"{n} bet(s) in a chapter: aim for at least 3")
        for n in acts
        if n < 3
    ][:1]


def french_in(text: Any) -> list[str]:
    """The French stopwords of ``text`` when it has two or more distinct ones, else ``[]``."""
    tokens = [t for t in _TOKEN_RE.findall(str(text or "").lower()) if t]
    if len(tokens) < _MIN_LANG_WORDS:
        return []
    found = sorted({t for t in tokens if t in _FRENCH_STOPWORDS})
    return found if len(found) >= 2 else []


def _walk_en(value: Any, path: str) -> Iterator[tuple[str, str]]:
    """``(path, text)`` of every ``en`` string under ``value`` (hints, choices, traps...)."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "en":
                for text in _texts(child):
                    yield f"{path}.en", text
            else:
                yield from _walk_en(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_en(child, f"{path}[{index}]")


def _en_fields(doc: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """``(path, text)`` of every English string a learner reads."""
    for item in _steps(doc):
        yield from _walk_en(item.step, item.path)
    for group in ("questions", "exercises", "minigames", "objectives"):
        for index, row in enumerate(doc.get(group) or []):
            if isinstance(row, dict):
                yield from _walk_en(row, f"{group}[{row.get('id', index)}]")


def lang_integrity(doc: dict[str, Any]) -> list[Finding]:
    """French in an ``en`` field (a translation that was copied, or never made)."""
    out: list[Finding] = []
    for path, text in _en_fields(doc):
        words = french_in(text)
        if words:
            out.append(
                Finding(
                    "lang_integrity",
                    path,
                    "the English text looks French (" + ", ".join(words[:4]) + ")",
                )
            )
    return out


def educational_art_findings(doc: dict[str, Any]) -> list[Finding]:
    return [
        Finding(
            "educational_prop_without_art",
            f"props[{pid}]",
            f"{pid!r} must be seen but the story has no picture for it (no course figure):"
            " its close-up is a name card unless the prop library has one",
        )
        for pid in educational_without_art(doc)
    ]


def all_findings(doc: dict[str, Any]) -> list[Finding]:
    """Every #2708 finding, all warnings."""
    return [
        *educational_art_findings(doc),
        *dangling_deixis(doc),
        *unseen_stimulus(doc),
        *lang_integrity(doc),
        *stimulus_not_shown(doc),
        *few_acts(doc),
    ]
