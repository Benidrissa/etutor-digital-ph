"""The slot call: the model fills the short lines the code left open (#2713).

:mod:`story_beats` builds a chapter's screenplay in code and leaves **slots**:
each has an id, a role, who says it, a hard word cap and a one-line brief. This
module asks the model for them in ONE call per chapter and takes back only
``{slot_id: {"fr": "...", "en": "..."}}``: about a thousand output tokens where
the whole screenplay took three to six thousand.

What the code does with the answer:

* **validates** each slot on its own: both languages present, the word cap
  and the story line's character limit respected, no name from the lesson's own
  examples (the same blocklist as the classic checks), no "Name:" prefix, no
  line that talks about the lesson or the app, no French in the English text;
* **retries** the slots that failed, once, in a second (small) call, when the
  repair budget allows it (``story-max-repair-calls``);
* **falls back** for any slot still missing or invalid: the code's own neutral
  line for that role (:data:`story_beats.FALLBACKS`), or no text at all for a
  card row. A slot never fails a chapter.

A chapter whose answer was mostly unusable is reported by the caller as such
(:attr:`SlotResult.mostly_fallback`) so the service can tell it the classic way
instead of publishing a story of stock lines.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from app.domain.services import story_beats as beats
from app.domain.services.story_checks import _META_RE, unaccented
from app.domain.services.story_metrics import french_in
from app.domain.services.story_repair import STORY_LINE_LIMITS, repeat_keys

logger = structlog.get_logger(__name__)

#: More than this share of fallback slots: the chapter is told the classic way.
MOSTLY_FALLBACK = 0.5
#: The longest, in characters, of a line, a row, a label (the classic limits are
#: :data:`story_repair.STORY_LINE_LIMITS`; a card row and a label are shorter).
ROW_CHARS = 120
LABEL_CHARS = 40

_PREFIX_RE = re.compile(r"^\s*(?:[A-ZÀ-Ý][\w' -]{0,18}|\{[a-z]+\})\s*:\s+\S")
_QUOTES = "\"'«»“”‘’ "

SYSTEM = (
    "You write the short lines of one chapter of an illustrated story for a learning"
    " platform. The screenplay is already built: you only fill the numbered slots with"
    " the words a character says, a narrator's sentence, a short label. Every slot is"
    " written twice, in English (en) and in French (fr), in the same voice, each in its"
    " own language only. You answer with ONE JSON object and nothing else."
)

#: ``(answer a model may give, an ``ask`` of the fill loop)``: the caller's model call.
Ask = Callable[..., Awaitable[dict[str, Any] | None]]


@dataclass
class SlotResult:
    """What filling a script cost and what it fell back on."""

    calls: int = 0
    #: Slots the model's first answer got wrong or left out.
    invalid: list[str] = field(default_factory=list)
    #: Slots filled by the code's own line (or left out) in the end.
    fallbacks: list[str] = field(default_factory=list)
    total: int = 0

    @property
    def mostly_fallback(self) -> bool:
        return bool(self.total) and len(self.fallbacks) / self.total > MOSTLY_FALLBACK

    def report(self) -> dict[str, Any]:
        return {
            "variant": "slots",
            "slots": self.total,
            "calls": self.calls,
            "invalid": list(self.invalid),
            "fallbacks": list(self.fallbacks),
        }


# -- the prompt --------------------------------------------------------------------------


def _clip(text: Any, limit: int = 300) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _voices_block(ctx: Any, script: beats.Script) -> str:
    plan = ctx.plan or {}
    voices = plan.get("voices") if isinstance(plan.get("voices"), dict) else {}
    cast = {
        str(c.get("id")): c
        for c in ctx.bible_content.get("cast") or []
        if isinstance(c, dict) and c.get("id")
    }
    used = {s.who for s in script.slots if s.who}
    lines = []
    for who in sorted(used):
        about = _clip((cast.get(who) or {}).get("about"), 160)
        voice = _clip(voices.get(who), 160)
        lines.append(f"- {who}: {about}" + (f" | voice in this story: {voice}" if voice else ""))
    return "VOICES (who speaks):\n" + "\n".join(lines) if lines else ""


def _catchphrases(ctx: Any) -> str:
    out = []
    for item in ctx.catchphrases or []:
        if isinstance(item, dict) and item.get("en"):
            out.append(f"{item.get('who')}: «{item.get('en')}» / «{item.get('fr')}»")
    if not out:
        return ""
    budget = max(0, 4 - int(getattr(ctx, "refrains_before", 0) or 0))
    return (
        "CATCHPHRASES (a character's own refrain): "
        + "; ".join(out)
        + f". Use at most {min(budget, 1)} of them in this chapter, only when it fits, in the"
        " slot of the character who owns it; never in a card row, a label or a bet."
    )


def build_message(ctx: Any, script: beats.Script, slots: list[beats.Slot] | None = None) -> str:
    """The user message of a chapter's slot call."""
    plan = ctx.plan or {}
    entry = ctx.plan_entry or {}
    slots = script.slots if slots is None else slots
    title = (entry.get("title") or {}).get("en") or ctx.unit_title.get("en", "")
    episode = (plan.get("episode_title") or {}).get("en", "")
    style = beats.STYLES[script.seed % len(beats.STYLES)]
    blocked = ", ".join(ctx.blocklist[:40])
    rows = [
        f"- {s.id} | {s.role}"
        + (f" | said by {s.who}" if s.who else "")
        + f" | at most {s.cap} words"
        + f" | {s.brief}"
        + (f" | FACT: {_clip(s.fact)}" if s.fact else "")
        for s in slots
    ]
    blocks = [
        f"REQUEST: fill the {len(slots)} slots of chapter {ctx.chapter_index} of"
        f" {ctx.chapter_count} of the episode «{episode}»: «{title}».",
        "THE STORY: "
        + _clip(plan.get("logline"), 400)
        + (
            f" RUNNING GAG: {_clip(plan.get('running_gag'), 200)}"
            if plan.get("running_gag")
            else ""
        ),
        f"THIS CHAPTER: goal: {_clip(entry.get('goal'))} | turn: {_clip(entry.get('turn'))} |"
        f" ends on: {_clip(entry.get('ends_on'))}",
        _voices_block(ctx, script),
        _catchphrases(ctx),
        f"VARIANT {script.seed % len(beats.STYLES) + 1} of {len(beats.STYLES)}: {style}."
        " Another chapter of this story uses another variant: do not fall back on the"
        " phrasings that come to mind first.",
        "SLOTS (id | role | who | length | what it does | the one fact it may use):\n"
        + "\n".join(rows),
        "RULES:\n"
        '- Each slot is {"en": ..., "fr": ...}: English only in en, French only in fr,'
        " the same meaning. Never exceed a slot's word limit; shorter is better.\n"
        '- A line is ONLY the words spoken: no "Name:", no "Name says", no quotation'
        " marks around it. A narrator line is present tense, third person.\n"
        "- {child} is the learner and {friend} the friend; each may be a girl or a boy: never"
        " he/she or il/elle, and in French no adjective or participle agrees with them.\n"
        "- A line reacts to the picture or the problem, in character. It never recites the"
        " lesson, never gives a question's answer, never talks about the lesson, the quiz,"
        " the chapter or the app.\n"
        "- A card row is a label of the idea (a word and what it means), not dialogue.\n"
        + (f"- Never use these names: {blocked}.\n" if blocked else "")
        + "- Two slots never say the same thing.",
        'OUTPUT: ONE JSON object: {"<slot id>": {"en": "...", "fr": "..."}, ...} with every'
        ' slot id above, then "__complete": true as the last key, and nothing else.',
    ]
    return "\n\n".join(b for b in blocks if b)


