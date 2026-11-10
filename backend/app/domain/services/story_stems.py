"""Story-voiced quiz questions with the answer key locked (#2698).

A course quiz question asked in a chapter used to keep the quiz's own stem: a
textbook sentence ("Les biologistes ont identifié…", a town of another
country) in the middle of a story, or the « Sur la carte » card holding it.
The practice pack now also writes, for each course question it is given, a
``story_stem``: the same question as a character of the episode asks it.
Only that sentence changes. The options, the correct one, the explanation and
the quiz row it comes from (id, revision, digest) stay byte for byte, so
grading against the pinned quiz revision is unchanged.

A rewrite is used only when it passes, in this order:

1. the checks made in code (:func:`stem_problems`): both languages, short
   enough to be the question itself (no card), the same numbers and units,
   the same negations, exceptions, quantifiers and superlatives, the words the
   original shares with its options, no correct answer, and no name or place
   the course does not have (the lesson's name blocklist; a capitalised word
   that is neither in the original, the course bible nor the cast);
2. the equivalence judge (:func:`judge_stems`): one call of the cheaper
   configured model for the chapter's questions together, answering in strict
   JSON whether each rewrite asks the same question, keeps the same option as
   the only correct one, and gives nothing away.

Anything else keeps the original stem: a failed check, a judge that says no,
an answer that cannot be read, a provider error. It never blocks a chapter.
The original is stored next to the rewrite (``question["original_stem"]``),
and the quiz page keeps showing the original.

The rewrite and the judge's verdict are kept with the chapter's practice pack
(``pack["stems"]``), whose inputs hold each question's content: a stem is
rewritten and judged again only when the quiz revision or the chapter changes
and the pack is made again — never in a loop.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from app.domain.services import story_repair as repair

logger = structlog.get_logger(__name__)

#: Part of a kept verdict: a judge of another version is asked again.
STEM_JUDGE_VERSION = 1
#: A story stem shorter than this is not a question.
MIN_STEM_LENGTH = 12

LANGS = ("en", "fr")

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_UNITS = frozenset(
    [
        "%",
        "‰",
        "°c",
        "°",
        "km",
        "m",
        "cm",
        "mm",
        "µm",
        "nm",
        "kg",
        "g",
        "mg",
        "l",
        "ml",
        "cl",
        "h",
        "min",
        "s",
        "ms",
        "an",
        "ans",
        "year",
        "years",
        "jour",
        "jours",
        "day",
        "days",
        "mois",
        "month",
        "months",
        "semaine",
        "semaines",
        "week",
        "weeks",
        "fcfa",
        "cfa",
        "$",
        "€",
        "kcal",
        "cal",
        "j",
        "kj",
        "mol",
        "ph",
        "km/h",
        "m/s",
    ]
)
_UNIT_RE = re.compile(
    r"(?<![\w])(\d+(?:[.,]\d+)?)\s*(%|‰|°\s*c|°|[a-zµ]{1,5}(?:/[a-z]{1,3})?|\$|€)(?![\w])",
    re.IGNORECASE,
)
#: Words that change what is asked: a rewrite keeps each group a stem has, and
#: adds none it does not have.
_GUARDS: dict[str, dict[str, frozenset[str]]] = {
    "negation": {
        "en": frozenset({"not", "never", "no", "none", "cannot", "isn't", "doesn't", "don't"}),
        "fr": frozenset({"pas", "jamais", "aucun", "aucune", "rien", "ni"}),
    },
    "exception": {
        "en": frozenset({"except", "excluding"}),
        "fr": frozenset({"sauf", "excepte", "hormis"}),
    },
    "universal": {
        "en": frozenset({"all", "every", "each", "always"}),
        "fr": frozenset({"tous", "toutes", "chaque", "toujours"}),
    },
    "superlative": {
        "en": frozenset({"most", "least", "best", "mainly", "main", "largest", "smallest"}),
        "fr": frozenset({"plus", "moins", "principalement", "principal", "principale"}),
    },
    "falsity": {
        "en": frozenset({"false", "wrong", "incorrect", "untrue"}),
        "fr": frozenset({"faux", "fausse", "incorrect", "incorrecte", "erronee"}),
    },
}
_STOPWORDS = frozenset(
    [
        "about",
        "after",
        "avant",
        "avec",
        "cette",
        "celle",
        "celui",
        "ceux",
        "comme",
        "dans",
        "depuis",
        "entre",
        "leurs",
        "parmi",
        "pendant",
        "plusieurs",
        "pourquoi",
        "quand",
        "quelle",
        "quelles",
        "quels",
        "quel",
        "suivante",
        "suivantes",
        "suivants",
        "their",
        "there",
        "these",
        "those",
        "which",
        "while",
        "whose",
        "where",
        "what",
        "with",
        "would",
        "could",
        "should",
        "following",
        "question",
        "choose",
        "choisis",
        "laquelle",
        "lequel",
        "lesquels",
        "lesquelles",
    ]
)
_WORD_RE = re.compile(r"[a-z0-9]+")
_CAPITALISED_RE = re.compile(r"(?<![\w'’-])([A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'’-]{2,})")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


def _plain(text: Any) -> str:
    """Lower case, no accents, straight apostrophes."""
    value = unicodedata.normalize("NFKD", str(text or "")).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.replace("’", "'")


def _words(text: Any) -> set[str]:
    return set(_WORD_RE.findall(_plain(text).replace("'", " ")))


def _root(word: str) -> str:
    """A word without its plural: "proprietes" and "propriete" are one term."""
    for end in ("es", "s", "x"):
        if len(word) > 4 and word.endswith(end):
            return word[: -len(end)]
    return word


def _numbers(text: str) -> list[str]:
    return sorted(n.replace(",", ".") for n in _NUMBER_RE.findall(text))


def _units(text: str) -> set[str]:
    return {
        re.sub(r"\s+", "", unit.lower())
        for _number, unit in _UNIT_RE.findall(text)
        if re.sub(r"\s+", "", unit.lower()) in _UNITS
    }


def _guards(text: str, lang: str) -> set[str]:
    words = _words(text)
    plain = _plain(text)
    found = {name for name, by_lang in _GUARDS.items() if words & by_lang[lang]}
    if lang == "en" and "n't" in plain:
        found.add("negation")
    return found


@dataclass
class StemCandidate:
    """One course question of a chapter, its original stem and its story stem."""

    ref: str
    #: The stem as the chapter would show it: the quiz's own in the course's
    #: language, the pack's translation in the other.
    original: dict[str, str]
    rewrite: dict[str, str]
    #: The options, per language, in their order; the correct one's index.
    options: dict[str, list[str]]
    correct_index: int


def stem_problems(
    candidate: StemCandidate,
    *,
    blocklist: Sequence[str] = (),
    allowed: Iterable[str] = (),
) -> list[str]:
    """Why a story stem cannot replace the original, checked in code; ``[]`` when it can.

    ``allowed`` are the words a name may be: the course bible's, the cast's
    and the country's (folded). Any other capitalised word inside a sentence
    must already be in the original.
    """
    problems: list[str] = []
    allowed_words = {_plain(w) for w in allowed}
    for lang in LANGS:
        rewrite = " ".join(str(candidate.rewrite.get(lang) or "").split())
        original = " ".join(str(candidate.original.get(lang) or "").split())
        if not rewrite:
            problems.append(f"{lang}: no story stem")
            continue
        limit = repair.PROMPT_LIMITS[lang]
        if not MIN_STEM_LENGTH <= len(rewrite) <= limit:
            problems.append(f"{lang}: {len(rewrite)} characters, the question takes up to {limit}")
        if "?" in original and "?" not in rewrite:
            problems.append(f"{lang}: no longer a question")
        if any(p not in ("{child}", "{friend}") for p in _PLACEHOLDER_RE.findall(rewrite)):
            problems.append(f"{lang}: a placeholder other than {{child}} or {{friend}}")
        if _numbers(original) != _numbers(rewrite):
            problems.append(f"{lang}: the numbers changed")
        if _units(original) != _units(rewrite):
            problems.append(f"{lang}: the units changed")
        if _guards(original, lang) != _guards(rewrite, lang):
            problems.append(f"{lang}: a negation, exception, quantifier or superlative changed")
        options = candidate.options.get(lang) or []
        option_words = {_root(w) for o in options for w in _words(o)}
        key_terms = {
            _root(w)
            for w in _words(original)
            if len(w) >= 5 and w not in _STOPWORDS and _root(w) in option_words
        }
        missing = key_terms - {_root(w) for w in _words(rewrite)}
        if missing:
            problems.append(f"{lang}: key terms left out: {', '.join(sorted(missing))}")
        for option_lang in LANGS:
            correct = (candidate.options.get(option_lang) or [None] * 99)[candidate.correct_index]
            if correct and repair._leaks(correct, rewrite):
                problems.append(f"{lang}: the rewrite contains the correct answer")
                break
        known = _words(original) | allowed_words | _words(candidate.original.get(_other(lang)))
        for sentence in re.split(r"(?<=[.!?…:;])\s+", _PLACEHOLDER_RE.sub("X", rewrite)):
            for match in _CAPITALISED_RE.finditer(sentence):
                if not sentence[: match.start(1)].strip(' «"“(-—–'):
                    continue  # it starts the sentence
                if not _words(match.group(1)) <= known:
                    problems.append(f"{lang}: a name or place the course does not have")
                    break
        plain = repair_plain(rewrite)
        for name in blocklist:
            if len(name) >= 3 and re.search(
                rf"(?<![\w-]){re.escape(repair_plain(name))}(?![\w-])", plain
            ):
                problems.append(f"{lang}: a name from the lesson's own examples")
                break
    return problems


def repair_plain(text: Any) -> str:
    """Accents removed, case kept: how a blocked name is matched (as the story checks do)."""
    value = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in value if not unicodedata.combining(c)).replace("’", "'")


def _other(lang: str) -> str:
    return "fr" if lang == "en" else "en"


def stem_candidates(
    ctx: repair.LessonStoryContext, spine: dict[str, Any]
) -> tuple[list[StemCandidate], dict[str, str]]:
    """The chapter's course questions whose pack wrote a usable story stem.

    Returns the candidates that pass :func:`stem_problems` and, for every
    other assigned question, why its original stem is kept.
    """
    derived = {str(d.get("ref")): d for d in spine.get("derived") or [] if isinstance(d, dict)}
    target, home = ctx.target, ctx.home
    allowed = _course_words(ctx)
    candidates: list[StemCandidate] = []
    kept: dict[str, str] = {}
    assigned = set(ctx.assigned_refs)
    for mcq in ctx.mcqs:
        if mcq.ref not in assigned:
            continue
        item = derived.get(mcq.ref) or {}
        story = item.get("story_stem")
        if not isinstance(story, dict) or not all(
            isinstance(story.get(lang), str) for lang in LANGS
        ):
            kept[mcq.ref] = "no story stem"
            continue
        home_options = item.get("options_home")
        home_options = (
            [str(o) for o in home_options]
            if isinstance(home_options, list) and len(home_options) == len(mcq.options)
            else list(mcq.options)
        )
        candidate = StemCandidate(
            ref=mcq.ref,
            original={
                target: mcq.stem,
                home: " ".join(str(item.get("prompt_home") or mcq.stem).split()),
            },
            rewrite={lang: " ".join(str(story[lang]).split()) for lang in LANGS},
            options={target: list(mcq.options), home: home_options},
            correct_index=mcq.correct_index,
        )
        problems = stem_problems(candidate, blocklist=ctx.blocklist, allowed=allowed)
        if problems:
            kept[mcq.ref] = "; ".join(problems)[:300]
            continue
        candidates.append(candidate)
    return candidates, kept


def _course_words(ctx: repair.LessonStoryContext) -> set[str]:
    """The words a name in a story stem may be: the bible's, the cast's, the country's."""
    from app.ai.prompts.story_from_lesson import country_names

    words: set[str] = set()
    for text in _texts(ctx.bible_content):
        words |= _words(text)
    for name in country_names(ctx.country):
        words |= _words(name)
    words |= {"child", "friend"}
    return words


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts(v)]
    return []


