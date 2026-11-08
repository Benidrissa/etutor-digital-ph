"""API tests for a lesson's story mode: GET /api/v1/story-courses/unit/{module}/{unit}.

The database, the generation service and Celery are mocked: these pin the
HTTP contract (200 story / 202 generating envelope / 409 story_unavailable /
404 when the feature is off), the access gate, route ordering against
``/{slug}``, and the dispatch dedup that keeps concurrent first views from
paying for two generations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, get_db_session
from app.api.deps_local_auth import (
    AuthenticatedUser,
    get_current_user,
    require_subscription_or_first_unit,
)
from app.api.v1 import story_courses as api
from app.main import app

MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")
UNIT_ID = uuid.UUID("2f1e0d3c-4b5a-4968-8776-655443322110")
URL = "/api/v1/story-courses/unit/M03/1.2"
STORY = {
    "format": "story-course/1",
    "id": f"lesson-{UNIT_ID.hex}-fr",
    "learner": {"first_name": "{child}"},
}


def _user(role: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser(
        {"sub": "22222222-2222-2222-2222-222222222222", "email": "l@example.com", "role": role}
    )


class _Unusable:
    """A DB session stub that fails loudly if a handler touches it."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was used: {name}")


@pytest.fixture
def as_role():
    def install(role: str = "user") -> None:
        async def no_db():
            yield _Unusable()

        app.dependency_overrides[require_subscription_or_first_unit] = lambda: _user(role)
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_db] = no_db
        app.dependency_overrides[get_db_session] = no_db

    yield install
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mocks():
    """Patch everything the handler calls; each test sets the return values."""
    with (
        patch.object(api, "story_mode_enabled", return_value=True) as enabled,
        patch.object(api, "_resolve_unit", AsyncMock(return_value=(MODULE_ID, UNIT_ID))) as unit,
        patch.object(api, "find_unit_story", AsyncMock(return_value=None)) as find,
        patch.object(api, "story_sources_are_fresh", AsyncMock(return_value=True)) as fresh,
        patch.object(
            api, "_dispatch_story_generation", AsyncMock(return_value="task-123")
        ) as dispatch,
    ):
        yield SimpleNamespace(enabled=enabled, unit=unit, find=find, fresh=fresh, dispatch=dispatch)


def _record(is_valid: bool = True, status: str = "published"):
    return SimpleNamespace(is_valid=is_valid, status=status, content=dict(STORY))