def build_repair_message(
    ctx: Any, script: beats.Script, bad: dict[str, str], previous: dict[str, Any]
) -> str:
    """The second call: only the slots that failed, each with why."""
    slots = [s for s in script.slots if s.id in bad]
    notes = "\n".join(
        f"- {s.id}: {bad[s.id]}"
        + (
            f" (you wrote: {_clip(json.dumps(previous.get(s.id), ensure_ascii=False), 120)})"
            if s.id in previous
            else ""
        )
        for s in slots
    )
    return (
        build_message(ctx, script, slots)
        + "\n\nThese slots of your previous answer could not be used. Write them again,"
        " fixing exactly what is said:\n" + notes
    )


# -- validation ---------------------------------------------------------------------------


def _blocked(ctx: Any) -> list[re.Pattern[str]]:
    return [
        re.compile(rf"(?<![\w-]){re.escape(unaccented(name))}(?![\w-])")
        for name in ctx.blocklist or []
        if len(name) >= 3
    ]


def _clean(text: str) -> str:
    return " ".join(text.split()).strip(_QUOTES) if text.strip(_QUOTES) else ""


def check_value(
    slot: beats.Slot,
    value: Any,
    ctx: Any,
    blocked: list[re.Pattern[str]],
    seen: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, str] | None, str | None]:
    """``(cleaned value, None)`` or ``(None, why it cannot be used)``."""
    if not isinstance(value, dict):
        return None, "missing"
    out: dict[str, str] = {}
    for lang in ("en", "fr"):
        raw = value.get(lang)
        if not isinstance(raw, str) or not _clean(raw):
            return None, f"no {lang} text"
        text = _clean(raw)
        limit = (
            LABEL_CHARS
            if slot.role in (beats.LABEL,)
            else ROW_CHARS
            if slot.role == beats.CARD_ROW
            else STORY_LINE_LIMITS[lang]
        )
        if len(text.split()) > slot.cap:
            return None, f"{lang} has {len(text.split())} words, at most {slot.cap}"
        if len(text) > limit:
            return None, f"{lang} is {len(text)} characters, at most {limit}"
        if slot.role != beats.CARD_ROW and _PREFIX_RE.match(text):
            return None, f"{lang} starts with a speaker name and a colon: say only the words"
        if _META_RE.search(text):
            return None, f"{lang} talks about the lesson, the quiz or the story itself"
        if any(p.search(unaccented(text)) for p in blocked):
            return None, f"{lang} uses a name from the lesson's own example"
        out[lang] = text
    if french_in(out["en"]):
        return None, "the en text looks French"
    if out["en"].lower() == out["fr"].lower() and len(out["en"].split()) > 3:
        return None, "en and fr are the same text"
    if slot.role not in (beats.CARD_ROW, beats.LABEL):
        keys = repeat_keys({"type": "say", **out})
        told = next((ctx.earlier_line_keys[k] for k in keys if k in ctx.earlier_line_keys), None)
        if told is not None:
            return None, f"this line was already said in chapter {told}: write a new one"
        if seen is not None:
            if keys & seen:
                return None, "another slot already says this: write a different line"
            seen.update(keys)
    return out, None


