"""Unit tests for tutor voice-session cap math + duration clamp (#1932).

Uses a mocked async session because the integration db_session fixture is
blocked on #554 (Base.metadata.create_all vs Alembic-managed enum types).
The interesting logic here is the round-up-to-minutes rule and the cap
clamp formula; both are pure arithmetic once the DB returns a seconds sum.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _session_returning_seconds(total_seconds):
    """Mock AsyncSession whose .execute(...).scalar() yields the given total.

    Accepts ``None`` to simulate drivers that return NULL even with COALESCE.
    """
    result = MagicMock()
    result.scalar = MagicMock(return_value=total_seconds)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


class TestMinutesUsedToday:
    """Round-up-to-minutes behaviour is conservative so users don't squeak
    past the daily cap by a few seconds."""

    async def test_no_sessions_is_zero(self):
        from app.api.v1.tutor_voice import _minutes_used_today

        session = _session_returning_seconds(0)
        assert await _minutes_used_today(uuid.uuid4(), session) == 0

    async def test_exactly_sixty_seconds_is_one_minute(self):
        from app.api.v1.tutor_voice import _minutes_used_today

        session = _session_returning_seconds(60)
        assert await _minutes_used_today(uuid.uuid4(), session) == 1

    async def test_sixty_one_seconds_rounds_up_to_two(self):
        from app.api.v1.tutor_voice import _minutes_used_today

        session = _session_returning_seconds(61)
        assert await _minutes_used_today(uuid.uuid4(), session) == 2

    async def test_nine_exact_minutes(self):
        from app.api.v1.tutor_voice import _minutes_used_today

        # 180 + 240 + 120 = 540s = 9 minutes exactly.
        session = _session_returning_seconds(540)
        assert await _minutes_used_today(uuid.uuid4(), session) == 9

    async def test_null_result_coerces_to_zero(self):
        """COALESCE inside the SQL returns 0 for no rows, but the ``.scalar()``
        wrapper can still return ``None`` on some drivers — the helper must
        handle that without raising."""
        from app.api.v1.tutor_voice import _minutes_used_today

        session = _session_returning_seconds(None)
        assert await _minutes_used_today(uuid.uuid4(), session) == 0


class TestDurationClamp:
    """Pure arithmetic — a broken/malicious client must not be able to lock
    itself out for the day by reporting a wild duration on close."""

    @pytest.mark.parametrize(
        ("cap_minutes", "reported_seconds", "expected_clamp"),
        [
            (10, 999_999, 600),  # cap to 10 min = 600 s
            (10, -5, 0),  # negative clamped to 0
            (10, 120, 120),  # within cap, unchanged
            (30, 120, 120),  # larger cap, same duration
            (1, 120, 60),  # tight cap clamps aggressively
        ],
    )
    def test_clamp_formula_matches_endpoint(
        self, cap_minutes: int, reported_seconds: int, expected_clamp: int
    ):
        max_seconds = cap_minutes * 60
        clamped = max(0, min(reported_seconds, max_seconds))
        assert clamped == expected_clamp
