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
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AiCallContext:
    feature: str | None = None
    user_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    module_id: uuid.UUID | None = None


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
        )
    )
    try:
        yield
    finally:
        _context.reset(token)
