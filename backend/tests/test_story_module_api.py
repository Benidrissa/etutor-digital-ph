"""API tests for module story mode: GET /api/v1/story-courses/module/{module_id}.

The requests go through the real FastAPI app (httpx ASGITransport) with the
database dependency replaced by stubs, so these pin the HTTP contract (C-4):
the handler order and every status code, the access gate, the status route,
route ordering against ``/{slug}``, the slug and catalog discriminators, the
dispatch dedup (on a real Redis when one is reachable), the offline bundle,
and the unit type the module detail now reports.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.api.deps_local_auth import (
    AuthenticatedUser,
    get_current_user,
    require_subscription_or_free_module,
)
from app.api.v1 import story_courses as api
from app.domain.services.story_module_assembly import StoryUnit
from app.main import app

MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")
USER_ID = "22222222-2222-2222-2222-222222222222"
URL = f"/api/v1/story-courses/module/{MODULE_ID}"
STATUS_URL = f"{URL}/status"
KEY = f"story_dispatch:module:{MODULE_ID}:fr"
STORY = {
    "format": "story-course/1",
    "id": f"module-{MODULE_ID.hex}-fr",
    "learner": {"first_name": "{child}"},
    "chapters": [{"id": "ch1"}, {"id": "ch2"}, {"id": "ch3"}],
    "module_story": {
        "module_id": str(MODULE_ID),
        "module_number": 1,
        "assembler": 1,
        "revision": "0123456789abcdef",
    },
}


def _story_unit(number: str, role: str, unit_type: str | None) -> StoryUnit:
    return StoryUnit(
        module_unit_id=uuid.uuid5(MODULE_ID, number),
        unit_number=number,
        unit_type=unit_type,
        order_index=int(number.split(".")[1]) - 1,
        role=role,
        title={"en": f"Unit {number}", "fr": f"Unité {number}"},
    )


UNITS = [
    _story_unit("1.1", "lesson", "lesson"),
    _story_unit("1.2", "quiz_checkpoint", "quiz"),
    _story_unit("1.3", "case_checkpoint", "case-study"),
]
NO_LESSON = UNITS[1:]


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


# --------------------------------------------------------------------------
# GET /story-courses/module/{module_id}
# --------------------------------------------------------------------------


class _ModuleDb:
    """A session that answers the module lookup and the free-unit roster, nothing else."""

    def __init__(self, exists: bool = True, roster=FREE_MODULE) -> None:
        self.exists = exists
        self.roster = [SimpleNamespace(unit_number=n, order_index=o) for n, o in roster]
        self.statements: list[str] = []

    async def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "FROM module_units" in sql:
            return _Rows(self.roster)
        assert "FROM modules" in sql, f"unexpected query: {sql}"
        row = (MODULE_ID,) if self.exists else None
        return SimpleNamespace(first=lambda: row)


def _install(role: str = "user", db=None, *, gate: bool = False) -> None:
    """Authenticate as ``role``; replace the gate unless ``gate``; use ``db`` as the session."""
    session = _ModuleDb() if db is None else db

    async def get_session():
        yield session

    app.dependency_overrides[get_current_user] = lambda: _user(role)
    if not gate:
        app.dependency_overrides[require_subscription_or_free_module] = lambda: _user(role)
    app.dependency_overrides[get_db] = get_session


def _record(is_valid: bool = True, status: str = "published", content=None):
    return SimpleNamespace(
        is_valid=is_valid, status=status, content=dict(content or STORY), module_id=MODULE_ID
    )


@pytest.fixture
def mocks():
    """Patch the handlers' collaborators; each test sets the return values."""
    with (
        patch.object(api, "story_mode_enabled", return_value=True) as enabled,
        patch.object(api, "load_story_units", AsyncMock(return_value=list(UNITS))) as units,
        patch.object(api, "find_module_story", AsyncMock(return_value=None)) as find,
        patch.object(api, "module_story_is_fresh", AsyncMock(return_value=True)) as fresh,
        patch.object(
            api, "dispatch_module_story_generation", AsyncMock(return_value="task-123")
        ) as dispatch,
        patch.object(api, "module_story_access", AsyncMock(return_value=True)) as access,
        patch.object(api, "_in_flight_story_task", AsyncMock(return_value=None)) as in_flight,
        patch.object(api.generate_module_story_task, "apply_async") as apply_async,
    ):
        yield SimpleNamespace(
            enabled=enabled,
            units=units,
            find=find,
            fresh=fresh,
            dispatch=dispatch,
            access=access,
            in_flight=in_flight,
            apply_async=apply_async,
        )


