"""Regression tests for issue #1625 — tutor chat must commit the new
conversation row before yielding its `conversation_id` to the client,
so a follow-up GET on that id (from a different HTTP/DB session)
returns 200 instead of 404.

Test approach: existing DB integration tests in this repo are all
`@pytest.mark.skip` because conftest's `create_all` can't emit enum
types that live behind `create_type=False`. So we verify the invariant
with an AsyncMock session and assert that `_get_or_create_conversation`
calls `session.commit()` (not just `session.flush()`) on the new-row path.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

from app.domain.services.tutor_service import TutorService


class _NullResult:
    def scalar_one_or_none(self):
        return None


class _FoundResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


async def test_new_conversation_is_committed_not_just_flushed() -> None:
    """When creating a new conversation, the helper must `await session.commit()`."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_NullResult())
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    svc = TutorService(
        anthropic_client=MagicMock(),
        semantic_retriever=MagicMock(),
        embedding_service=MagicMock(),
    )
    result = await svc._get_or_create_conversation(
        user_id=uuid.uuid4(),
        module_id=None,
        conversation_id=None,
        session=session,
    )

    assert result is not None
    assert session.add.call_count == 1, "new conversation must be staged"
    # The fix for #1625: commit (not just flush) so a fresh session sees it.
    assert session.commit.await_count >= 1, (
        "new conversation must be committed before the helper returns "
        "(#1625) — a bare flush() left the row invisible to follow-up GETs"
    )


async def test_existing_conversation_is_fetched_not_recreated() -> None:
    """When passed an existing conversation_id, helper must fetch and
    return without creating a new row (no add/commit)."""
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        module_id=None,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FoundResult(existing))
    session.add = MagicMock()
    session.commit = AsyncMock()

    svc = TutorService(
        anthropic_client=MagicMock(),
        semantic_retriever=MagicMock(),
        embedding_service=MagicMock(),
    )
    fetched = await svc._get_or_create_conversation(
        user_id=existing.user_id,
        module_id=None,
        conversation_id=existing.id,
        session=session,
    )

    assert fetched is existing
    assert session.add.call_count == 0, "existing conversation must not be re-added"
    assert session.commit.await_count == 0, "existing path must not commit"


# Guard against a silent regression back to `flush()` without commit.
async def test_create_path_does_not_only_flush() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_NullResult())
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    svc = TutorService(
        anthropic_client=MagicMock(),
        semantic_retriever=MagicMock(),
        embedding_service=MagicMock(),
    )
    await svc._get_or_create_conversation(
        user_id=uuid.uuid4(),
        module_id=None,
        conversation_id=None,
        session=session,
    )

    # flush() alone would be the pre-fix bug. commit() is the fix.
    assert session.commit.await_count >= 1

    # Ensure we don't accidentally re-introduce a bare flush-without-commit
    # by checking commit() ran *at some point* — not the specific ordering
    # (the helper may refresh/flush internally if extended later).
    assert session.method_calls  # sanity: the session was exercised
    _ = call  # silence unused-import check if lints tighten
