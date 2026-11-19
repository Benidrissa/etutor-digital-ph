"""Request/task-scoped context for the AI usage ledger (#2629).

Call sites deep in the AI stack (providers, embeddings, image/TTS clients)
record usage without knowing *why* they were called. This contextvar carries
the business context (feature, user, course, module) down from the entry point
— set once per HTTP request (``deps_local_auth``) or Celery task body — so the
recorder can attribute every row without threading arguments through every
layer. Contextvars copy into asyncio child tasks automatically, so concurrent
sub-batches inherit the caller's context.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class AiCallContext:
    feature: str | None = None
    user_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    module_id: uuid.UUID | None = None
    #: What the call is for inside its feature (#2713: a story's "slots", "repair"...).
    #: It feeds the run's :class:`UsageTally`, which counts a repair under ``repair``.
    call_kind: str | None = None
    #: The kind this call repairs or retries (#2735). The ledger columns
    #: ``call_kind`` / ``is_repair`` come from it; the tally never reads it.
    repair_of: str | None = None


_context: ContextVar[AiCallContext | None] = ContextVar("ai_call_context", default=None)


def current_ai_context() -> AiCallContext:
    return _context.get() or AiCallContext()


def set_ai_context_user(user_id: uuid.UUID | str | None) -> None:
    """Attach the authenticated user to the current context (auth layer only)."""
    try:
        uid = uuid.UUID(str(user_id)) if user_id else None
    except (ValueError, TypeError):
        uid = None
    _context.set(replace(current_ai_context(), user_id=uid))


def set_ai_context(
    feature: str | None = None,
    *,
    user_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    module_id: uuid.UUID | None = None,
) -> None:
    """Merge fields into the current context without a ``with`` scope.

    For task-lifetime attribution: Celery task bodies and streaming request
    handlers, where the surrounding asyncio task is discarded when the work
    ends so no reset is needed. Prefer :func:`ai_usage_context` inside shared
    request paths.
    """
    current = current_ai_context()
    _context.set(
        AiCallContext(
            feature=feature or current.feature,
            user_id=user_id or current.user_id,
            course_id=course_id or current.course_id,
            module_id=module_id or current.module_id,
            call_kind=current.call_kind,
            repair_of=current.repair_of,
        )
    )


@contextmanager
def ai_usage_context(
    feature: str | None = None,
    *,
    user_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    module_id: uuid.UUID | None = None,
    only_if_unset: bool = False,
    call_kind: str | None = None,
    repair_of: str | None = None,
) -> Iterator[None]:
    """Merge the given fields into the current context for the ``with`` block.

    Unset fields inherit the surrounding context, so a request-level ``user_id``
    survives a service-level ``feature`` override. ``only_if_unset=True`` applies
    ``feature`` only when none is set yet (e.g. the retriever's ``rag_query``
    fallback must not clobber ``tutor_chat``).
    """
    current = current_ai_context()
    new_feature = feature
    if only_if_unset and current.feature:
        new_feature = current.feature
    token = _context.set(
        AiCallContext(
            feature=new_feature or current.feature,
            user_id=user_id or current.user_id,
            course_id=course_id or current.course_id,
            module_id=module_id or current.module_id,
            call_kind=call_kind or current.call_kind,
            repair_of=repair_of or current.repair_of,
        )
    )
    try:
        yield
    finally:
        _context.reset(token)


@dataclass
class UsageTally:
    """Model calls and output tokens of one run, by kind of call (#2713).

    ``calls`` is counted where the call is made; ``output_tokens`` is what the
    provider reported to the AI usage ledger for it (:func:`note_usage`) and
    ``estimated_tokens`` a length-based estimate, for a provider that reports
    nothing. Shared by every task of the run (a plain object in a context var).
    """

    calls: dict[str, int] = field(default_factory=dict)
    output_tokens: dict[str, int] = field(default_factory=dict)
    estimated_tokens: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, dict[str, int | bool]]:
        out: dict[str, dict[str, int | bool]] = {}
        for kind in sorted(set(self.calls) | set(self.output_tokens)):
            reported = self.output_tokens.get(kind, 0)
            entry: dict[str, int | bool] = {
                "calls": self.calls.get(kind, 0),
                "output_tokens": reported or self.estimated_tokens.get(kind, 0),
            }
            if not reported and entry["output_tokens"]:
                entry["estimated"] = True
            out[kind] = entry
        return out


_tally: ContextVar[UsageTally | None] = ContextVar("ai_usage_tally", default=None)


@contextmanager
def usage_tally() -> Iterator[UsageTally]:
    """Count the model calls made inside (and in the tasks they start)."""
    tally = UsageTally()
    token = _tally.set(tally)
    try:
        yield tally
    finally:
        _tally.reset(token)


def current_tally() -> UsageTally | None:
    return _tally.get()


def note_call(kind: str, *, estimated_tokens: int = 0) -> None:
    """One call of ``kind`` made (and, once answered, its estimated output tokens)."""
    tally = _tally.get()
    if tally is None:
        return
    if estimated_tokens:
        tally.estimated_tokens[kind] = tally.estimated_tokens.get(kind, 0) + estimated_tokens
    else:
        tally.calls[kind] = tally.calls.get(kind, 0) + 1


def note_usage(kind: str | None, output_tokens: Any) -> None:
    """The output tokens the ledger recorded for a call of ``kind`` (never raises)."""
    tally = _tally.get()
    if tally is None or not kind or not isinstance(output_tokens, int):
        return
    tally.output_tokens[kind] = tally.output_tokens.get(kind, 0) + output_tokens
