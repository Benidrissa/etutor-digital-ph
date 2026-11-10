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


def _wordset(words: str) -> frozenset[str]:
    return frozenset(words.split())


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
#: Number words counted as numbers ("one" and « un »/« une » are articles and
#: pronouns too: they only count in the answer check).
_NUMBER_WORDS: dict[str, dict[str, str]] = {
    "en": dict(
        zip(
            [
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
                "ten",
                "eleven",
                "twelve",
                "thirteen",
                "fourteen",
                "fifteen",
                "sixteen",
                "seventeen",
                "eighteen",
                "nineteen",
                "twenty",
            ],
            [str(n) for n in range(2, 21)],
            strict=True,
        )
    ),
    "fr": dict(
        zip(
            [
                "deux",
                "trois",
                "quatre",
                "cinq",
                "six",
                "sept",
                "huit",
                "neuf",
                "dix",
                "onze",
                "douze",
                "treize",
                "quatorze",
                "quinze",
                "seize",
                "dix-sept",
                "dix-huit",
                "dix-neuf",
                "vingt",
            ],
            [str(n) for n in range(2, 21)],
            strict=True,
        )
    ),
}
#: Words that multiply or divide: as binding as a number.
_MULTIPLIERS = _wordset(
    "double doubles doubled triple triples tripled quadruple twice thrice half halves"
    " quarter moitie demi demie quart tiers dixieme centieme"
)
#: The spelled-out forms of 0-20, for the answer check (both languages).
_SPELLED = {
    str(n): words
    for n, words in enumerate(
        [
            ("zero",),
            ("one", "un", "une"),
            ("two", "deux"),
            ("three", "trois"),
            ("four", "quatre"),
            ("five", "cinq"),
            ("six",),
            ("seven", "sept"),
            ("eight", "huit"),
            ("nine", "neuf"),
            ("ten", "dix"),
            ("eleven", "onze"),
            ("twelve", "douze"),
            ("thirteen", "treize"),
            ("fourteen", "quatorze"),
            ("fifteen", "quinze"),
            ("sixteen", "seize"),
            ("seventeen", "dix-sept"),
            ("eighteen", "dix-huit"),
            ("nineteen", "dix-neuf"),
            ("twenty", "vingt"),
        ]
    )
}
_UNIT_SYMBOL_RE = re.compile(
    r"(?<![\w])\d+(?:[.,]\d+)?\s*(%|‰|°\s*c|°|µm|nm|mm|cm|km|m|mg|kg|g|ml|cl|l|kcal|kj|j|h|min|s|ms)(?![\w])",
    re.IGNORECASE,
)
#: Unit words, with or without a number ("in micrometres").
_UNIT_WORDS = {
    "en": _wordset(
        "nanometre nanometer micrometre micrometer micron millimetre millimeter centimetre"
        " centimeter metre meter kilometre kilometer milligram milligramme gram gramme"
        " kilogram kilogramme tonne ton millilitre milliliter centilitre litre liter second"
        " minute hour day week month year decade century degree celsius kelvin percent"
        " percentage calorie kilocalorie joule kilojoule watt volt ampere pascal mole"
    ),
    "fr": _wordset(
        "nanometre micrometre micron millimetre centimetre metre kilometre milligramme"
        " gramme kilogramme tonne millilitre centilitre litre seconde minute heure jour"
        " semaine mois an annee decennie siecle degre celsius kelvin pourcent pourcentage"
        " calorie kilocalorie joule kilojoule watt volt ampere pascal mole"
    ),
}
#: Words that change what is asked, compared word for word (« le plus grand »
#: is not « le plus petit »): a negation, an exception or a restriction, a
#: quantifier, a comparison, true or false.
_GUARD_WORDS = {
    "en": _wordset(
        "not never no none nothing nobody neither nor cannot except excluding besides"
        " only solely without non all every each always both any most least more less"
        " fewer best worst main mainly first last than true false wrong correct incorrect"
        " untrue"
    ),
    "fr": _wordset(
        "pas jamais aucun aucune rien ni personne sauf excepte hormis seul seule seuls"
        " seules seulement uniquement sans non tous toutes tout chaque toujours meilleur"
        " meilleure pire principal principale principalement premier premiere dernier"
        " derniere vrai vraie faux fausse correct correcte incorrect incorrecte erronee"
    ),
}
#: Phrases that restrict or except, as one guard each.
_GUARD_PHRASES = {
    "en": (
        ("other than", re.compile(r"\bother than\b")),
        ("apart from", re.compile(r"\bapart from\b")),
        ("but not", re.compile(r"\bbut not\b")),
    ),
    "fr": (
        ("a part", re.compile(r"\ba part\b")),
        ("autre que", re.compile(r"\bautres? que\b")),
        ("a l'exception", re.compile(r"\ba l'exception\b")),
        ("en dehors", re.compile(r"\ben dehors\b")),
        # « ne … que »: only.
        ("ne que", re.compile(r"\bn(?:e\s|')[^.?!]*?\bqu(?:e\b|')")),
    ),
}
#: An English superlative ("largest", "smallest"), as its own guard.
_SUPERLATIVE_RE = re.compile(r"\b[a-z]{2,}est\b")
_NOT_SUPERLATIVES = _wordset(
    "forest interest honest harvest test rest nest west chest guest request suggest"
    " contest protest invest digest arrest modest earnest manifest pest vest quest"
)
#: Capitalised words a sentence may start with that are not names.
_STARTERS = _wordset(
    "which what why how who whom whose where when is are do does did can could will would"
    " the a an this that these those my your his her its our their i you he she it we"
    " they and but so then now here there today yes no well oh ah hey look listen imagine"
    " think count choose pick tell say help wait come see find guess try remember"
    " quel quelle quels quelles lequel laquelle lesquels lesquelles pourquoi comment"
    " combien ou qui que qu quand est le la les l un une des du de ce cet cette ces mon ma"
    " mes ton ta tes son sa ses notre votre leur leurs je j tu il elle on nous vous ils"
    " elles et mais alors donc puis ensuite enfin maintenant ici aujourd oui non bon"
    " regarde regardez ecoute ecoutez imagine imaginez pense pensez compte comptez choisis"
    " choisissez dis dites aide aidez attends attendez viens venez vois voyez voici voila"
    " devine devinez essaie trouve trouvez souviens rappelle"
)
_WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CAPITALISED_RE = re.compile(r"(?<![\w'’-])([A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'’-]{2,})")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_STOPWORDS = _wordset(
    "about after avant avec cette celle celui ceux comme dans depuis entre leurs parmi"
    " pendant plusieurs pourquoi quand quelle quelles quels quel suivante suivantes"
    " suivants their there these those which while whose where what with would could"
    " should following question choose choisis laquelle lequel lesquels lesquelles"
)