class TestModuleStory:
    async def test_cached_valid_story_is_200(self, client, mocks):
        _install()
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"language": "fr"})
        assert resp.status_code == 200
        assert resp.json() == STORY
        assert resp.headers["cache-control"] == "private, no-cache"
        mocks.dispatch.assert_not_awaited()
        assert mocks.find.await_args.args[1:] == (MODULE_ID, "fr")
        assert mocks.units.await_args.args[1] == MODULE_ID
        # The roster just read is reused by the freshness check.
        assert mocks.fresh.await_args.kwargs == {"units": UNITS}

    async def test_missing_story_dispatches_and_is_202(self, client, mocks):
        _install()
        resp = await client.get(URL, params={"language": "en", "level": 2, "country": "sn"})
        assert resp.status_code == 202
        assert resp.json() == {
            "status": "generating",
            "task_id": "task-123",
            "message": "Story is being generated",
        }
        assert mocks.dispatch.await_args.kwargs == {
            "module_id": MODULE_ID,
            "language": "en",
            "country": "SN",
            "level": 2,
            "force_regenerate": False,
        }

    async def test_stale_story_is_regenerated(self, client, mocks):
        _install()
        mocks.find.return_value = _record()
        mocks.fresh.return_value = False
        assert (await client.get(URL)).status_code == 202
        mocks.dispatch.assert_awaited_once()

    async def test_fresh_story_that_is_not_publishable_is_409(self, client, mocks):
        _install()
        mocks.find.return_value = _record(is_valid=False, status="draft")
        resp = await client.get(URL)
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["error"] == "story_unavailable" and detail["message"]
        mocks.dispatch.assert_not_awaited()

    async def test_valid_draft_is_not_served(self, client, mocks):
        _install()
        mocks.find.return_value = _record(is_valid=True, status="draft")
        assert (await client.get(URL)).status_code == 409

    async def test_unavailable_story_whose_sources_changed_is_retried(self, client, mocks):
        _install()
        mocks.find.return_value = _record(is_valid=False, status="draft")
        mocks.fresh.return_value = False
        assert (await client.get(URL)).status_code == 202

    async def test_story_mode_off_is_404_before_any_query(self, client, mocks):
        _install(db=_Unusable())
        mocks.enabled.return_value = False
        resp = await client.get(URL)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_mode_disabled"
        mocks.units.assert_not_awaited()
        mocks.find.assert_not_awaited()
        mocks.dispatch.assert_not_awaited()

    async def test_unknown_module_is_404(self, client, mocks):
        _install(db=_ModuleDb(exists=False))
        resp = await client.get(URL)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "module_not_found"
        mocks.units.assert_not_awaited()
        mocks.dispatch.assert_not_awaited()

    @pytest.mark.parametrize("module_id", ["M01", "abc", "1.2"])
    async def test_a_module_id_that_is_not_a_uuid_is_404_without_a_query(
        self, client, mocks, module_id
    ):
        """A module code is shared by every course: it never names one module here."""
        _install(db=_Unusable())
        resp = await client.get(f"/api/v1/story-courses/module/{module_id}")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "module_not_found"
        mocks.units.assert_not_awaited()

    async def test_a_module_without_a_lesson_has_no_story(self, client, mocks):
        _install()
        mocks.units.return_value = list(NO_LESSON)
        resp = await client.get(URL)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "no_story_content"
        mocks.find.assert_not_awaited()
        mocks.dispatch.assert_not_awaited()

    async def test_cached_only_with_nothing_cached_is_404_and_dispatches_nothing(
        self, client, mocks
    ):
        _install()
        resp = await client.get(URL, params={"generate": "false"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_not_cached"
        mocks.dispatch.assert_not_awaited()
        mocks.apply_async.assert_not_called()

    async def test_cached_only_with_a_stale_story_is_404_even_when_forced(self, client, mocks):
        _install("admin")
        mocks.find.return_value = _record()
        mocks.fresh.return_value = False
        resp = await client.get(URL, params={"generate": "false", "force_regenerate": "true"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_not_cached"
        mocks.dispatch.assert_not_awaited()
        mocks.apply_async.assert_not_called()

    async def test_cached_only_still_serves_a_fresh_story(self, client, mocks):
        _install()
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"generate": "false"})
        assert resp.status_code == 200 and resp.json() == STORY
        mocks.dispatch.assert_not_awaited()

    async def test_cached_only_reports_an_unavailable_story_as_409(self, client, mocks):
        _install()
        mocks.find.return_value = _record(is_valid=False, status="draft")
        resp = await client.get(URL, params={"generate": "false"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "story_unavailable"
        mocks.dispatch.assert_not_awaited()

    async def test_learners_cannot_force_a_regeneration(self, client, mocks):
        _install("user")
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"force_regenerate": "true"})
        assert resp.status_code == 200
        mocks.dispatch.assert_not_awaited()

    async def test_a_learners_force_is_dropped_from_a_dispatch(self, client, mocks):
        _install("user")
        resp = await client.get(URL, params={"force_regenerate": "true"})
        assert resp.status_code == 202
        assert mocks.dispatch.await_args.kwargs["force_regenerate"] is False

    @pytest.mark.parametrize("role", ["admin", "sub_admin"])
    async def test_admins_can_force_a_regeneration(self, client, mocks, role):
        _install(role)
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"force_regenerate": "true"})
        assert resp.status_code == 202
        assert mocks.dispatch.await_args.kwargs["force_regenerate"] is True
        mocks.fresh.assert_not_awaited()

    async def test_unsupported_language_is_422(self, client, mocks):
        _install()
        assert (await client.get(URL, params={"language": "de"})).status_code == 422

    @pytest.mark.parametrize("level", [0, 5])
    async def test_level_out_of_range_is_422(self, client, mocks, level):
        _install()
        assert (await client.get(URL, params={"level": level})).status_code == 422

    async def test_module_paths_are_not_swallowed_by_the_slug_route(self, client, mocks):
        """``/{slug}`` would query story_courses, which this session refuses."""
        _install()
        mocks.find.return_value = _record()
        assert (await client.get(URL)).status_code == 200
        assert (await client.get(STATUS_URL)).status_code == 200

    def test_routes_are_declared_before_the_slug_route(self):
        paths = [route.path for route in api.router.routes if "GET" in route.methods]
        slug = paths.index("/story-courses/{slug}")
        assert paths.index("/story-courses/module/{module_id}") < slug
        assert paths.index("/story-courses/module/{module_id}/status") < slug

    def test_the_route_is_gated(self):
        route = next(r for r in api.router.routes if r.path == "/story-courses/module/{module_id}")
        assert require_subscription_or_free_module in [d.call for d in route.dependant.dependencies]

    async def test_no_token_is_refused(self, client):
        app.dependency_overrides.clear()
        assert (await client.get(URL)).status_code in (401, 403)
        assert (await client.get(STATUS_URL)).status_code in (401, 403)


