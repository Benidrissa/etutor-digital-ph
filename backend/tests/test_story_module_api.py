"""API tests for module story mode: GET /api/v1/story-courses/module/{module_id}.

The requests go through the real FastAPI app (httpx ASGITransport) with the
database dependency replaced by stubs, so these pin the HTTP contract (C-4):
the handler order and every status code, the access gate, the status route,
route ordering against ``/{slug}``, the slug and catalog discriminators, the
dispatch dedup (on a real Redis when one is reachable), the offline bundle,
and the unit type the module detail now reports.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.main import app

MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")
USER_ID = "22222222-2222-2222-2222-222222222222"


def _user(role: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser({"sub": USER_ID, "email": "l@example.com", "role": role})


class _Unusable:
    """A DB session stub that fails loudly if anything touches it."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was used: {name}")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# The module detail reports each unit's type
# --------------------------------------------------------------------------


class TestProgressDetail:
    """The module page classifies units (lesson, quiz, case study) from this route."""

    async def test_each_unit_carries_its_type(self, client):
        def unit(number: str, unit_type: str | None) -> dict:
            return {
                "id": str(uuid.uuid4()),
                "unit_number": number,
                "title_fr": f"Unité {number}",
                "title_en": f"Unit {number}",
                "estimated_minutes": 10,
                "order_index": int(number.split(".")[1]),
                "unit_type": unit_type,
                "status": "pending",
            }

        detail = {
            "id": str(MODULE_ID),
            "module_number": 1,
            "level": 1,
            "title_fr": "Module",
            "title_en": "Module",
            "estimated_hours": 2,
            "status": "in_progress",
            "completion_pct": 0.0,
            "units": [unit("1.1", "lesson"), unit("1.2", "quiz"), unit("1.3", None)],
        }
        service = SimpleNamespace(get_module_with_progress=AsyncMock(return_value=detail))

        async def no_db():
            yield _Unusable()

        app.dependency_overrides[get_current_user] = lambda: _user()
        app.dependency_overrides[get_db] = no_db
        with patch("app.api.v1.progress.ProgressService", return_value=service):
            resp = await client.get(f"/api/v1/progress/modules/{MODULE_ID}/detail")

        assert resp.status_code == 200
        assert [u["unit_type"] for u in resp.json()["units"]] == ["lesson", "quiz", None]


# --------------------------------------------------------------------------
# The access gate
# --------------------------------------------------------------------------


class _Rows:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)


class _RosterDb:
    """A session whose only query is the module's roster for the free-unit rule."""

    def __init__(self, units) -> None:
        self.units = [SimpleNamespace(unit_number=n, order_index=o) for n, o in units]
        self.statements: list = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Rows(self.units)


@pytest.fixture
def subscription():
    """Patch the gate's collaborators: the subscription lookup and the free count (2)."""
    service = SimpleNamespace(get_active_subscription=AsyncMock(return_value=None))
    cache = SimpleNamespace(get=lambda key, default=None: 2)
    with (
        patch("app.domain.services.subscription_service.SubscriptionService", return_value=service),
        patch("app.domain.services.platform_settings_service.SettingsCache") as cache_cls,
    ):
        cache_cls.instance.return_value = cache
        yield service


FREE_MODULE = [("1.1", 0), ("1.2", 1)]
PAID_MODULE = [("1.1", 0), ("1.2", 1), ("1.3", 2)]


class TestFreeUnitRule:
    @pytest.mark.parametrize(
        ("number", "order", "free"),
        [
            ("1.1", 0, True),
            ("1.2", 1, True),
            ("3.2", 7, True),  # the number decides first
            ("1.3", 2, False),
            ("1.3", 1, True),  # then the order index, as the lesson gate does
            ("1.10", 9, False),
            ("A-1", 0, True),  # not a canonical number: the order index decides
            ("A-1", 2, False),
            (None, None, False),
            ("1.3", None, False),
        ],
    )
    def test_the_lessons_own_rule(self, number, order, free):
        from app.api.deps_local_auth import unit_is_free

        assert unit_is_free(number, order, 2) is free


class TestModuleStoryAccess:
    async def _access(self, units, role: str = "user", user_id: str = USER_ID) -> bool:
        from app.api.deps_local_auth import module_story_access

        user = AuthenticatedUser({"sub": user_id, "role": role})
        return await module_story_access(self.db_for(units), user, MODULE_ID)

    def db_for(self, units):
        self.db = _RosterDb(units)
        return self.db

    @pytest.mark.parametrize("role", ["admin", "sub_admin"])
    async def test_staff_pass_without_any_query(self, subscription, role):
        from app.api.deps_local_auth import module_story_access

        user = AuthenticatedUser({"sub": USER_ID, "role": role})
        assert await module_story_access(_Unusable(), user, MODULE_ID) is True
        subscription.get_active_subscription.assert_not_awaited()

    async def test_a_subscriber_passes_on_a_paid_module(self, subscription):
        subscription.get_active_subscription.return_value = object()
        assert await self._access(PAID_MODULE) is True
        assert subscription.get_active_subscription.await_args.args[0] == uuid.UUID(USER_ID)
        assert self.db.statements == []  # the roster is not even read

    async def test_a_learner_passes_on_a_module_whose_units_are_all_free(self, subscription):
        assert await self._access(FREE_MODULE) is True

    async def test_one_paid_unit_closes_the_whole_module(self, subscription):
        assert await self._access(PAID_MODULE) is False

    async def test_the_roster_read_is_scoped_to_the_module(self, subscription):
        await self._access(PAID_MODULE)
        [statement] = self.db.statements
        assert "module_units.module_id = " in str(statement)

    async def test_a_user_id_that_is_not_a_uuid_still_gets_the_free_rule(self, subscription):
        assert await self._access(FREE_MODULE, user_id="not-a-uuid") is True
        assert await self._access(PAID_MODULE, user_id="not-a-uuid") is False
        subscription.get_active_subscription.assert_not_awaited()


class TestGateDependency:
    """require_subscription_or_free_module on its own (the routes use it below)."""

    @staticmethod
    def _request(module_id) -> SimpleNamespace:
        return SimpleNamespace(path_params={"module_id": str(module_id)})

    async def test_admin_passes_without_the_database(self, subscription):
        from app.api.deps_local_auth import require_subscription_or_free_module

        user = _user("admin")
        assert (
            await require_subscription_or_free_module(self._request(MODULE_ID), user, _Unusable())
            is user
        )

    async def test_a_learner_on_a_paid_module_gets_403_subscription_required(self, subscription):
        from fastapi import HTTPException

        from app.api.deps_local_auth import require_subscription_or_free_module

        with pytest.raises(HTTPException) as refused:
            await require_subscription_or_free_module(
                self._request(MODULE_ID), _user(), _RosterDb(PAID_MODULE)
            )
        assert refused.value.status_code == 403
        assert refused.value.detail["code"] == "subscription_required"
        assert refused.value.detail["message"]

    async def test_a_learner_on_a_free_module_passes(self, subscription):
        from app.api.deps_local_auth import require_subscription_or_free_module

        user = _user()
        result = await require_subscription_or_free_module(
            self._request(MODULE_ID), user, _RosterDb(FREE_MODULE)
        )
        assert result is user

    @pytest.mark.parametrize("module_id", ["M01", "not-a-uuid", "None"])
    async def test_a_module_id_that_is_not_a_uuid_is_left_to_the_route(
        self, subscription, module_id
    ):
        from app.api.deps_local_auth import require_subscription_or_free_module

        user = _user()
        result = await require_subscription_or_free_module(
            self._request(module_id), user, _Unusable()
        )
        assert result is user
