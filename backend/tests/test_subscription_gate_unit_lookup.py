"""Regression tests for the free-unit subscription gate (#2459).

`require_subscription_or_first_unit` used to run an unscoped
`select(ModuleUnit.order_index).where(unit_number == unit_id)` and call
`scalar_one_or_none()`. Because a unit number like "1.3" exists in many
modules, that matched multiple rows and raised MultipleResultsFound, which
escaped the route handler as an unhandled 500 — but only for learners (admins
bypass the gate). These tests lock in the module-scoped, crash-proof lookup.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import MultipleResultsFound

from app.api.deps_local_auth import (
    AuthenticatedUser,
    require_subscription_or_first_unit,
)


def _learner(role: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser({"sub": str(uuid.uuid4()), "email": "n@sira.app", "role": role})


def _request(unit_id: str = "1.3", module_id: str | None = None) -> MagicMock:
    req = MagicMock()
    req.path_params = {"unit_id": unit_id}
    if module_id is not None:
        req.path_params["module_id"] = module_id
    return req


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
        patch("app.domain.services.platform_settings_service.SettingsCache") as cache_cls,
    ):
        cache_cls.instance.return_value = settings_cache
        yield


async def test_admin_bypasses_without_db():
    # Admins never touch the DB lookup at all.
    user = _learner(role="admin")
    result = await require_subscription_or_first_unit(_request(), user)
    assert result is user


async def test_paid_unit_no_sub_returns_403_not_500():
    # Unit "1.3" is paid (3 > free_count 2). A learner without a subscription must
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
            await require_subscription_or_first_unit(
                _request(module_id=str(uuid.uuid4())), _learner()
            )

    assert exc.value.status_code == 403
    result_obj.scalar_one_or_none.assert_not_called()


async def test_free_unit_short_circuits_before_db():
    # Unit "1.2" is within the free window — granted without any subscription check.
    result = await require_subscription_or_first_unit(_request(unit_id="1.2"), _learner())
    assert result.role == "user"


async def test_low_order_index_grants_access():
    # A unit whose number doesn't parse but resolves to an early order_index is free.
    result_obj = MagicMock()
    result_obj.scalars.return_value.first.return_value = 0  # order_index < free_count
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_obj)

    async with _patched(session, sub=None):
        granted = await require_subscription_or_first_unit(
            _request(unit_id="intro", module_id=str(uuid.uuid4())), _learner()
        )

    assert granted.role == "user"