def _plain(text: Any) -> str:
    """Lower case, no accents, straight apostrophes."""
    value = unicodedata.normalize("NFKD", str(text or "")).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.replace("’", "'")


def _tokens(text: Any) -> list[str]:
    """The words of ``text``, elisions opened ("n'est" → "n", "est")."""
    return _WORD_RE.findall(_plain(text).replace("'", " "))


def _words(text: Any) -> set[str]:
    words = set(_tokens(text))
    return words | {part for w in words if "-" in w for part in w.split("-")}


def _root(word: str) -> str:
    """A word without its plural: "proprietes" and "propriete" are one term."""
    for end in ("es", "s", "x"):
        if len(word) > 4 and word.endswith(end):
            return word[: -len(end)]
    return word


def _numbers(text: str, lang: str) -> list[str]:
    """The numbers of ``text``: digits, number words (2-20) and multipliers."""
    found = [n.replace(",", ".") for n in _NUMBER_RE.findall(text)]
    for word in _tokens(text):
        if word in _NUMBER_WORDS[lang]:
            found.append(_NUMBER_WORDS[lang][word])
        elif word in _MULTIPLIERS:
            found.append(word)
    return sorted(found)


def _units(text: str, lang: str) -> set[str]:
    """The units of ``text``: a symbol after a number, a unit word anywhere."""
    found = {re.sub(r"\s+", "", u.lower()) for u in _UNIT_SYMBOL_RE.findall(text)}
    units = {_singular(u) for u in _UNIT_WORDS[lang]}
    found |= {_singular(w) for w in _words(text) if _singular(w) in units}
    return found