def _parse(answer: Any) -> dict[str, Any]:
    if not isinstance(answer, dict):
        return {}
    inner = answer.get("slots")
    if isinstance(inner, dict) and "en" not in inner:
        answer = inner
    return {k: v for k, v in answer.items() if isinstance(k, str) and not k.startswith("__")}


# -- the fill loop ---------------------------------------------------------------------------


async def fill_script(
    script: beats.Script,
    ctx: Any,
    ask: Ask,
    *,
    repairs: int,
) -> SlotResult:
    """Fill every slot of ``script``: one call, one retry of the failed slots, then code lines.

    ``ask(user, *, repair, max_tokens)`` makes a model call and returns the parsed
    answer (``None`` when unreadable). A failure of the FIRST call is the caller's
    (it propagates: no story at all is the classic path's business); a failed retry
    only leaves the slots to their fallback.
    """
    from app.domain.services.story_calls import StoryCallTimeout, slots_max_tokens

    result = SlotResult(total=len(script.slots))
    blocked = _blocked(ctx)
    pending = list(script.slots)
    seen: set[tuple[str, str]] = set()
    previous: dict[str, Any] = {}
    reasons: dict[str, str] = {}
    attempts = 1 + max(0, min(repairs, 1))
    for number in range(attempts):
        if not pending:
            break
        if number == 0:
            message = build_message(ctx, script, pending)
        else:
            message = build_repair_message(ctx, script, reasons, previous)
        result.calls += 1
        try:
            answer = await ask(
                message, repair=number > 0, max_tokens=slots_max_tokens(len(pending))
            )
        except Exception as exc:
            if number == 0 or isinstance(exc, SoftTimeLimitExceeded | StoryCallTimeout):
                raise
            logger.warning("Slot retry failed; the code's lines are used", error=str(exc)[:200])
            break
        parsed = _parse(answer)
        previous.update(parsed)
        failed: list[beats.Slot] = []
        reasons = {}
        for slot in pending:
            value, why = check_value(slot, parsed.get(slot.id), ctx, blocked, seen)
            if value is None:
                failed.append(slot)
                reasons[slot.id] = why or "unusable"
                if number == 0:
                    result.invalid.append(slot.id)
            else:
                slot.apply(value)
        pending = failed
    for slot in pending:
        result.fallbacks.append(slot.id)
        slot.apply(slot.fallback)
    beats.finalize(script, ctx)
    logger.info(
        "Story slots filled",
        slug=getattr(ctx, "slug", None),
        slots=result.total,
        calls=result.calls,
        invalid=len(result.invalid),
        fallbacks=len(result.fallbacks),
    )
    return result