class TestGateOnTheRoute:
    """The real gate in front of the real handler."""

    @pytest.fixture(autouse=True)
    def _handler(self, mocks):
        mocks.find.return_value = _record()
        self.mocks = mocks

    async def test_a_learner_without_a_subscription_is_refused_a_paid_module(
        self, client, subscription
    ):
        db = _ModuleDb(roster=PAID_MODULE)
        _install("user", db, gate=True)
        resp = await client.get(URL)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "subscription_required"
        assert resp.json()["detail"]["message"]
        self.mocks.units.assert_not_awaited()
        self.mocks.find.assert_not_awaited()
        self.mocks.dispatch.assert_not_awaited()

    async def test_a_learner_without_a_subscription_reads_an_all_free_module(
        self, client, subscription
    ):
        db = _ModuleDb(roster=FREE_MODULE)
        _install("user", db, gate=True)
        resp = await client.get(URL)
        assert resp.status_code == 200 and resp.json() == STORY
        assert any("FROM module_units" in sql for sql in db.statements)

    async def test_a_subscriber_reads_a_paid_module(self, client, subscription):
        subscription.get_active_subscription.return_value = object()
        _install("user", _ModuleDb(roster=PAID_MODULE), gate=True)
        assert (await client.get(URL)).status_code == 200

    @pytest.mark.parametrize("role", ["admin", "sub_admin"])
    async def test_staff_pass_without_the_roster(self, client, subscription, role):
        db = _ModuleDb(roster=PAID_MODULE)
        _install(role, db, gate=True)
        assert (await client.get(URL)).status_code == 200
        subscription.get_active_subscription.assert_not_awaited()
        assert not any("FROM module_units" in sql for sql in db.statements)

    async def test_a_module_id_that_is_not_a_uuid_passes_the_gate_and_is_404(
        self, client, subscription
    ):
        _install("user", _Unusable(), gate=True)
        resp = await client.get("/api/v1/story-courses/module/M01")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "module_not_found"


# --------------------------------------------------------------------------
# GET /story-courses/module/{module_id}/status
# --------------------------------------------------------------------------


class TestStatus:
    async def _status(self, client, **params) -> dict:
        resp = await client.get(STATUS_URL, params=params)
        assert resp.status_code == 200, resp.text
        assert resp.headers["cache-control"] == "private, no-store"
        return resp.json()

    async def test_ready(self, client, mocks):
        _install()
        mocks.find.return_value = _record()
        assert await self._status(client) == {
            "state": "ready",
            "task_id": None,
            "chapters": 3,
            "revision": "0123456789abcdef",
            "access": "ok",
        }
        assert mocks.find.await_args.args[1:] == (MODULE_ID, "fr")
        assert mocks.fresh.await_args.kwargs == {"units": UNITS}

    async def test_the_language_is_honoured(self, client, mocks):
        _install()
        await self._status(client, language="en")
        assert mocks.find.await_args.args[1:] == (MODULE_ID, "en")
        assert mocks.in_flight.await_args.args[0] == f"story_dispatch:module:{MODULE_ID}:en"

    async def test_unpublishable(self, client, mocks):
        _install()
        mocks.find.return_value = _record(is_valid=False, status="draft")
        body = await self._status(client)
        assert body["state"] == "unavailable" and body["chapters"] is None

    async def test_a_module_without_a_lesson_is_unavailable(self, client, mocks):
        _install()
        mocks.units.return_value = list(NO_LESSON)
        assert (await self._status(client))["state"] == "unavailable"
        mocks.find.assert_not_awaited()

    async def test_generating(self, client, mocks):
        _install()
        mocks.find.return_value = _record()
        mocks.fresh.return_value = False
        mocks.in_flight.return_value = "task-9"
        body = await self._status(client)
        assert body["state"] == "generating" and body["task_id"] == "task-9"
        assert body["chapters"] is None and body["revision"] is None
        # A report only: a finished task's key is left to the next dispatch.
        assert mocks.in_flight.await_args.args == (KEY,)
        assert mocks.in_flight.await_args.kwargs == {"release_finished": False}

    async def test_not_ready(self, client, mocks):
        _install()
        body = await self._status(client)
        assert body == {
            "state": "not_ready",
            "task_id": None,
            "chapters": None,
            "revision": None,
            "access": "ok",
        }

    async def test_without_redis_it_reads_not_ready(self, client, mocks):
        _install()
        mocks.in_flight.side_effect = ConnectionError("redis down")
        assert (await self._status(client))["state"] == "not_ready"

    async def test_disabled(self, client, mocks):
        _install()
        mocks.enabled.return_value = False
        body = await self._status(client)
        assert body["state"] == "disabled" and body["access"] == "ok"
        mocks.units.assert_not_awaited()
        mocks.find.assert_not_awaited()

    async def test_access_is_reported_whatever_the_state(self, client, mocks):
        _install()
        mocks.access.return_value = False
        mocks.find.return_value = _record()
        body = await self._status(client)
        assert body["access"] == "subscription_required" and body["state"] == "ready"
        user = mocks.access.await_args.args[1]
        assert mocks.access.await_args.args[2] == MODULE_ID and user.id == USER_ID

    @pytest.mark.parametrize("found", [None, "stale", "fresh"])
    async def test_it_never_dispatches(self, client, mocks, found):
        _install()
        if found:
            mocks.find.return_value = _record()
            mocks.fresh.return_value = found == "fresh"
        await self._status(client)
        mocks.dispatch.assert_not_awaited()
        mocks.apply_async.assert_not_called()

    async def test_unknown_module_is_404(self, client, mocks):
        _install(db=_ModuleDb(exists=False))
        resp = await client.get(STATUS_URL)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "module_not_found"

    async def test_a_module_id_that_is_not_a_uuid_is_404(self, client, mocks):
        _install(db=_Unusable())
        resp = await client.get("/api/v1/story-courses/module/M01/status")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "module_not_found"

    async def test_a_non_subscriber_is_not_refused(self, client, mocks):
        """The card needs the state to say "for subscribers": the status route is ungated."""
        _install("user", gate=True)
        mocks.access.return_value = False
        assert (await self._status(client))["access"] == "subscription_required"
        route = next(r for r in api.router.routes if r.path.endswith("/status"))
        calls = [d.call for d in route.dependant.dependencies]
        assert get_current_user in calls
        assert require_subscription_or_free_module not in calls