# --------------------------------------------------------------------------
# The equivalence judge
# --------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = (
    "You check quiz questions that were reworded for a story. You are strict: when in"
    " doubt, the answer is no. You answer with one JSON object and nothing else."
)


def build_judge_message(candidates: Sequence[StemCandidate], language: str) -> str:
    """The judge's message: each question's original and rewrite, its options, the key."""
    lines = [
        "REQUEST: each quiz question below was reworded so a character of a story asks it."
        " Only the question sentence changed; the options and the correct one did not."
        " For each question, answer:",
        "- same_question: the rewrite asks exactly what the original asks — the same facts,"
        " numbers, units and conditions, nothing that matters added or left out.",
        "- same_answer: the option marked correct is still the one and only correct answer to"
        " the rewrite.",
        "- gives_away: the rewrite hints at, names or rules out options so the answer is given"
        " away.",
        "",
    ]
    for candidate in candidates:
        lines.append(f"[{candidate.ref}]")
        for lang in (language, _other(language)):
            lines.append(f"ORIGINAL ({lang}): {candidate.original.get(lang, '')}")
            lines.append(f"REWRITE ({lang}): {candidate.rewrite.get(lang, '')}")
        for index, option in enumerate(candidate.options.get(language) or []):
            mark = "  <- correct" if index == candidate.correct_index else ""
            lines.append(f"  {repair.CHOICE_IDS[index]}) {option}{mark}")
        lines.append("")
    lines.append(
        'Return ONLY this JSON: {"verdicts": [{"ref": "q1", "same_question": true,'
        ' "same_answer": true, "gives_away": false}], "__complete": true} — one entry per'
        " question above, true and false as JSON booleans."
    )
    return "\n".join(lines)