class TestUnitStory:
    async def test_cached_valid_story_is_200(self, as_role, client, mocks):
        as_role()
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"language": "fr"})
        assert resp.status_code == 200
        assert resp.json() == STORY
        assert resp.headers["cache-control"] == "private, no-cache"
        mocks.dispatch.assert_not_awaited()
        mocks.find.assert_awaited_once()
        assert mocks.find.await_args.args[1:] == (UNIT_ID, "fr")

    async def test_missing_story_dispatches_and_is_202(self, as_role, client, mocks):
        as_role()
        resp = await client.get(URL, params={"language": "en", "level": 2, "country": "sn"})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "generating" and body["task_id"] == "task-123"
        kwargs = mocks.dispatch.await_args.kwargs
        assert kwargs == {
            "module_id": MODULE_ID,
            "unit_id": "1.2",
            "module_unit_id": UNIT_ID,
            "language": "en",
            "country": "SN",
            "level": 2,
            "force_regenerate": False,
        }

    async def test_stale_story_is_regenerated(self, as_role, client, mocks):
        as_role()
        mocks.find.return_value = _record()
        mocks.fresh.return_value = False
        resp = await client.get(URL)
        assert resp.status_code == 202
        mocks.dispatch.assert_awaited_once()

    async def test_invalid_story_that_is_not_stale_is_409(self, as_role, client, mocks):
        as_role()
        mocks.find.return_value = _record(is_valid=False, status="draft")
        resp = await client.get(URL)
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["error"] == "story_unavailable"
        assert detail["message"]
        mocks.dispatch.assert_not_awaited()

    async def test_invalid_story_whose_sources_changed_is_retried(self, as_role, client, mocks):
        as_role()
        mocks.find.return_value = _record(is_valid=False, status="draft")
        mocks.fresh.return_value = False
        assert (await client.get(URL)).status_code == 202

    async def test_feature_flag_off_is_404(self, as_role, client, mocks):
        as_role()
        mocks.enabled.return_value = False
        resp = await client.get(URL)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_mode_disabled"
        mocks.unit.assert_not_awaited()
        mocks.dispatch.assert_not_awaited()

    async def test_learners_cannot_force_a_regeneration(self, as_role, client, mocks):
        as_role("user")
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"force_regenerate": "true"})
        assert resp.status_code == 200
        mocks.dispatch.assert_not_awaited()

    async def test_admins_can_force_a_regeneration(self, as_role, client, mocks):
        as_role("admin")
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"force_regenerate": "true"})
        assert resp.status_code == 202
        assert mocks.dispatch.await_args.kwargs["force_regenerate"] is True

    async def test_unsupported_language_is_422(self, as_role, client, mocks):
        as_role()
        assert (await client.get(URL, params={"language": "de"})).status_code == 422

    async def test_unit_is_not_swallowed_by_the_slug_route(self, as_role, client, mocks):
        """``/{slug}`` would query the (unusable) session and fail; it must not run."""
        as_role()
        mocks.find.return_value = _record()
        resp = await client.get("/api/v1/story-courses/unit/M03/1.2")
        assert resp.status_code == 200
        mocks.unit.assert_awaited_once()
        assert mocks.unit.await_args.args[1:] == ("M03", "1.2")

    async def test_route_is_declared_before_the_slug_route(self):
        paths = [route.path for route in api.router.routes if "GET" in route.methods]
        assert paths.index("/story-courses/unit/{module_id}/{unit_id}") < paths.index(
            "/story-courses/{slug}"
        )

    async def test_access_follows_the_lesson_gate(self, client):
        """No subscription and not a free unit: the lesson's 403 applies here too."""
        app.dependency_overrides.clear()
        resp = await client.get(URL)
        assert resp.status_code in (401, 403)
        route = next(r for r in api.router.routes if r.path.endswith("{unit_id}"))
        gates = [d.call for d in route.dependant.dependencies]
        assert require_subscription_or_first_unit in gates


class TestCatalog:
    async def test_lesson_stories_are_not_listed_in_the_catalog(self, client):
        captured = []

        class Db:
            async def execute(self, statement):
                captured.append(statement)
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        async def db():
            yield Db()

        app.dependency_overrides[get_current_user] = lambda: _user()
        app.dependency_overrides[get_db] = db
        app.dependency_overrides[get_db_session] = db
        try:
            resp = await client.get("/api/v1/story-courses")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert "story_courses.module_unit_id IS NULL" in str(captured[0])


# --------------------------------------------------------------------------
# Dispatch dedup
# --------------------------------------------------------------------------


@pytest.fixture
def redis():
    client = MagicMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    with patch("app.infrastructure.cache.redis.redis_client", client):
        yield client


@pytest.fixture
def celery():
    task = MagicMock()
    with (
        patch.object(api, "generate_story_task", task),
        patch.object(api, "mark_task_dispatched", AsyncMock()) as marked,
    ):
        yield SimpleNamespace(task=task, marked=marked)


def _dispatch():
    return api._dispatch_story_generation(
        module_id=MODULE_ID,
        unit_id="1.2",
        module_unit_id=UNIT_ID,
        language="fr",
        country="CI",
        level=1,
        force_regenerate=False,
    )