# --------------------------------------------------------------------------
# Dispatch dedup
# --------------------------------------------------------------------------


@pytest.fixture
def redis():
    client = MagicMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    client.eval = AsyncMock(return_value=1)
    with patch("app.infrastructure.cache.redis.redis_client", client):
        yield client


@pytest.fixture
def celery():
    task = MagicMock()
    with (
        patch.object(api, "generate_module_story_task", task),
        patch.object(api, "mark_task_dispatched", AsyncMock()) as marked,
        patch.object(api, "vouch_while_owned", AsyncMock()) as vouched,
    ):
        yield SimpleNamespace(task=task, marked=marked, vouched=vouched)


def _dispatch(**overrides):
    kwargs = {
        "module_id": MODULE_ID,
        "language": "fr",
        "country": "CI",
        "level": 1,
        "force_regenerate": False,
        **overrides,
    }
    return api.dispatch_module_story_generation(**kwargs)


def _state(state: str):
    return patch.object(api, "AsyncResult", return_value=SimpleNamespace(state=state))


class TestDispatch:
    async def test_first_view_claims_the_module_key_and_dispatches(self, redis, celery):
        task_id = await _dispatch()
        key, value = redis.set.await_args.args
        assert key == KEY and value == task_id
        assert redis.set.await_args.kwargs == {"nx": True, "ex": api._MODULE_STORY_DISPATCH_TTL_S}
        celery.task.apply_async.assert_called_once_with(
            args=[str(MODULE_ID), "fr", "CI", 1, False],
            kwargs={"dedup_key": KEY},
            task_id=task_id,
        )
        celery.marked.assert_awaited_once_with(task_id)

    async def test_force_and_the_preferred_sources_reach_the_task(self, redis, celery):
        await _dispatch(language="en", country="SN", level=3, force_regenerate=True)
        call = celery.task.apply_async.call_args
        assert call.kwargs["args"] == [str(MODULE_ID), "en", "SN", 3, True]
        assert call.kwargs["kwargs"] == {"dedup_key": f"story_dispatch:module:{MODULE_ID}:en"}

    async def test_concurrent_view_joins_the_running_task(self, redis, celery):
        redis.get.return_value = "running-task"
        with _state("STARTED"):
            assert await _dispatch() == "running-task"
        celery.task.apply_async.assert_not_called()

    async def test_view_that_loses_the_race_joins_the_winner(self, redis, celery):
        redis.get.side_effect = [None, "winner-task"]
        redis.set.return_value = False
        assert await _dispatch() == "winner-task"
        celery.task.apply_async.assert_not_called()

    @pytest.mark.parametrize("state", ["SUCCESS", "FAILURE", "REVOKED"])
    async def test_finished_task_is_replaced_with_a_compare_and_delete(self, redis, celery, state):
        redis.get.return_value = "old-task"
        with _state(state):
            task_id = await _dispatch()
        assert task_id != "old-task"
        # Only the key still holding "old-task" may go: never a plain DELETE.
        redis.delete.assert_not_awaited()
        script, numkeys, key, value = redis.eval.await_args.args
        assert 'redis.call("get", KEYS[1]) == ARGV[1]' in script
        assert (numkeys, key, value) == (1, KEY, "old-task")
        celery.task.apply_async.assert_called_once()

    async def test_queued_task_past_the_stall_threshold_is_still_joined(self, redis, celery):
        """A long queue is not a dead task while its key lives."""
        redis.get.return_value = "queued-task"
        marker = AsyncMock()
        with _state("PENDING"), patch("app.api.v1._task_status.dispatched_at", marker):
            assert await _dispatch() == "queued-task"
        celery.task.apply_async.assert_not_called()
        marker.assert_not_awaited()
        redis.delete.assert_not_awaited()
        redis.eval.assert_not_awaited()

    async def test_just_claimed_task_without_a_dispatch_marker_is_joined(self, redis, celery):
        """Between SET NX and the dispatch marker the key is PENDING, unmarked."""
        redis.get.return_value = "just-claimed"
        with _state("PENDING"):
            assert await _dispatch() == "just-claimed"
        celery.task.apply_async.assert_not_called()
        redis.eval.assert_not_awaited()

    async def test_key_released_between_set_and_get_is_claimed_again(self, redis, celery):
        redis.get.return_value = None
        redis.set.side_effect = [False, True]
        task_id = await _dispatch()
        assert redis.set.await_count == 2
        celery.task.apply_async.assert_called_once()
        assert celery.task.apply_async.call_args.kwargs["task_id"] == task_id

    async def test_failed_dispatch_releases_only_its_own_key(self, redis, celery):
        celery.task.apply_async.side_effect = ConnectionError("broker down")
        with pytest.raises(ConnectionError):
            await _dispatch()
        task_id = redis.set.await_args.args[1]
        assert redis.eval.await_args.args[1:] == (1, KEY, task_id)
        redis.delete.assert_not_awaited()
        celery.marked.assert_not_awaited()

    async def test_without_redis_it_fails_open(self, redis, celery):
        redis.get.side_effect = ConnectionError("redis down")
        task_id = await _dispatch()
        celery.task.apply_async.assert_called_once()
        assert celery.task.apply_async.call_args.kwargs["task_id"] == task_id

    async def test_the_task_is_vouched_for_before_its_key_is_claimed(self, redis, celery):
        """A joined task stays "pending" on /content/status while its key names it."""
        order: list[str] = []
        celery.vouched.side_effect = lambda *a: order.append("vouch")
        redis.set.side_effect = lambda *a, **k: order.append("claim") or True
        task_id = await _dispatch()
        celery.vouched.assert_awaited_once_with(task_id, KEY, api._MODULE_STORY_DISPATCH_TTL_S)
        assert order == ["vouch", "claim"]

    async def test_joining_a_running_task_vouches_for_nothing_new(self, redis, celery):
        redis.get.return_value = "running-task"
        with _state("PENDING"):
            assert await _dispatch() == "running-task"
        celery.vouched.assert_not_awaited()

    async def test_a_status_read_never_releases_a_finished_tasks_key(self, redis):
        redis.get.return_value = "old-task"
        with _state("SUCCESS"):
            assert await api._in_flight_story_task(KEY, release_finished=False) is None
        redis.eval.assert_not_awaited()
        redis.delete.assert_not_awaited()