def read_verdicts(raw: Any, refs: Sequence[str]) -> dict[str, bool]:
    """Each ref's verdict from the judge's answer; anything unreadable is a no.

    A rewrite is approved only when its entry says, as JSON booleans,
    ``same_question: true``, ``same_answer: true`` and ``gives_away: false``.
    A ref with no entry, or with two, is a no.
    """
    verdicts: dict[str, bool] = {ref: False for ref in refs}
    items = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return verdicts
    seen: dict[str, int] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("ref"), str):
            seen[item["ref"]] = seen.get(item["ref"], 0) + 1
    for item in items:
        if not isinstance(item, dict) or item.get("ref") not in verdicts:
            continue
        if seen[item["ref"]] != 1:
            continue
        verdicts[item["ref"]] = (
            item.get("same_question") is True
            and item.get("same_answer") is True
            and item.get("gives_away") is False
        )
    return verdicts


async def judge_stems(
    service: Any, candidates: Sequence[StemCandidate], language: str
) -> dict[str, bool]:
    """One call of the judge for all ``candidates``; raises when the provider fails."""
    raw = await service.generate_structured_content(
        JUDGE_SYSTEM_PROMPT, build_judge_message(candidates, language), "story", max_retries=0
    )
    if isinstance(raw, dict):
        raw.pop("__complete", None)
    return read_verdicts(raw, [c.ref for c in candidates])