def _singular(word: str) -> str:
    """A unit word without its plural s ("millimetres" → "millimetre")."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _guards(text: str, lang: str) -> set[str]:
    """The words and phrases of ``text`` that change what is asked (compared as such)."""
    plain = _plain(text)
    words = _words(text)
    found = {w for w in words if w in _GUARD_WORDS[lang]}
    if lang == "en":
        if re.search(r"n't\b", plain):
            found.add("not")
        found |= {w for w in _SUPERLATIVE_RE.findall(plain) if w not in _NOT_SUPERLATIVES}
        found |= {f"{m} than" for m in re.findall(r"\b([a-z]+) than\b", plain)}
    else:
        # « le plus grand » / « le moins d'énergie »: the word that follows counts.
        found |= {f"{w} {nxt}" for w, nxt in re.findall(r"\b(plus|moins)\s+(?:d')?([a-z]+)", plain)}
    for name, pattern in _GUARD_PHRASES[lang]:
        if pattern.search(plain):
            found.add(name)
    return found


def _question_part(text: str) -> tuple[str, str]:
    """``(lead-in, question sentence)``: the last sentence that asks, and the rest."""
    sentences = [s for s in _SENTENCE_RE.split(text.strip()) if s]
    if not sentences:
        return "", ""
    index = max((i for i, s in enumerate(sentences) if "?" in s), default=len(sentences) - 1)
    lead = " ".join(sentences[:index] + sentences[index + 1 :])
    return lead, sentences[index]


def _names_option(option: str, text: str) -> bool:
    return bool(option) and repair._leaks(option, text)


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

    Per language: both written, short enough to be the question, still a
    question, only ``{child}``/``{friend}``; the same numbers (digits, number
    words, multipliers) and units (symbols, unit words); the question sentence
    has exactly the guard words of the original (negations, exceptions,
    restrictions, quantifiers, comparisons, true/false — compared word for
    word) and the lead-in has none; the original's words shared with its
    options are kept; no option the original does not name (nor the correct
    answer's number spelled out); no name or place the course does not have:
    a capitalised word, even one that starts a sentence, must be in the
    original, ``allowed`` (the bible, the cast, the country) or be a common
    sentence opener; no name of the lesson's blocklist (any case, any accents).
    """
    problems: list[str] = []
    allowed_words = {w for a in allowed for w in _words(a)}
    blocked = [_plain(n) for n in blocklist if len(n) >= 3]
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
        if _numbers(original, lang) != _numbers(rewrite, lang):
            problems.append(f"{lang}: the numbers changed")
        if _units(original, lang) != _units(rewrite, lang):
            problems.append(f"{lang}: the units changed")
        lead, question = _question_part(rewrite)
        if _guards(lead, lang):
            problems.append(
                f"{lang}: the lead-in has a word that changes the question"
                f" ({', '.join(sorted(_guards(lead, lang)))})"
            )
        if _guards(original, lang) != _guards(question, lang):
            problems.append(
                f"{lang}: a negation, exception, restriction, quantifier or comparison changed"
            )
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
        if any(
            _names_option(option, rewrite) and not _names_option(option, original)
            for option_lang in LANGS
            for option in candidate.options.get(option_lang) or []
        ):
            problems.append(f"{lang}: the rewrite names an option")
        correct = (candidate.options.get(lang) or [""] * 99)[candidate.correct_index]
        spelled = _SPELLED.get(re.sub(r"[^\d]", "", correct) if correct.strip().isdigit() else "")
        if spelled and set(spelled) & (set(_tokens(rewrite)) - set(_tokens(original))):
            problems.append(f"{lang}: the rewrite spells out the correct answer")
        known = _words(original) | allowed_words | _words(candidate.original.get(_other(lang)))
        for sentence in _SENTENCE_RE.split(_PLACEHOLDER_RE.sub("X", rewrite)):
            for match in _CAPITALISED_RE.finditer(sentence):
                words = _words(match.group(1))
                starts = not sentence[: match.start(1)].strip(' «"“(-—–')
                if words <= known or (starts and words <= _STARTERS):
                    continue
                problems.append(f"{lang}: a name or place the course does not have")
                break
        plain = _plain(rewrite)
        if any(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", plain) for name in blocked):
            problems.append(f"{lang}: a name from the lesson's own examples")
    return problems


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
    """The judge's message: each question in both languages, its options and the key."""
    lines = [
        "REQUEST: each quiz question below was reworded, in English and in French, so a"
        " character of a story asks it. Only the question sentence changed; the options"
        " and the correct one did not. Judge BOTH languages; each answer covers both:",
        "- same_question: true only if, in EACH language, the rewrite asks exactly what"
        " the original asks — the same facts, numbers, units and conditions, nothing that"
        " matters added or left out. False if either language differs.",
        "- same_answer: true only if, in EACH language, the option marked correct is still"
        " the one and only correct answer to the rewrite.",
        "- gives_away: true if, in EITHER language, the rewrite hints at, names or rules out"
        " options so the answer is given away.",
        "",
    ]
    for candidate in candidates:
        lines.append(f"[{candidate.ref}]")
        for lang in (language, _other(language)):
            lines.append(f"ORIGINAL ({lang}): {candidate.original.get(lang, '')}")
            lines.append(f"REWRITE ({lang}): {candidate.rewrite.get(lang, '')}")
            lines.append(f"OPTIONS ({lang}):")
            for index, option in enumerate(candidate.options.get(lang) or []):
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
        # An answer that came back unreadable is a judge that said no
        # (read_verdicts): kept. Anything raised — the provider, its key, its
        # configuration — decides nothing: asked again on the next telling.
        verdicts = await judge_stems(judge, candidates, ctx.target)
    except SoftTimeLimitExceeded:
        raise
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


def recheck_stems(
    ctx: repair.LessonStoryContext, spine: dict[str, Any], approved: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    """The kept approved stems that still pass every check made in code — no call.

    A verdict kept with a pack is read again with the checks as they are now,
    so a check added later applies to stems approved before it, for free.
    """
    if not approved:
        return {}
    candidates, _kept = stem_candidates(ctx, spine)
    passing = {c.ref: c.rewrite for c in candidates}
    return {ref: stem for ref, stem in approved.items() if passing.get(ref) == stem}