def test_the_dedup_key_outlives_the_task_and_nothing_else():
    """HARD + 60: past the task's hard limit, short of a redelivery or a lost result."""
    from app.api.v1 import _task_status
    from app.tasks.celery_app import celery_app
    from app.tasks.content_generation import MODULE_STORY_HARD_LIMIT

    ttl = api._MODULE_STORY_DISPATCH_TTL_S
    assert ttl == MODULE_STORY_HARD_LIMIT + 60 == 1320
    assert ttl < 3600
    assert ttl <= celery_app.conf.result_expires
    visibility = (celery_app.conf.broker_transport_options or {}).get("visibility_timeout", 3600)
    assert ttl < visibility
    # The dispatch marker the status endpoint reads outlives the key too.
    assert ttl < _task_status._TTL_SECONDS


def test_the_task_releases_its_key_with_a_compare_and_delete_on_its_own_id():
    from app.tasks import content_generation

    client = MagicMock()
    with patch("redis.Redis.from_url", return_value=client):
        content_generation._release_story_dispatch(KEY, "task-42")
    script, numkeys, key, value = client.eval.call_args.args
    assert "ARGV[1]" in script and (numkeys, key, value) == (1, KEY, "task-42")
    client.delete.assert_not_called()
    client.close.assert_called_once()


def test_the_task_key_release_never_raises():
    from app.tasks import content_generation

    with patch("redis.Redis.from_url", side_effect=ConnectionError("redis down")):
        content_generation._release_story_dispatch(KEY, "task-42")
    content_generation._release_story_dispatch(None, "task-42")  # nothing claimed