async def approve_stems(
    ctx: repair.LessonStoryContext, spine: dict[str, Any], judge: Any
) -> dict[str, Any] | None:
    """The chapter's verdict on its story stems: ``{"version", "approved", "kept"}``.

    ``approved`` maps a ref to its story stem (``{"en", "fr"}``); ``kept``
    maps every other assigned ref to why its original stem stays. ``None``
    when nothing could be decided now and it should be asked again on the
    next telling: no judge is configured, or the provider failed.
    """
    candidates, kept = stem_candidates(ctx, spine)
    if not candidates:
        return {"version": STEM_JUDGE_VERSION, "approved": {}, "kept": kept, "calls": 0}
    if judge is None:
        return None
    try:
        verdicts = await judge_stems(judge, candidates, ctx.target)
    except SoftTimeLimitExceeded:
        raise
    except ValueError as exc:
        # An unreadable answer is a judge that said no: kept, never asked again.
        logger.warning("Story stem judge unreadable", slug=ctx.slug, error=str(exc)[:200])
        verdicts = {c.ref: False for c in candidates}
    except Exception as exc:
        logger.warning("Story stem judge unavailable", slug=ctx.slug, error=str(exc)[:200])
        return None
    approved: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        if verdicts.get(candidate.ref):
            approved[candidate.ref] = dict(candidate.rewrite)
        else:
            kept[candidate.ref] = "the judge did not find the rewrite equivalent"
    logger.info(
        "Story stems judged",
        slug=ctx.slug,
        approved=sorted(approved),
        kept=sorted(kept),
    )
    return {"version": STEM_JUDGE_VERSION, "approved": approved, "kept": kept, "calls": 1}


def approved_stems(verdict: Any) -> dict[str, dict[str, str]]:
    """The approved story stems of a kept verdict (``{}`` for one of another version)."""
    if not isinstance(verdict, dict) or verdict.get("version") != STEM_JUDGE_VERSION:
        return {}
    approved = verdict.get("approved")
    if not isinstance(approved, dict):
        return {}
    return {
        str(ref): {lang: str(stem[lang]) for lang in LANGS}
        for ref, stem in approved.items()
        if isinstance(stem, dict) and all(isinstance(stem.get(lang), str) for lang in LANGS)
    }
