"""API tests for a lesson's story mode: GET /api/v1/story-courses/unit/{module}/{unit}.

The database, the generation service and Celery are mocked: these pin the
HTTP contract (200 story / 202 generating envelope / 409 story_unavailable /
404 when the feature is off, for a non-lesson unit, or with generate=false and
nothing cached), the access gate, route ordering against ``/{slug}``, that a
lesson story is never served by slug to a learner, and the dispatch dedup that
keeps concurrent first views from paying for two generations.
"""

from __future__ import annotations

import uuid
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
        patch.object(
            api, "_resolve_unit", AsyncMock(return_value=(MODULE_ID, UNIT_ID, "lesson"))
        ) as unit,
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

    @pytest.mark.parametrize("unit_type", ["quiz", "case-study", "scenario"])
    async def test_non_lesson_unit_is_404_and_nothing_is_generated(
        self, as_role, client, mocks, unit_type
    ):
        as_role()
        mocks.unit.return_value = (MODULE_ID, UNIT_ID, unit_type)
        resp = await client.get(URL)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "not_a_lesson"
        mocks.find.assert_not_awaited()
        mocks.dispatch.assert_not_awaited()

    @pytest.mark.parametrize("unit_type", ["lesson", None])
    async def test_lesson_and_untyped_units_have_a_story(self, as_role, client, mocks, unit_type):
        as_role()
        mocks.unit.return_value = (MODULE_ID, UNIT_ID, unit_type)
        assert (await client.get(URL)).status_code == 202

    async def test_cached_only_with_nothing_cached_is_404_and_dispatches_nothing(
        self, as_role, client, mocks
    ):
        as_role()
        resp = await client.get(URL, params={"generate": "false"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_not_cached"
        mocks.dispatch.assert_not_awaited()

    async def test_cached_only_with_a_stale_story_is_404_and_dispatches_nothing(
        self, as_role, client, mocks
    ):
        as_role("admin")
        mocks.find.return_value = _record()
        mocks.fresh.return_value = False
        resp = await client.get(URL, params={"generate": "false", "force_regenerate": "true"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_not_cached"
        mocks.dispatch.assert_not_awaited()

    async def test_cached_only_still_serves_a_fresh_story(self, as_role, client, mocks):
        as_role()
        mocks.find.return_value = _record()
        resp = await client.get(URL, params={"generate": "false"})
        assert resp.status_code == 200
        assert resp.json() == STORY
        mocks.dispatch.assert_not_awaited()

    async def test_cached_only_reports_an_unavailable_story_as_409(self, as_role, client, mocks):
        as_role()
        mocks.find.return_value = _record(is_valid=False, status="draft")
        resp = await client.get(URL, params={"generate": "false"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "story_unavailable"
        mocks.dispatch.assert_not_awaited()

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
        patch.object(api, "generate_story_task", task),
        patch.object(api, "mark_task_dispatched", AsyncMock()) as marked,
        patch.object(api, "vouch_while_owned", AsyncMock()) as vouched,
    ):
        yield SimpleNamespace(task=task, marked=marked, vouched=vouched)


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


def _state(state: str):
    return patch.object(api, "AsyncResult", return_value=SimpleNamespace(state=state))


KEY = f"story_dispatch:{UNIT_ID}:fr"


class TestDispatch:
    async def test_first_view_claims_the_key_and_dispatches(self, redis, celery):
        task_id = await _dispatch()
        key, value = redis.set.await_args.args
        assert key == KEY and value == task_id
        assert redis.set.await_args.kwargs == {"nx": True, "ex": api._STORY_DISPATCH_TTL_S}
        celery.task.apply_async.assert_called_once_with(
            args=[str(MODULE_ID), "1.2", "fr", "CI", 1, False],
            kwargs={"dedup_key": KEY},
            task_id=task_id,
        )
        celery.marked.assert_awaited_once_with(task_id)

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
        """FC-5(a): a long queue is not a dead task while its key lives."""
        redis.get.return_value = "queued-task"
        marker = AsyncMock()
        with _state("PENDING"), patch("app.api.v1._task_status.dispatched_at", marker):
            assert await _dispatch() == "queued-task"
        celery.task.apply_async.assert_not_called()
        marker.assert_not_awaited()
        redis.delete.assert_not_awaited()
        redis.eval.assert_not_awaited()

    async def test_just_claimed_task_without_a_dispatch_marker_is_joined(self, redis, celery):
        """FC-5(b): between SET NX and the dispatch marker the key is PENDING, unmarked."""
        redis.get.return_value = "just-claimed"
        with _state("PENDING"):
            assert await _dispatch() == "just-claimed"
        celery.task.apply_async.assert_not_called()
        redis.delete.assert_not_awaited()
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
        celery.vouched.assert_awaited_once_with(task_id, KEY, api._STORY_DISPATCH_TTL_S)
        assert order == ["vouch", "claim"]

    async def test_joining_a_running_task_vouches_for_nothing_new(self, redis, celery):
        redis.get.return_value = "running-task"
        with _state("PENDING"):
            assert await _dispatch() == "running-task"
        celery.vouched.assert_not_awaited()


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

        await vouch_while_owned("task-1", KEY, api._STORY_DISPATCH_TTL_S)
        store.data[KEY] = "task-1"
        body = await self._status("task-1", marker_age_s=TASK_STALL_THRESHOLD_S + 60)
        assert body == {"status": "pending"}

    async def test_a_just_claimed_story_without_a_marker_is_pending(self, store):
        from app.api.v1._task_status import vouch_while_owned

        await vouch_while_owned("task-1", KEY, api._STORY_DISPATCH_TTL_S)
        store.data[KEY] = "task-1"
        assert await self._status("task-1", marker_age_s=None) == {"status": "pending"}

    async def test_once_the_key_names_another_task_the_stall_rule_applies(self, store):
        from app.api.v1._task_status import TASK_STALL_THRESHOLD_S, vouch_while_owned

        await vouch_while_owned("task-1", KEY, api._STORY_DISPATCH_TTL_S)
        store.data[KEY] = "task-2"  # released and claimed again
        body = await self._status("task-1", marker_age_s=TASK_STALL_THRESHOLD_S + 60)
        assert body == {"status": "failed", "error": "task_stalled"}
        del store.data[KEY]  # released, nobody claimed it
        assert await self._status("task-1", marker_age_s=None) == {
            "status": "failed",
            "error": "task_lost",
        }

    async def test_an_unvouched_task_still_stalls(self, store):
        from app.api.v1._task_status import TASK_STALL_THRESHOLD_S

        body = await self._status("lesson-task", marker_age_s=TASK_STALL_THRESHOLD_S + 60)
        assert body == {"status": "failed", "error": "task_stalled"}

    async def test_vouching_never_raises_without_redis(self):
        from app.api.v1 import _task_status

        broken = MagicMock()
        broken.setex = AsyncMock(side_effect=ConnectionError("redis down"))
        broken.get = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch.object(_task_status, "redis_client", broken):
            await _task_status.vouch_while_owned("task-1", KEY, 60)
            assert await _task_status.is_vouched("task-1") is False


def test_story_task_limits_fit_a_lesson_plus_three_story_calls():
    from app.domain.services.story_from_lesson_service import MAX_REPAIR_CALLS
    from app.tasks.content_generation import (
        POLL_SOFT_LIMIT,
        STORY_HARD_LIMIT,
        STORY_SOFT_LIMIT,
        generate_story_task,
    )

    assert generate_story_task.name == "app.tasks.content_generation.generate_story_task"
    assert generate_story_task.soft_time_limit == STORY_SOFT_LIMIT
    assert generate_story_task.time_limit == STORY_HARD_LIMIT
    assert STORY_HARD_LIMIT > STORY_SOFT_LIMIT
    # The lesson alone may take the lesson task's whole budget; then the spine
    # calls (1 + MAX_REPAIR_CALLS) still need room.
    assert STORY_SOFT_LIMIT >= POLL_SOFT_LIMIT + (1 + MAX_REPAIR_CALLS) * 150
    assert generate_story_task.rate_limit == "5/m"
    assert not getattr(generate_story_task, "autoretry_for", ())
    # The dedup key outlives the task.
    assert api._STORY_DISPATCH_TTL_S > STORY_HARD_LIMIT


def test_story_task_reports_failure_instead_of_raising():
    from app.tasks import content_generation

    def failing_run(coroutine):
        coroutine.close()  # never started; close it so it is not left unawaited
        raise RuntimeError("model down")

    with (
        patch("asyncio.run", side_effect=failing_run),
        patch.object(content_generation, "_release_story_dispatch") as release,
    ):
        result = content_generation.generate_story_task.run(str(MODULE_ID), "1.2", "fr")
    assert result == {"status": "failed", "error": "model down"}
    release.assert_called_once()


def test_story_task_on_its_soft_time_limit_fails_and_releases_its_key():
    from celery.exceptions import SoftTimeLimitExceeded

    from app.tasks import content_generation

    def timed_out(coroutine):
        coroutine.close()
        raise SoftTimeLimitExceeded()

    task = content_generation.generate_story_task
    with (
        patch("asyncio.run", side_effect=timed_out),
        patch.object(content_generation, "_release_story_dispatch") as release,
    ):
        task.push_request(id="task-42")
        try:
            result = task.run(str(MODULE_ID), "1.2", "fr", dedup_key=KEY)
        finally:
            task.pop_request()
    assert result == {"status": "failed", "error": "time_limit_exceeded"}
    release.assert_called_once_with(KEY, "task-42")


def test_task_key_release_is_a_compare_and_delete_on_its_own_id():
    from app.tasks import content_generation

    client = MagicMock()
    with patch("redis.Redis.from_url", return_value=client):
        content_generation._release_story_dispatch(KEY, "task-42")
    script, numkeys, key, value = client.eval.call_args.args
    assert "ARGV[1]" in script and (numkeys, key, value) == (1, KEY, "task-42")
    client.delete.assert_not_called()
    client.close.assert_called_once()


def test_task_key_release_never_raises():
    from app.tasks import content_generation

    with patch("redis.Redis.from_url", side_effect=ConnectionError("redis down")):
        content_generation._release_story_dispatch(KEY, "task-42")
    content_generation._release_story_dispatch(None, "task-42")  # nothing claimed