class _FakeRedis:
    """Just enough of redis.asyncio for the task-status helpers."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value

    async def get(self, key: str) -> str | None:
        return self.data.get(key)


class TestStatusOfAQueuedStory:
    """Joined clients poll /content/status: it must agree with the dedup."""

    @pytest.fixture
    def store(self):
        from app.api.v1 import _task_status

        fake = _FakeRedis()
        with patch.object(_task_status, "redis_client", fake):
            yield fake

    @staticmethod
    async def _status(task_id: str, *, marker_age_s: float | None) -> dict:
        import json
        from datetime import UTC, datetime, timedelta

        from app.api.v1 import content as content_module

        marker = (
            None if marker_age_s is None else datetime.now(tz=UTC) - timedelta(seconds=marker_age_s)
        )
        with (
            patch.object(
                content_module, "AsyncResult", return_value=SimpleNamespace(state="PENDING")
            ),
            patch.object(content_module, "task_dispatched_at", AsyncMock(return_value=marker)),
        ):
            response = await content_module.get_generation_status(task_id)
        return json.loads(response.body)

    async def test_a_story_queued_past_the_stall_threshold_is_pending(self, store):
        from app.api.v1._task_status import TASK_STALL_THRESHOLD_S, vouch_while_owned

        await vouch_while_owned("task-1", KEY, api._MODULE_STORY_DISPATCH_TTL_S)
        store.data[KEY] = "task-1"
        body = await self._status("task-1", marker_age_s=TASK_STALL_THRESHOLD_S + 60)
        assert body == {"status": "pending"}

    async def test_a_just_claimed_story_without_a_marker_is_pending(self, store):
        from app.api.v1._task_status import vouch_while_owned

        await vouch_while_owned("task-1", KEY, api._MODULE_STORY_DISPATCH_TTL_S)
        store.data[KEY] = "task-1"
        assert await self._status("task-1", marker_age_s=None) == {"status": "pending"}

    async def test_once_the_key_names_another_task_the_stall_rule_applies(self, store):
        from app.api.v1._task_status import TASK_STALL_THRESHOLD_S, vouch_while_owned

        await vouch_while_owned("task-1", KEY, api._MODULE_STORY_DISPATCH_TTL_S)
        store.data[KEY] = "task-2"  # released and claimed again
        body = await self._status("task-1", marker_age_s=TASK_STALL_THRESHOLD_S + 60)
        assert body == {"status": "failed", "error": "task_stalled"}
        del store.data[KEY]  # released, nobody claimed it
        assert await self._status("task-1", marker_age_s=None) == {
            "status": "failed",
            "error": "task_lost",
        }

    async def test_vouching_never_raises_without_redis(self):
        from app.api.v1 import _task_status

        broken = MagicMock()
        broken.setex = AsyncMock(side_effect=ConnectionError("redis down"))
        broken.get = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch.object(_task_status, "redis_client", broken):
            await _task_status.vouch_while_owned("task-1", KEY, 60)
            assert await _task_status.is_vouched("task-1") is False


# --------------------------------------------------------------------------
# The dedup on a real Redis
# --------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def real_redis():
    """A Redis client on this test's own loop (settings.redis_url); skip without a server."""
    from redis.asyncio import Redis

    from app.infrastructure.config.settings import settings

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"no Redis server: {exc}"[:200])
    await client.delete(KEY)
    with (
        patch("app.infrastructure.cache.redis.redis_client", client),
        patch("app.api.v1._task_status.redis_client", client),
    ):
        yield client
    await client.delete(KEY)
    await client.aclose()


class TestRealRedisDedup:
    async def test_twenty_concurrent_first_views_dispatch_once(self, client, mocks, real_redis):
        from app.api.v1._task_status import _KEY_PREFIX, _OWNER_PREFIX
        from app.tasks import content_generation

        _install()

        # Let the requests interleave around every await, as they would in production.
        async def units(*_args, **_kwargs):
            await asyncio.sleep(0)
            return list(UNITS)

        mocks.units.side_effect = units
        apply_async = MagicMock()
        with (
            patch.object(api, "dispatch_module_story_generation", _real_dispatch),
            patch.object(api.generate_module_story_task, "apply_async", apply_async),
            _state("PENDING"),
        ):
            responses = await asyncio.gather(*(client.get(URL) for _ in range(20)))

        assert [r.status_code for r in responses] == [202] * 20
        task_ids = {r.json()["task_id"] for r in responses}
        assert len(task_ids) == 1
        [task_id] = task_ids
        apply_async.assert_called_once_with(
            args=[str(MODULE_ID), "fr", "CI", 1, False],
            kwargs={"dedup_key": KEY},
            task_id=task_id,
        )
        assert await real_redis.get(KEY) == task_id
        assert 0 < await real_redis.ttl(KEY) <= api._MODULE_STORY_DISPATCH_TTL_S
        assert await real_redis.get(f"{_OWNER_PREFIX}{task_id}") == KEY
        assert await real_redis.exists(f"{_KEY_PREFIX}{task_id}")

        # The card's status names the very task the GETs joined...
        with patch.object(api, "_in_flight_story_task", _real_in_flight), _state("PENDING"):
            body = (await client.get(STATUS_URL)).json()
        assert (body["state"], body["task_id"]) == ("generating", task_id)

        # ...a release by another task id leaves the key alone...
        content_generation._release_story_dispatch(KEY, "someone-else")
        assert await real_redis.get(KEY) == task_id

        # ...and once the task releases its key, nothing is generating.
        content_generation._release_story_dispatch(KEY, task_id)
        assert await real_redis.get(KEY) is None
        with patch.object(api, "_in_flight_story_task", _real_in_flight):
            body = (await client.get(STATUS_URL)).json()
        assert body["state"] == "not_ready" and body["task_id"] is None
        await real_redis.delete(f"{_OWNER_PREFIX}{task_id}", f"{_KEY_PREFIX}{task_id}")


#: The real helpers, taken before any fixture replaces them on ``api``.
_real_dispatch = api.dispatch_module_story_generation
_real_in_flight = api._in_flight_story_task


# --------------------------------------------------------------------------
# The per-unit story is gone
# --------------------------------------------------------------------------


