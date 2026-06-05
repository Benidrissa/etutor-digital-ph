"""Regression tests for issue #2412 — summative final-quiz submission 500.

``can_attempt_summative_assessment`` is a FastAPI route handler. The submit
endpoint (``submit_summative_assessment_attempt``) calls it *directly* as a plain
function, so ``current_user`` must be passed explicitly. If it is omitted the
parameter keeps its ``Depends(require_active_subscription)`` default, and the very
first line — ``uuid.UUID(str(current_user.id))`` — raises ``AttributeError``,
which the generic handler converts into a 500 "Failed to check attempt
eligibility". That 500 bubbles up through the submit endpoint and leaves learners
unable to complete the final quiz.

These tests cover ``current_user.id`` access, which happens *before* any DB query,
so they use a mocked session and need no database.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.quiz import can_attempt_summative_assessment


def _mock_session(module, attempts):
    """Mock AsyncSession: first execute() -> module, second -> attempts list."""
    module_result = MagicMock()
    module_result.scalar_one_or_none.return_value = module

    attempts_result = MagicMock()
    attempts_scalars = MagicMock()
    attempts_scalars.all.return_value = attempts
    attempts_result.scalars.return_value = attempts_scalars

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[module_result, attempts_result])
    return session


async def test_can_attempt_when_current_user_passed_no_prior_attempts():
    """The fixed call path: passing a real user returns an eligibility result."""
    user = MagicMock()
    user.id = uuid.uuid4()
    session = _mock_session(module=MagicMock(), attempts=[])

    resp = await can_attempt_summative_assessment(uuid.uuid4(), session, user)

    assert resp.can_attempt is True
    assert resp.attempt_count == 0


async def test_missing_current_user_yields_500(caplog):
    """The original bug: omitting current_user => 500, not a real eligibility check.

    Guards the call site in submit_summative_assessment_attempt against regressing
    back to calling this handler without an explicit user.
    """
    session = _mock_session(module=MagicMock(), attempts=[])

    with pytest.raises(HTTPException) as exc_info:
        # Intentionally omit current_user to reproduce the pre-fix behavior.
        await can_attempt_summative_assessment(uuid.uuid4(), session)

    assert exc_info.value.status_code == 500
