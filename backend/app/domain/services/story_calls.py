"""The story generator's model calls, each bounded in tokens and in time (#2702).

A module story run once lost a whole forced regeneration to one runaway call:
a chapter story at the content model's 64,000-token ceiling ran 1,068 s,
cost about a dollar and was unusable; the next call was killed by the task's
soft time limit, and the deadline guard — checked only between calls — never
handed over to a continuation. So, here:

* **tokens** — each kind of call has its own ``max_tokens``
  (:data:`MAX_TOKENS`), sized from the real answers with headroom, not the
  content model's ceiling: a runaway is cut at a few thousand tokens;
* **truncation** — an answer cut at that ceiling (``stop_reason`` =
  ``max_tokens``, :class:`TruncatedResponse`) is a failure of the call: it is
  never sent back for a repair at the same budget, but asked again once with
  a "be concise" notice (:func:`concise`); a second cut ends that call's loop;
* **time** — each call runs under ``min(cap of its kind, the run's deadline −
  margin)`` (:func:`call_bound`); past it, :class:`StoryCallTimeout` with its
  ``reason``. Past the **deadline**, the run stops cleanly, keeps what is done
  (packs, finished chapters) and the task dispatches its continuation. Past the
  kind's **cap** with time left, the call failed: a chapter, a pack or the
  rally is recorded as failed like one that could not be made valid (its
  failure counter is kept, so the cap stops paying across runs), and the run
  goes on with the next one.

There is no streaming abort. The Anthropic provider streams, but the
OpenAI-compatible one (Kimi) does not (``complete()`` makes one request), and
a length or repetition abort would need both: the tight ``max_tokens`` is
what makes a degenerate answer cost cents rather than a dollar. Streaming for
Kimi is out of scope here.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog

from app.ai.claude_service import TruncatedResponse
from app.ai.usage_context import ai_usage_context, note_call

logger = structlog.get_logger(__name__)

#: The most output tokens a call of each kind may write. The fixture module's
#: answers (3.2 characters a token): bible ~1.1k, plan ~2.7k (3 chapters),
#: pack ~1.5-2.3k, chapter story ~2.5-3k, rally story ~1.6k; staging chapters
#: of a long lesson run to 6-8k. Each limit is about 1.5-2x the largest real
#: answer: a long module or chapter still fits, a runaway does not.
MAX_TOKENS: dict[str, int] = {
    "bible": 6_000,
    "plan": 12_000,
    "pack": 8_000,
    "story": 12_000,
    "rally": 10_000,
    "judge": 2_000,
    # #2713: the slot builder's lines, ~1k tokens for a chapter of 20 slots; the
    # limit grows with the slots (:func:`slots_max_tokens`), this is its ceiling.
    "slots": 6_000,
}
#: The episode plan grows with the module: a global block, then a few beats per
#: chapter. Its limit is this base plus this much per chapter, within bounds.
PLAN_BASE_TOKENS, PLAN_TOKENS_PER_CHAPTER = 4_000, 1_500
PLAN_MIN_TOKENS, PLAN_MAX_TOKENS = 8_000, 24_000


def plan_max_tokens(chapters: int) -> int:
    """The plan's ``max_tokens`` for a module of ``chapters`` lesson chapters.

    3 chapters → 8,500; 6 → 13,000; 10 → 19,000; 14 or more → 24,000. A long
    module's plan is never cut twice and dropped for one made in code.
    """
    tokens = PLAN_BASE_TOKENS + PLAN_TOKENS_PER_CHAPTER * max(int(chapters), 1)
    return max(PLAN_MIN_TOKENS, min(PLAN_MAX_TOKENS, tokens))


#: A slots answer: the keys and a little each slot, plus ~70 tokens a slot (two
#: lines of up to 12-20 words and their quotes), within bounds.
SLOTS_BASE_TOKENS, SLOTS_TOKENS_PER_SLOT = 600, 90
SLOTS_MIN_TOKENS = 1_500


def slots_max_tokens(slots: int) -> int:
    """The ``max_tokens`` of a slots call for ``slots`` slots (never above the kind's ceiling)."""
    tokens = SLOTS_BASE_TOKENS + SLOTS_TOKENS_PER_SLOT * max(int(slots), 1)
    return max(SLOTS_MIN_TOKENS, min(MAX_TOKENS["slots"], tokens))


#: The kind that counts a repair call in the run's counters (#2713).
REPAIR_KIND = "repair"

#: The admin settings of the story generator (#2713).
MODEL_SETTING = "ai-model-story"
REPAIR_SETTING = "story-max-repair-calls"
VARIANT_SETTING = "story-builder-variant"
CLASSIC, SLOTS = "classic", "slots"
#: The value of ``ai-model-story`` that means "the content model".
CONTENT_MODEL = "content"
#: What the repair budget was before the setting (a pack's repairs; a screenplay's is 1).
DEFAULT_REPAIR_CALLS = 1
MAX_REPAIR_SETTING = 2


def _setting(key: str, default: Any) -> Any:
    try:
        from app.domain.services.platform_settings_service import SettingsCache

        return SettingsCache.instance().get(key, default)
    except Exception:  # a missing cache is the default, never a failed story
        return default


def story_model() -> str | None:
    """The model of story writing and repair, or ``None``: the content model (#2713)."""
    value = str(_setting(MODEL_SETTING, CONTENT_MODEL) or "").strip()
    return None if value in ("", CONTENT_MODEL) else value


def repair_budget() -> int:
    """Extra calls a pack, a screenplay or a slot line may be repaired with (0-2)."""
    value = _setting(REPAIR_SETTING, DEFAULT_REPAIR_CALLS)
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return DEFAULT_REPAIR_CALLS
    try:
        return max(0, min(MAX_REPAIR_SETTING, int(value)))
    except ValueError:
        return DEFAULT_REPAIR_CALLS


def builder_variant() -> str:
    """``classic`` (the model writes the screenplay) or ``slots`` (code builds it)."""
    value = str(_setting(VARIANT_SETTING, CLASSIC) or "").strip().lower()
    return SLOTS if value == SLOTS else CLASSIC


def _cap_for(tokens: int) -> float:
    """The longest a call may run: its token limit at a slow 25 tokens a second,
    plus a minute for the request (a 64k answer took 1,068 s at about 60 a second)."""
    return tokens / 25 + 60


#: The longest a call of each kind may run, in seconds (:func:`_cap_for`).
CALL_CAPS: dict[str, float] = {kind: _cap_for(tokens) for kind, tokens in MAX_TOKENS.items()}
#: Kept before the run's deadline when bounding a call: time to save what is
#: done and dispatch the continuation (the deadline itself is 150 s before the
#: task's soft time limit).
CALL_MARGIN_S = 30.0

#: The notice of the one retry of a truncated answer.
CONCISE_NOTICE = (
    "IMPORTANT: your previous answer was cut off at the length limit and could not be"
    " used. Answer again, complete and SHORTER: keep every text brief, never repeat a"
    " line or a list, close every bracket, and end with the closing key."
)


#: Why a call was stopped: the run's deadline came (hand over), or the call
#: ran past its kind's cap with time left (a failure of that call).
DEADLINE, CAP = "deadline", "cap"


class StoryCallTimeout(Exception):
    """A model call ran past its time; ``reason`` says which (:data:`DEADLINE`, :data:`CAP`)."""

    def __init__(self, kind: str, timeout: float, reason: str = DEADLINE) -> None:
        super().__init__(f"The {kind} call ran past {timeout:.0f} s ({reason})")
        self.kind = kind
        self.timeout = timeout
        self.reason = reason

    @property
    def at_deadline(self) -> bool:
        return self.reason == DEADLINE


#: The run's deadline: ``(deadline, clock)``; ``None`` outside a module run.
_DEADLINE: ContextVar[tuple[float, Callable[[], float]] | None] = ContextVar(
    "story_call_deadline", default=None
)


@contextmanager
def run_deadline(
    deadline: float | None, clock: Callable[[], float] = time.monotonic
) -> Iterator[None]:
    """Bound every story call made inside (and in the tasks it starts) by ``deadline``."""
    token = _DEADLINE.set((deadline, clock) if deadline is not None else None)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def call_bound(kind: str, *, max_tokens: int | None = None) -> tuple[float, str]:
    """``(timeout, reason)``: the kind's cap, or the time left before the run's
    deadline less the margin when that is shorter (then the reason is the deadline)."""
    cap = _cap_for(max_tokens) if max_tokens else CALL_CAPS.get(kind, CALL_CAPS["story"])
    bound = _DEADLINE.get()
    if bound is None:
        return cap, CAP
    deadline, clock = bound
    left = deadline - clock() - CALL_MARGIN_S
    if left < cap:
        return max(0.0, left), DEADLINE
    return cap, CAP


def call_timeout(kind: str, *, max_tokens: int | None = None) -> float:
    """``min(cap of the kind, time left before the run's deadline − margin)``, at least 0."""
    return call_bound(kind, max_tokens=max_tokens)[0]


def bounded(service: Any, kind: str, max_tokens: int | None = None) -> Any:
    """``service`` writing at most :data:`MAX_TOKENS` of ``kind`` (a fake is used as is)."""
    limit = getattr(service, "with_max_tokens", None)
    tokens = max_tokens or MAX_TOKENS.get(kind, MAX_TOKENS["story"])
    return limit(tokens) if callable(limit) else service


def concise(message: str) -> str:
    """``message`` with the notice of the one retry of a truncated answer."""
    return f"{CONCISE_NOTICE}\n\n{message}"


def _estimate_tokens(answer: Any) -> int:
    """About how many tokens an answer took (3.2 characters a token), for a counter."""
    try:
        return max(1, round(len(json.dumps(answer, ensure_ascii=False, default=str)) / 3.2))
    except Exception:
        return 0


async def structured_call(
    service: Any,
    system: str,
    user: str,
    *,
    kind: str,
    max_tokens: int | None = None,
    repair: bool = False,
    repair_of: str | None = None,
) -> Any:
    """One model call of ``kind``: its ``max_tokens`` (or ``max_tokens``), under its timeout.

    The run's counters (:class:`~app.ai.usage_context.UsageTally`) count it as
    ``kind``, or as ``repair`` when ``repair`` (the limits are the kind's).
    The AI usage ledger (#2735) records the kind a repair repairs, flagged
    ``is_repair``: ``kind`` when ``repair``, or ``repair_of`` for a retry that
    keeps its kind in the counters (the plan's repair, the bible's retry).

    Raises :class:`StoryCallTimeout` past the timeout (or when no time is
    left), with its reason; :class:`TruncatedResponse` for an answer cut at
    ``max_tokens``; and lets every other error through.
    """
    timeout, reason = call_bound(kind, max_tokens=max_tokens)
    if timeout <= 0:
        raise StoryCallTimeout(kind, 0.0, DEADLINE)
    client = bounded(service, kind, max_tokens)
    scope = asyncio.timeout(timeout)
    label = REPAIR_KIND if repair else kind
    repairs = repair_of or (kind if repair else None)
    note_call(label)
    try:
        async with scope:
            with ai_usage_context(call_kind=label, repair_of=repairs):
                answer = await client.generate_structured_content(
                    system, user, "story", max_retries=0
                )
            note_call(label, estimated_tokens=_estimate_tokens(answer))
            return answer
    except TimeoutError as exc:
        if not scope.expired():
            raise  # the provider's own timeout: an outage, not our deadline
        logger.warning(
            "Story model call timed out", kind=kind, timeout_s=round(timeout), reason=reason
        )
        raise StoryCallTimeout(kind, timeout, reason) from exc


__all__ = [
    "CAP",
    "DEADLINE",
    "CALL_CAPS",
    "CALL_MARGIN_S",
    "MAX_TOKENS",
    "CLASSIC",
    "REPAIR_KIND",
    "SLOTS",
    "StoryCallTimeout",
    "TruncatedResponse",
    "builder_variant",
    "repair_budget",
    "slots_max_tokens",
    "story_model",
    "bounded",
    "call_bound",
    "call_timeout",
    "plan_max_tokens",
    "concise",
    "run_deadline",
    "structured_call",
]