class TestPerUnitStoryRemoved:
    """One story per module replaces one per lesson: no route, task or key is left."""

    async def test_the_unit_route_is_404(self, client):
        _install("admin", _Unusable())
        for path in (
            f"/api/v1/story-courses/unit/{MODULE_ID}/1.2",
            "/api/v1/story-courses/unit/M03/1.2",
        ):
            assert (await client.get(path)).status_code == 404

    def test_no_route_serves_a_unit_story(self):
        paths = [getattr(route, "path", "") for route in app.routes]
        assert not [p for p in paths if p.startswith("/api/v1/story-courses/unit")]

    def test_the_per_unit_task_and_key_are_gone(self):
        from app.domain.services import story_from_lesson_service
        from app.tasks import content_generation
        from app.tasks.celery_app import celery_app

        for name in ("generate_story_task", "STORY_SOFT_LIMIT", "STORY_HARD_LIMIT"):
            assert not hasattr(content_generation, name), name
        assert "app.tasks.content_generation.generate_story_task" not in celery_app.tasks
        assert "app.tasks.content_generation.generate_module_story_task" in celery_app.tasks
        assert not hasattr(story_from_lesson_service, "story_dispatch_key")
        for name in ("get_unit_story", "_dispatch_story_generation", "_STORY_DISPATCH_TTL_S"):
            assert not hasattr(api, name), name


# --------------------------------------------------------------------------
# The slug route, the catalog and the authoring routes
# --------------------------------------------------------------------------


class _OneRow:
    """A DB session stub whose one query returns ``record``."""

    def __init__(self, record) -> None:
        self.record = record

    async def execute(self, statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.record)


CHAPTER_ID = uuid.uuid5(MODULE_ID, "1.1")


def _stored(kind: str, status: str = "published"):
    module_id, unit_id, slug = {
        "authored": (None, None, "igcse-maths-u1-w04"),
        "chapter": (MODULE_ID, CHAPTER_ID, f"lesson-{CHAPTER_ID.hex}-fr"),
        "module": (MODULE_ID, None, f"module-{MODULE_ID.hex}-fr"),
    }[kind]
    return SimpleNamespace(
        slug=slug, status=status, module_id=module_id, module_unit_id=unit_id, content=dict(STORY)
    )


class TestSlugRoute:
    """``GET /story-courses/{slug}`` never hands a learner a generated story."""

    async def _get(self, client, record, role: str):
        _install(role, _OneRow(record))
        return await client.get(f"/api/v1/story-courses/{record.slug}")

    @pytest.mark.parametrize("kind", ["chapter", "module"])
    async def test_learner_cannot_read_a_published_generated_story_by_slug(self, client, kind):
        resp = await self._get(client, _stored(kind), "user")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_course_not_found"

    @pytest.mark.parametrize("kind", ["chapter", "module"])
    @pytest.mark.parametrize("role", ["admin", "sub_admin"])
    async def test_admin_reads_one_but_never_from_a_shared_cache(self, client, kind, role):
        resp = await self._get(client, _stored(kind), role)
        assert resp.status_code == 200 and resp.json() == STORY
        assert resp.headers["cache-control"] == "private, no-store"

    async def test_learner_still_reads_a_published_authored_week(self, client):
        resp = await self._get(client, _stored("authored"), "user")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "public, max-age=3600"

    async def test_learner_cannot_read_an_authored_draft(self, client):
        resp = await self._get(client, _stored("authored", status="draft"), "user")
        assert resp.status_code == 404


class TestCatalog:
    async def test_generated_stories_are_not_listed(self, client):
        captured = []

        class Db:
            async def execute(self, statement):
                captured.append(str(statement))
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        _install("user", Db())
        resp = await client.get("/api/v1/story-courses")
        assert resp.status_code == 200
        assert "story_courses.module_id IS NULL" in captured[0]
        assert "story_courses.module_unit_id IS NULL" in captured[0]


class TestReservedSlugs:
    @pytest.fixture
    def course(self) -> dict:
        import json
        from pathlib import Path

        path = Path(__file__).parent / "fixtures" / "story_course_w04.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @pytest.mark.parametrize(
        "slug", [f"lesson-{CHAPTER_ID.hex}-fr", f"module-{MODULE_ID.hex}-en", "module-x"]
    )
    async def test_a_generated_storys_id_cannot_be_saved(self, client, course, slug):
        _install("admin", _Unusable())
        course["id"] = slug
        resp = await client.post("/api/v1/story-courses", json={"content": course})
        assert resp.status_code == 422
        assert resp.json()["detail"]["error"] == "reserved_slug"

    async def test_an_ordinary_id_is_still_saved(self, client, course):
        stored = SimpleNamespace(
            id=uuid.uuid4(), slug=course["id"], status="draft", is_valid=True, week=course["week"]
        )

        class Db:
            async def commit(self):
                pass

            async def refresh(self, _record):
                pass

        _install("admin", Db())
        with patch.object(api, "upsert_story_course", AsyncMock(return_value=stored)) as upsert:
            resp = await client.post("/api/v1/story-courses", json={"content": course})
        assert resp.status_code == 200
        assert upsert.await_args.kwargs["course"].id == course["id"]

    @pytest.mark.parametrize("kind", ["chapter", "module"])
    async def test_a_generated_story_cannot_be_published_by_hand(self, client, kind):
        record = _stored(kind, status="draft")
        _install("admin", _OneRow(record))
        resp = await client.post(f"/api/v1/story-courses/{record.slug}/publish")
        assert resp.status_code == 422
        assert resp.json()["detail"]["error"] == "reserved_slug"
        assert record.status == "draft"


# --------------------------------------------------------------------------
# The offline bundle
# --------------------------------------------------------------------------


