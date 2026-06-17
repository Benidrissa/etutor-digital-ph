"""Regression tests for the quiz free-unit subscription gate (#2537).

`_check_subscription_or_first_unit` (the quiz endpoint's gate) used to run an
unscoped `select(ModuleUnit.order_index).where(unit_number == unit_id)` and call
`scalar_one_or_none()`. Because a unit number like "1.5" exists in many modules,
that matched multiple rows and raised MultipleResultsFound, which escaped the
route as a generic 500 ("La génération du quiz a échoué") — but only for
learners (admins/sub_admins bypass the gate). This is the same bug class fixed
for the lesson gate in #2459; these tests lock in the module-scoped, crash-proof
lookup for the quiz gate.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import MultipleResultsFound

from app.api.deps_local_auth import AuthenticatedUser
from app.api.v1.quiz import _check_subscription_or_first_unit


def _learner(role: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser({"sub": str(uuid.uuid4()), "email": "n@sira.app", "role": role})


@asynccontextmanager
async def _patched(session, *, sub):
    """Patch the gate's lazily-imported collaborators around one call."""

    async def _fake_get_db_session():
        yield session

    sub_service = MagicMock()
    sub_service.get_active_subscription = AsyncMock(return_value=sub)

    settings_cache = MagicMock()
    settings_cache.get.return_value = 2  # free-units-count

    with (
        patch(
            "app.infrastructure.persistence.database.get_db_session",
            _fake_get_db_session,
        ),
        patch(
            "app.domain.services.subscription_service.SubscriptionService",
            return_value=sub_service,
        ),
        # SettingsCache is bound at module import time in app.api.v1.quiz.
        patch("app.api.v1.quiz.SettingsCache") as cache_cls,
    ):
        cache_cls.instance.return_value = settings_cache
        yield


async def test_admin_bypasses_without_db():
    # Admins never touch the DB lookup at all.
    await _check_subscription_or_first_unit(_learner(role="admin"), "1.5")


async def test_paid_unit_no_sub_returns_403_not_500():
    # Unit "1.5" is paid (5 > free_count 2). A learner without a subscription must
    # get a clean 403 — never MultipleResultsFound, even though the lookup would
    # match a shared unit number. We make scalar_one_or_none() blow up to prove the
    # gate doesn't rely on it.
    result_obj = MagicMock()
    result_obj.scalars.return_value.first.return_value = 2  # order_index >= free_count
    result_obj.scalar_one_or_none.side_effect = MultipleResultsFound("must not be called")
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_obj)

    async with _patched(session, sub=None):
        with pytest.raises(HTTPException) as exc:
            await _check_subscription_or_first_unit(_learner(), "1.5", uuid.uuid4())

    assert exc.value.status_code == 403
    result_obj.scalar_one_or_none.assert_not_called()


async def test_active_subscription_grants_access():
    # An active subscription short-circuits before the unit lookup.
    session = MagicMock()
    session.execute = AsyncMock()

    async with _patched(session, sub=MagicMock()):
        await _check_subscription_or_first_unit(_learner(), "1.5", uuid.uuid4())

    session.execute.assert_not_called()


async def test_free_unit_short_circuits_before_db():
    # Unit "1.2" is within the free window — granted without any subscription check.
    await _check_subscription_or_first_unit(_learner(), "1.2")


async def test_low_order_index_grants_access():
    # A unit whose number doesn't parse but resolves to an early order_index is free.
    result_obj = MagicMock()
    result_obj.scalars.return_value.first.return_value = 0  # order_index < free_count
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_obj)

    async with _patched(session, sub=None):
        await _check_subscription_or_first_unit(_learner(), "intro", uuid.uuid4())
