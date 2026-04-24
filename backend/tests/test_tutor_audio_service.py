"""Unit tests for TutorAudioService — caching, validation, and error paths (#1932)."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.conversation import TutorConversation
from app.domain.models.tutor_voice import TutorMessageAudio
from app.domain.models.user import User
from app.domain.services.tutor_audio_service import TutorAudioService


def _make_conversation(user_id: uuid.UUID, messages: list[dict]) -> TutorConversation:
    return TutorConversation(
        id=uuid.uuid4(),
        user_id=user_id,
        module_id=None,
        messages=messages,
        created_at=datetime.utcnow(),
    )


async def _persisted_conversation(db_session, messages: list[dict]) -> TutorConversation:
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4()}@example.com",
        preferred_language="fr",
        current_level=2,
        country="CI",
    )
    db_session.add(user)
    await db_session.flush()
    conv = _make_conversation(user.id, messages)
    db_session.add(conv)
    await db_session.commit()
    return conv


class TestValidation:
    async def test_rejects_out_of_range_index(self, db_session):
        conv = await _persisted_conversation(
            db_session,
            [{"role": "assistant", "content": "hi", "timestamp": "2026-04-24T00:00:00"}],
        )
        service = TutorAudioService()
        with pytest.raises(ValueError, match="out of range"):
            await service.synthesize_for_message(
                conversation=conv,
                message_index=99,
                language="fr",
                session=db_session,
            )

    async def test_rejects_user_message(self, db_session):
        conv = await _persisted_conversation(
            db_session,
            [{"role": "user", "content": "question", "timestamp": "2026-04-24T00:00:00"}],
        )
        service = TutorAudioService()
        with pytest.raises(ValueError, match="Only assistant"):
            await service.synthesize_for_message(
                conversation=conv,
                message_index=0,
                language="fr",
                session=db_session,
            )

    async def test_rejects_empty_content(self, db_session):
        conv = await _persisted_conversation(
            db_session,
            [{"role": "assistant", "content": "  ", "timestamp": "2026-04-24T00:00:00"}],
        )
        service = TutorAudioService()
        with pytest.raises(ValueError, match="empty"):
            await service.synthesize_for_message(
                conversation=conv,
                message_index=0,
                language="fr",
                session=db_session,
            )


class TestCaching:
    @pytest.fixture
    def mock_service(self):
        service = TutorAudioService()
        service._call_tts = AsyncMock(return_value=b"\x00" * 12288)  # ~2 sec
        upload_mock = AsyncMock(return_value="https://minio.example/tutor-audio/x.opus")
        service._storage = MagicMock()
        service._storage.upload_bytes = upload_mock
        return service

    async def test_first_call_synthesizes(self, db_session, mock_service):
        conv = await _persisted_conversation(
            db_session,
            [
                {"role": "user", "content": "q", "timestamp": "2026-04-24T00:00:00"},
                {
                    "role": "assistant",
                    "content": "Photosynthesis is the process…",
                    "timestamp": "2026-04-24T00:00:01",
                },
            ],
        )

        record = await mock_service.synthesize_for_message(
            conversation=conv,
            message_index=1,
            language="en",
            session=db_session,
        )

        assert record.status == "ready"
        assert record.storage_url == "https://minio.example/tutor-audio/x.opus"
        assert mock_service._call_tts.call_count == 1

    async def test_second_call_returns_cache(self, db_session, mock_service):
        conv = await _persisted_conversation(
            db_session,
            [
                {
                    "role": "assistant",
                    "content": "Hi there.",
                    "timestamp": "2026-04-24T00:00:00",
                },
            ],
        )
        first = await mock_service.synthesize_for_message(
            conversation=conv,
            message_index=0,
            language="en",
            session=db_session,
        )
        assert mock_service._call_tts.call_count == 1

        second = await mock_service.synthesize_for_message(
            conversation=conv,
            message_index=0,
            language="en",
            session=db_session,
        )

        assert second.id == first.id
        assert second.storage_url == first.storage_url
        # Cached: TTS not re-invoked.
        assert mock_service._call_tts.call_count == 1

    async def test_different_language_synthesizes_separately(self, db_session, mock_service):
        conv = await _persisted_conversation(
            db_session,
            [
                {
                    "role": "assistant",
                    "content": "Bonjour.",
                    "timestamp": "2026-04-24T00:00:00",
                },
            ],
        )
        await mock_service.synthesize_for_message(
            conversation=conv,
            message_index=0,
            language="fr",
            session=db_session,
        )
        await mock_service.synthesize_for_message(
            conversation=conv,
            message_index=0,
            language="en",
            session=db_session,
        )

        assert mock_service._call_tts.call_count == 2


class TestFailurePath:
    async def test_tts_failure_persists_failed_status(self, db_session):
        conv = await _persisted_conversation(
            db_session,
            [
                {
                    "role": "assistant",
                    "content": "Text to synthesize.",
                    "timestamp": "2026-04-24T00:00:00",
                },
            ],
        )
        service = TutorAudioService()
        service._call_tts = AsyncMock(side_effect=RuntimeError("OpenAI down"))

        with pytest.raises(RuntimeError):
            await service.synthesize_for_message(
                conversation=conv,
                message_index=0,
                language="fr",
                session=db_session,
            )

        # Record persisted with status=failed so the UI shows "unavailable"
        from sqlalchemy import select

        result = await db_session.execute(
            select(TutorMessageAudio).where(
                TutorMessageAudio.conversation_id == conv.id,
            )
        )
        record = result.scalar_one()
        assert record.status == "failed"
        assert "OpenAI down" in (record.error_message or "")
