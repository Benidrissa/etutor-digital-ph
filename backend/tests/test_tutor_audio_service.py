"""Unit tests for TutorAudioService — validation, caching, and error paths (#1932).

Uses a mocked async session because the integration db_session fixture is
blocked on #554 (Base.metadata.create_all vs Alembic-managed enum types —
test_courses.py marks its DB tests skipped for the same reason).

Cache-hit + failure-path tests that need real ORM transaction semantics are
skipped rather than faked badly; the pure-logic branches are covered here.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.tutor_voice import TutorMessageAudio
from app.domain.services.tutor_audio_service import TutorAudioService

_SKIP_554 = pytest.mark.skip(
    reason="#554 — db_session fixture blocked by enum create_all; same pattern as test_courses.py"
)


def _conversation(messages: list[dict]) -> SimpleNamespace:
    """Minimal TutorConversation stand-in — the service only reads `.id`,
    `.user_id`, and `.messages`. A real model instance isn't required for
    validation/synthesis-path tests."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        module_id=None,
        messages=messages,
    )


def _session_with_no_cache() -> MagicMock:
    """Async session mock whose `.execute()` returns an empty scalars() — i.e.
    no cached audio row exists."""
    scalars = MagicMock()
    scalars.first = MagicMock(return_value=None)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


class TestValidation:
    """Validation raises before any DB call, so these are true unit tests."""

    async def test_rejects_out_of_range_index(self):
        conv = _conversation(
            [{"role": "assistant", "content": "hi", "timestamp": "2026-04-24T00:00:00"}]
        )
        service = TutorAudioService(storage=MagicMock())
        session = _session_with_no_cache()

        with pytest.raises(ValueError, match="out of range"):
            await service.synthesize_for_message(
                conversation=conv,
                message_index=99,
                language="fr",
                session=session,
            )
        # No DB touched; validation short-circuits before cache lookup.
        session.execute.assert_not_awaited()

    async def test_rejects_user_message(self):
        conv = _conversation(
            [{"role": "user", "content": "question?", "timestamp": "2026-04-24T00:00:00"}]
        )
        service = TutorAudioService(storage=MagicMock())
        session = _session_with_no_cache()

        with pytest.raises(ValueError, match="Only assistant"):
            await service.synthesize_for_message(
                conversation=conv,
                message_index=0,
                language="fr",
                session=session,
            )
        session.execute.assert_not_awaited()

    async def test_rejects_empty_content(self):
        conv = _conversation(
            [{"role": "assistant", "content": "  ", "timestamp": "2026-04-24T00:00:00"}]
        )
        service = TutorAudioService(storage=MagicMock())
        session = _session_with_no_cache()

        with pytest.raises(ValueError, match="empty"):
            await service.synthesize_for_message(
                conversation=conv,
                message_index=0,
                language="fr",
                session=session,
            )
        session.execute.assert_not_awaited()


class TestCacheHitShortCircuit:
    """Cache-hit returns without invoking TTS — verifiable with a mock session
    that yields a ready-status row on its first execute()."""

    async def test_ready_cache_hit_skips_tts(self):
        conv = _conversation(
            [
                {
                    "role": "assistant",
                    "content": "Hi there.",
                    "timestamp": "2026-04-24T00:00:00",
                }
            ]
        )
        cached_row = TutorMessageAudio(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            message_index=0,
            language="en",
            status="ready",
            storage_url="https://minio.example/cached.opus",
            duration_seconds=3,
        )
        scalars = MagicMock()
        scalars.first = MagicMock(return_value=cached_row)
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)

        service = TutorAudioService(storage=MagicMock())
        service._call_tts = AsyncMock()  # must not be invoked

        record = await service.synthesize_for_message(
            conversation=conv,
            message_index=0,
            language="en",
            session=session,
        )

        assert record is cached_row
        assert record.status == "ready"
        assert record.storage_url == "https://minio.example/cached.opus"
        service._call_tts.assert_not_awaited()


@_SKIP_554
class TestCachingWriteThrough:
    """End-to-end cache write-through (INSERT on miss, SELECT on second call,
    unique-constraint race handling) requires real ORM transaction semantics.
    Tracked under #554 alongside the other skipped DB-integration tests."""

    async def test_first_call_synthesizes_and_persists(self):  # pragma: no cover
        pass

    async def test_second_call_returns_cache(self):  # pragma: no cover
        pass

    async def test_different_language_synthesizes_separately(self):  # pragma: no cover
        pass


@_SKIP_554
class TestFailurePath:
    """Persisting status=failed on TTS exception requires a working commit
    cycle on a real session. Skip alongside the other DB tests (#554)."""

    async def test_tts_failure_persists_failed_status(self):  # pragma: no cover
        pass
