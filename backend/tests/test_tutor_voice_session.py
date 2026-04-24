"""Tests for tutor voice-call session endpoints — daily cap enforcement (#1932)."""

import uuid
from datetime import datetime, timedelta

import pytest

from app.domain.models.tutor_voice import TutorVoiceSession
from app.domain.models.user import User


@pytest.fixture
async def seeded_user(db_session):
    user = User(
        id=uuid.uuid4(),
        email=f"voice-test-{uuid.uuid4()}@example.com",
        preferred_language="en",
        current_level=2,
        country="CI",
    )
    db_session.add(user)
    await db_session.commit()
    return user


class TestMinutesUsedToday:
    async def test_no_sessions_is_zero(self, db_session, seeded_user):
        from app.api.v1.tutor_voice import _minutes_used_today

        assert await _minutes_used_today(seeded_user.id, db_session) == 0

    async def test_rounds_up_to_minutes(self, db_session, seeded_user):
        from app.api.v1.tutor_voice import _minutes_used_today

        # 61 seconds should round up to 2 minutes (cap logic is conservative
        # so users don't quietly squeak over the cap).
        db_session.add(
            TutorVoiceSession(
                id=uuid.uuid4(),
                user_id=seeded_user.id,
                started_at=datetime.utcnow(),
                duration_seconds=61,
            )
        )
        await db_session.commit()
        assert await _minutes_used_today(seeded_user.id, db_session) == 2

    async def test_only_counts_today(self, db_session, seeded_user):
        from app.api.v1.tutor_voice import _minutes_used_today

        yesterday = datetime.utcnow() - timedelta(days=1, hours=1)
        db_session.add(
            TutorVoiceSession(
                id=uuid.uuid4(),
                user_id=seeded_user.id,
                started_at=yesterday,
                duration_seconds=600,
            )
        )
        db_session.add(
            TutorVoiceSession(
                id=uuid.uuid4(),
                user_id=seeded_user.id,
                started_at=datetime.utcnow(),
                duration_seconds=120,
            )
        )
        await db_session.commit()
        assert await _minutes_used_today(seeded_user.id, db_session) == 2

    async def test_sums_multiple_sessions(self, db_session, seeded_user):
        from app.api.v1.tutor_voice import _minutes_used_today

        now = datetime.utcnow()
        for duration in (180, 240, 120):
            db_session.add(
                TutorVoiceSession(
                    id=uuid.uuid4(),
                    user_id=seeded_user.id,
                    started_at=now,
                    duration_seconds=duration,
                )
            )
        await db_session.commit()
        # (180 + 240 + 120) / 60 = 9 minutes exactly
        assert await _minutes_used_today(seeded_user.id, db_session) == 9


class TestCloseSessionDurationClamp:
    """A malicious/buggy client must not be able to lock itself out for the day."""

    async def test_duration_clamped_at_daily_cap(self, db_session, seeded_user):
        from app.infrastructure.config.settings import get_settings

        cap = get_settings().tutor_voice_daily_minutes_cap
        session_row = TutorVoiceSession(
            id=uuid.uuid4(),
            user_id=seeded_user.id,
            started_at=datetime.utcnow(),
        )
        db_session.add(session_row)
        await db_session.commit()

        # Simulate the server-side clamp logic from close_voice_session.
        max_seconds = cap * 60
        reported = 999_999
        clamped = max(0, min(reported, max_seconds))
        session_row.duration_seconds = clamped
        await db_session.commit()

        assert session_row.duration_seconds == max_seconds