class TestCachedModuleStory:
    """The bundle carries a module's story only when one is ready, from the cache."""

    @pytest.fixture
    def svc(self):
        service = "app.domain.services.story_module_service"
        with (
            patch(f"{service}.find_module_story", AsyncMock()) as find,
            patch(f"{service}.module_story_is_fresh", AsyncMock(return_value=True)) as fresh,
        ):
            yield SimpleNamespace(find=find, fresh=fresh)

    async def test_a_ready_story_is_bundled(self, svc):
        from app.tasks.course_bundle import _cached_module_story

        svc.find.return_value = _record()
        assert await _cached_module_story(object(), MODULE_ID, "fr") == STORY
        assert svc.find.await_args.args[1:] == (MODULE_ID, "fr")

    @pytest.mark.parametrize(
        ("record", "fresh"),
        [
            (None, True),
            (_record(is_valid=False, status="draft"), True),
            (_record(is_valid=True, status="draft"), True),
            (_record(), False),
        ],
        ids=["missing", "invalid", "draft", "stale"],
    )
    async def test_a_story_that_is_not_ready_is_not_bundled(self, svc, record, fresh):
        from app.tasks.course_bundle import _cached_module_story

        svc.find.return_value = record
        svc.fresh.return_value = fresh
        assert await _cached_module_story(object(), MODULE_ID, "fr") is None


class _BundleSession:
    """The bundle task's session: the bundle row, then the course with its modules."""

    def __init__(self, bundle, course) -> None:
        self.bundle, self.course = bundle, course

    async def get(self, _model, _key):
        return self.bundle

    async def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.course)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _bundle_course():
    def unit(module_number: int, minor: int, unit_type: str | None):
        return SimpleNamespace(
            id=uuid.uuid4(),
            unit_number=f"{module_number}.{minor}",
            unit_type=unit_type,
            order_index=minor - 1,
            title_fr=f"Unité {module_number}.{minor}",
            title_en=f"Unit {module_number}.{minor}",
        )

    def module(number: int):
        return SimpleNamespace(
            id=uuid.uuid5(MODULE_ID, str(number)),
            module_number=number,
            title_fr=f"Module {number}",
            title_en=f"Module {number}",
            units=[unit(number, 1, "lesson"), unit(number, 2, None), unit(number, 3, "quiz")],
        )

    return SimpleNamespace(title_fr="Cours", title_en="Course", modules=[module(2), module(1)])


class TestBundleTask:
    def test_one_story_file_per_module_and_only_when_ready(self):
        from app.tasks import course_bundle

        course = _bundle_course()
        ready_module = next(m for m in course.modules if m.module_number == 1)
        bundle = SimpleNamespace(
            status="pending", course_id=uuid.uuid4(), language="fr", level=1, country="CI"
        )
        engine = SimpleNamespace(dispose=AsyncMock())
        session = _BundleSession(bundle, course)
        zipped: list[list[str]] = []

        def build_zip(files):
            zipped.append([name for name, _ in files])
            return b"zip"

        render = AsyncMock(return_value="<html></html>")
        bundle_service = SimpleNamespace(
            render_flashcards=render,
            render_lesson=render,
            render_quiz=render,
            render_case_study=render,
            build_zip=build_zip,
        )
        flashcards = SimpleNamespace(
            get_or_generate_flashcard_set=AsyncMock(return_value=SimpleNamespace(flashcards=[]))
        )
        lessons = SimpleNamespace(get_or_generate_lesson=AsyncMock(return_value=object()))
        quizzes = SimpleNamespace(get_or_generate_quiz=AsyncMock(return_value=object()))
        storage = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://minio/x.zip"))

        async def cached(_session, module_id, language):
            # Module 2's story is stale (or missing): the bundle skips it.
            return dict(STORY) if module_id == ready_module.id else None

        cached_story = AsyncMock(side_effect=cached)
        with (
            patch.object(
                course_bundle, "_make_session_factory", return_value=(engine, lambda: session)
            ),
            patch.object(course_bundle, "_cached_module_story", cached_story),
            patch.object(course_bundle.generate_course_bundle_task, "update_state"),
            patch("app.ai.claude_service.ClaudeService"),
            patch("app.ai.rag.retriever.SemanticRetriever"),
            patch("app.domain.services.bundle_service.BundleService", return_value=bundle_service),
            patch(
                "app.domain.services.flashcard_service.FlashcardGenerationService",
                return_value=flashcards,
            ),
            patch(
                "app.domain.services.lesson_service.LessonGenerationService", return_value=lessons
            ),
            patch("app.domain.services.lesson_service.CaseStudyGenerationService"),
            patch("app.domain.services.quiz_service.QuizService", return_value=quizzes),
            patch("app.infrastructure.storage.s3.S3StorageService", return_value=storage),
        ):
            result = course_bundle.generate_course_bundle_task.run(str(uuid.uuid4()))

        assert result["status"] == "ready", result
        [files] = zipped
        stories = [name for name in files if "_story_" in name]
        assert stories == ["001_00_story_fr.json"]
        # Looked up once per module, never per unit, and only from the cache.
        assert cached_story.await_count == 2
        assert {call.args[1] for call in cached_story.await_args_list} == {
            m.id for m in course.modules
        }
        assert files.index("001_00_flashcards_fr.html") < files.index("001_00_story_fr.json")
        assert bundle.status == "ready"
