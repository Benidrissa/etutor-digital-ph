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
  margin)`` (:func:`call_timeout`); past it, :class:`StoryCallTimeout`: the run
  stops cleanly, keeps what is done (packs, finished chapters) and the task
  dispatches its continuation.

There is no streaming abort: the providers stream already, and the tight
``max_tokens`` makes a degenerate answer cost cents rather than a dollar.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog

from app.ai.claude_service import TruncatedResponse

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
}
#: The longest a call of each kind may run, in seconds: its token limit at a
#: slow 25 tokens a second, plus a minute for the request (a 64k answer took
#: 1,068 s at about 60 a second).
CALL_CAPS: dict[str, float] = {kind: tokens / 25 + 60 for kind, tokens in MAX_TOKENS.items()}
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


class StoryCallTimeout(Exception):
    """A model call ran past its time: the run stops and hands over (never a failure)."""

    def __init__(self, kind: str, timeout: float) -> None:
        super().__init__(f"The {kind} call ran past {timeout:.0f} s")
        self.kind = kind
        self.timeout = timeout


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


def call_timeout(kind: str) -> float:
    """``min(cap of the kind, time left before the run's deadline − margin)``, at least 0."""
    cap = CALL_CAPS.get(kind, CALL_CAPS["story"])
    bound = _DEADLINE.get()
    if bound is None:
        return cap
    deadline, clock = bound
    return max(0.0, min(cap, deadline - clock() - CALL_MARGIN_S))


def bounded(service: Any, kind: str) -> Any:
    """``service`` writing at most :data:`MAX_TOKENS` of ``kind`` (a fake is used as is)."""
    limit = getattr(service, "with_max_tokens", None)
    return limit(MAX_TOKENS.get(kind, MAX_TOKENS["story"])) if callable(limit) else service


def concise(message: str) -> str:
    """``message`` with the notice of the one retry of a truncated answer."""
    return f"{CONCISE_NOTICE}\n\n{message}"


async def structured_call(service: Any, system: str, user: str, *, kind: str) -> Any:
    """One model call of ``kind``: its ``max_tokens``, under its timeout.

    Raises :class:`StoryCallTimeout` past the timeout (or when no time is
    left), :class:`TruncatedResponse` for an answer cut at ``max_tokens``, and
    lets every other error through.
    """
    timeout = call_timeout(kind)
    if timeout <= 0:
        raise StoryCallTimeout(kind, 0.0)
    client = bounded(service, kind)
    scope = asyncio.timeout(timeout)
    try:
        async with scope:
            return await client.generate_structured_content(system, user, "story", max_retries=0)
    except TimeoutError as exc:
        if not scope.expired():
            raise  # the provider's own timeout: an outage, not our deadline
        logger.warning("Story model call timed out", kind=kind, timeout_s=round(timeout))
        raise StoryCallTimeout(kind, timeout) from exc


__all__ = [
    "CALL_CAPS",
    "CALL_MARGIN_S",
    "MAX_TOKENS",
    "StoryCallTimeout",
    "TruncatedResponse",
    "bounded",
    "call_timeout",
    "concise",
    "run_deadline",
    "structured_call",
]