class TestDispatch:
    async def test_first_view_claims_the_key_and_dispatches(self, redis, celery):
        task_id = await _dispatch()
        key, value = redis.set.await_args.args
        assert key == f"story_dispatch:{UNIT_ID}:fr" and value == task_id
        assert redis.set.await_args.kwargs == {"nx": True, "ex": api._STORY_DISPATCH_TTL_S}
        celery.task.apply_async.assert_called_once_with(
            args=[str(MODULE_ID), "1.2", "fr", "CI", 1, False], task_id=task_id
        )
        celery.marked.assert_awaited_once_with(task_id)

    async def test_concurrent_view_joins_the_running_task(self, redis, celery):
        redis.get.return_value = "running-task"
        with patch.object(api, "AsyncResult", return_value=SimpleNamespace(state="STARTED")):
            assert await _dispatch() == "running-task"
        celery.task.apply_async.assert_not_called()

    async def test_view_that_loses_the_race_joins_the_winner(self, redis, celery):
        redis.get.side_effect = [None, "winner-task"]
        redis.set.return_value = False
        assert await _dispatch() == "winner-task"
        celery.task.apply_async.assert_not_called()

    async def test_finished_task_no_longer_blocks_a_new_one(self, redis, celery):
        redis.get.return_value = "old-task"
        with patch.object(api, "AsyncResult", return_value=SimpleNamespace(state="SUCCESS")):
            task_id = await _dispatch()
        assert task_id != "old-task"
        redis.delete.assert_awaited_once()
        celery.task.apply_async.assert_called_once()

    async def test_task_that_never_started_is_replaced(self, redis, celery):
        redis.get.return_value = "lost-task"
        stale = datetime.now(tz=UTC) - timedelta(seconds=api.TASK_STALL_THRESHOLD_S + 5)
        with (
            patch.object(api, "AsyncResult", return_value=SimpleNamespace(state="PENDING")),
            patch.object(api, "task_dispatched_at", AsyncMock(return_value=stale)),
        ):
            task_id = await _dispatch()
        assert task_id != "lost-task"
        celery.task.apply_async.assert_called_once()

    async def test_queued_task_is_joined(self, redis, celery):
        redis.get.return_value = "queued-task"
        with (
            patch.object(api, "AsyncResult", return_value=SimpleNamespace(state="PENDING")),
            patch.object(api, "task_dispatched_at", AsyncMock(return_value=datetime.now(tz=UTC))),
        ):
            assert await _dispatch() == "queued-task"
        celery.task.apply_async.assert_not_called()

    async def test_without_redis_it_fails_open(self, redis, celery):
        redis.get.side_effect = ConnectionError("redis down")
        task_id = await _dispatch()
        celery.task.apply_async.assert_called_once()
        assert celery.task.apply_async.call_args.kwargs["task_id"] == task_id


def test_story_task_is_registered_with_the_lesson_task_limits():
    from app.tasks.content_generation import (
        POLL_HARD_LIMIT,
        POLL_SOFT_LIMIT,
        generate_story_task,
    )

    assert generate_story_task.name == "app.tasks.content_generation.generate_story_task"
    assert generate_story_task.soft_time_limit == POLL_SOFT_LIMIT
    assert generate_story_task.time_limit == POLL_HARD_LIMIT
    assert generate_story_task.rate_limit == "5/m"
    assert not getattr(generate_story_task, "autoretry_for", ())


def test_story_task_reports_failure_instead_of_raising():
    from app.tasks import content_generation

    def failing_run(coroutine):
        coroutine.close()  # never started; close it so it is not left unawaited
        raise RuntimeError("model down")

    with patch("asyncio.run", side_effect=failing_run):
        result = content_generation.generate_story_task.run(str(MODULE_ID), "1.2", "fr")
    assert result == {"status": "failed", "error": "model down"}


# --------------------------------------------------------------------------
# Offline bundle
# --------------------------------------------------------------------------


class TestBundleStory:
    """The offline bundle carries a unit's story only when one is ready."""

    @pytest.fixture
    def svc(self):
        service = "app.domain.services.story_from_lesson_service"
        with (
            patch(f"{service}.find_unit_story", AsyncMock()) as find,
            patch(f"{service}.story_sources_are_fresh", AsyncMock(return_value=True)) as fresh,
        ):
            yield SimpleNamespace(find=find, fresh=fresh)

    async def test_ready_story_is_bundled(self, svc):
        from app.tasks.course_bundle import _cached_unit_story

        svc.find.return_value = SimpleNamespace(is_valid=True, status="published", content=STORY)
        assert await _cached_unit_story(object(), UNIT_ID, "fr") == STORY

    @pytest.mark.parametrize(
        ("record", "fresh"),
        [
            (None, True),
            (SimpleNamespace(is_valid=False, status="draft", content=STORY), True),
            (SimpleNamespace(is_valid=True, status="published", content=STORY), False),
        ],
    )
    async def test_missing_invalid_or_stale_story_is_not_bundled(self, svc, record, fresh):
        from app.tasks.course_bundle import _cached_unit_story

        svc.find.return_value = record
        svc.fresh.return_value = fresh
        assert await _cached_unit_story(object(), UNIT_ID, "fr") is None
