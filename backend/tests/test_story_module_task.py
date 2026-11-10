"""The Celery task that makes a module story: its budget, wiring and results.

The task runs for real (``asyncio.run`` included) with the services it builds
replaced by fakes: no database, no model, no provider client. Releasing the
API's dedup key is checked against a real Redis when one is reachable.
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.ai.usage_context import current_ai_context
from app.domain.services.story_module_service import (
    ChapterGenerationFailed,
    find_module_story,
    story_dispatch_key,
)
from app.tasks import content_generation
from app.tasks.content_generation import (
    MODULE_STORY_HARD_LIMIT,
    MODULE_STORY_SOFT_LIMIT,
    generate_module_story_task,
)

MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")
#: The real compare-and-delete, taken before any test replaces it.
_REAL_RELEASE = content_generation._release_story_dispatch
#: The real re-arm of the key as the task starts, likewise.
_REAL_HOLD = content_generation._hold_story_dispatch
STORY_ID = uuid.UUID(int=99)
TASK_ID = "task-42"


def test_the_task_is_declared_with_its_budget_and_no_retry():
    from app.tasks.celery_app import celery_app

    task = generate_module_story_task
    assert task.name == "app.tasks.content_generation.generate_module_story_task"
    # #2680: the chapters are told one after another (8-10 min for 3 lessons,
    # 14 for 6); the run keeps its own deadline and continues in a new task.
    assert (MODULE_STORY_SOFT_LIMIT, MODULE_STORY_HARD_LIMIT) == (2400, 2460)
    assert task.soft_time_limit == MODULE_STORY_SOFT_LIMIT
    assert task.time_limit == MODULE_STORY_HARD_LIMIT
    assert task.rate_limit == "5/m"
    assert not getattr(task, "autoretry_for", ())
    assert content_generation.MODULE_STORY_DEADLINE_MARGIN_S == 150
    assert content_generation.MODULE_STORY_MAX_CONTINUATIONS == 2
    # The API's dedup key (HARD + 60) expires before a redelivery or a lost result.
    dedup_ttl = MODULE_STORY_HARD_LIMIT + 60
    assert dedup_ttl < 3600
    assert dedup_ttl < celery_app.conf.result_expires
    visibility = (celery_app.conf.broker_transport_options or {}).get("visibility_timeout", 3600)
    assert dedup_ttl < visibility


class FakeModuleStoryService:
    """Stands in for ModuleStoryService; records how the task built and called it."""

    instances: list[FakeModuleStoryService] = []
    outcome: Any = None
    #: Called while the "generation" runs, to look at the world from inside it.
    during: Any = None

    def __init__(self, claude_service, lesson_service, quiz_service, **kwargs) -> None:
        self.args = (claude_service, lesson_service, quiz_service)
        self.kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        FakeModuleStoryService.instances.append(self)

    async def get_or_generate_module_story(
        self,
        module_id,
        language,
        session_factory,
        *,
        level,
        country,
        force_regenerate,
        deadline=None,
    ):
        self.calls.append(
            {
                "module_id": module_id,
                "language": language,
                "session_factory": session_factory,
                "level": level,
                "country": country,
                "force_regenerate": force_regenerate,
                "deadline": deadline,
                "feature": current_ai_context().feature,
            }
        )
        if FakeModuleStoryService.during is not None:
            FakeModuleStoryService.during()
        outcome = FakeModuleStoryService.outcome
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeLock:
    """Stands in for the run's advisory lock; ``taken`` says whether it is free."""

    def __init__(self) -> None:
        self.taken = True
        self.calls: list[tuple[Any, str, str]] = []

    @contextlib.asynccontextmanager
    async def __call__(self, engine, module_id: str, language: str):
        self.calls.append((engine, module_id, language))
        yield self.taken


@pytest.fixture
def wiring():
    """Every collaborator the task builds, replaced; yields what the test inspects."""
    FakeModuleStoryService.instances = []
    FakeModuleStoryService.outcome = SimpleNamespace(id=STORY_ID, is_valid=True)
    FakeModuleStoryService.during = None
    engine = MagicMock()
    engine.dispose = AsyncMock()
    lock = FakeLock()
    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine) as create,
        patch("app.ai.claude_service.ClaudeService") as claude,
        patch("app.ai.rag.embeddings.EmbeddingService") as embeddings,
        patch("app.ai.rag.retriever.SemanticRetriever") as retriever,
        patch("app.domain.services.lesson_service.LessonGenerationService") as lessons,
        patch("app.domain.services.quiz_service.QuizService") as quizzes,
        patch(
            "app.domain.services.story_module_service.ModuleStoryService",
            FakeModuleStoryService,
        ),
        patch.object(content_generation, "_release_story_dispatch") as release,
        patch.object(content_generation, "_hold_story_dispatch") as hold,
        patch.object(content_generation, "_module_story_lock", lock),
    ):
        yield SimpleNamespace(
            create=create,
            engine=engine,
            claude=claude,
            embeddings=embeddings,
            retriever=retriever,
            lessons=lessons,
            quizzes=quizzes,
            release=release,
            hold=hold,
            lock=lock,
        )


def run_task(*args: Any, **kwargs: Any) -> dict:
    task = generate_module_story_task
    task.push_request(id=TASK_ID)
    try:
        return task.run(*args, **kwargs)
    finally:
        task.pop_request()


def test_a_complete_run_builds_the_services_and_reports_the_story(wiring):
    key = story_dispatch_key(MODULE_ID, "fr")
    result = run_task(
        str(MODULE_ID), "fr", country="SN", level=2, force_regenerate=True, dedup_key=key
    )

    assert result == {"status": "complete", "content_id": str(STORY_ID), "is_valid": True}
    # An engine sized for six concurrent chapter sessions, disposed at the end.
    assert wiring.create.call_args.kwargs["pool_size"] == 8
    assert wiring.create.call_args.kwargs["max_overflow"] == 2
    wiring.engine.dispose.assert_awaited_once()
    # One model client and one retriever, shared by the lesson and quiz services.
    claude = wiring.claude.return_value
    retriever = wiring.retriever.return_value
    wiring.lessons.assert_called_once_with(claude, retriever)
    wiring.quizzes.assert_called_once_with(claude, retriever)
    (service,) = FakeModuleStoryService.instances
    assert service.args == (claude, wiring.lessons.return_value, wiring.quizzes.return_value)
    (call,) = service.calls
    assert call["module_id"] == MODULE_ID and call["language"] == "fr"
    assert (call["level"], call["country"], call["force_regenerate"]) == (2, "SN", True)
    assert call["feature"] == "story_generation"  # the ledger's default for the run
    assert callable(call["session_factory"])
    # The run's own deadline: the soft limit less a margin, on the monotonic clock.
    import time

    left = call["deadline"] - time.monotonic()
    assert MODULE_STORY_SOFT_LIMIT - 200 < left <= MODULE_STORY_SOFT_LIMIT - 150
    # A figure whose binary is gone is never offered (#2681).
    assert "figure_storage" in service.kwargs
    # The key is armed again as the task starts, then released as it ends.
    wiring.hold.assert_called_once_with(key, TASK_ID, MODULE_STORY_HARD_LIMIT + 60)
    wiring.release.assert_called_once_with(key, TASK_ID)
    # The run holds the (module, language) lock on the task's own engine.
    assert wiring.lock.calls == [(wiring.engine, str(MODULE_ID), "fr")]


def test_a_copy_the_run_lock_turns_away_pays_nothing_and_keeps_the_key(wiring):
    """A broker redelivery of the same id while the first copy runs: skipped."""
    wiring.lock.taken = False
    result = run_task(str(MODULE_ID), "fr", dedup_key="k")
    assert result == content_generation.MODULE_STORY_SKIPPED
    assert result["status"] == "skipped" and result["content_id"] is None
    assert FakeModuleStoryService.instances == []  # nothing built, nothing paid
    wiring.claude.assert_not_called()
    wiring.release.assert_not_called()  # the running copy may have this very id
    wiring.engine.dispose.assert_awaited_once()


def test_the_run_lock_has_its_own_key_space():
    from app.domain.services import story_bible, story_plan
    from app.tasks.story_art import STORY_ART_LOCK_NAMESPACE

    namespace, key = content_generation.module_story_lock_key(str(MODULE_ID), "fr")
    assert namespace == content_generation.MODULE_STORY_LOCK_NAMESPACE != STORY_ART_LOCK_NAMESPACE
    assert -(2**31) <= key < 2**31
    assert key != content_generation.module_story_lock_key(str(MODULE_ID), "en")[1]
    # The bible's and the plan's locks are single bigints: another key space.
    assert isinstance(story_bible._lock_key(MODULE_ID), int)
    assert isinstance(story_plan._lock_key(MODULE_ID, "fr"), int)


def test_an_invalid_story_still_completes(wiring):
    FakeModuleStoryService.outcome = SimpleNamespace(id=STORY_ID, is_valid=False)
    result = run_task(str(MODULE_ID), "en")
    assert result == {"status": "complete", "content_id": str(STORY_ID), "is_valid": False}


def test_failed_chapters_are_reported_by_unit_and_release_the_key(wiring):
    FakeModuleStoryService.outcome = ChapterGenerationFailed(["1.2", "1.5"])
    result = run_task(str(MODULE_ID), "en", dedup_key="k")
    assert result == {
        "status": "failed",
        "content_id": None,
        "is_valid": False,
        "error": "chapter_generation_failed",
        "failed_units": ["1.2", "1.5"],
    }
    wiring.engine.dispose.assert_awaited_once()
    wiring.release.assert_called_once_with("k", TASK_ID)


def test_a_run_that_reaches_its_deadline_continues_in_a_new_task(wiring):
    from app.domain.services.story_module_service import StoryDeadlineReached

    FakeModuleStoryService.outcome = StoryDeadlineReached(["1.1", "1.2"])
    events: list[str] = []
    with (
        patch.object(
            generate_module_story_task,
            "apply_async",
            side_effect=lambda **_kw: events.append("dispatch"),
        ) as dispatch,
        patch("redis.Redis.from_url") as redis_client,
    ):
        redis_client.return_value.setex.side_effect = lambda key, *_a: events.append(key)
        result = run_task(str(MODULE_ID), "fr", country="SN", force_regenerate=True, dedup_key="k")
    next_id = result["continued_by"]
    assert uuid.UUID(next_id)  # made by the task, before the dispatch
    assert result == {
        "status": "complete",
        "content_id": None,
        "is_valid": False,
        "continued_by": next_id,
        "told": ["1.1", "1.2"],
    }
    assert dispatch.call_args.kwargs["task_id"] == next_id
    kwargs = dispatch.call_args.kwargs["kwargs"]
    assert kwargs["continuation"] == 1 and kwargs["dedup_key"] == "k"
    assert kwargs["force_regenerate"] is False  # never pays twice for what was told
    assert (kwargs["module_id"], kwargs["country"]) == (str(MODULE_ID), "SN")
    # Marked and vouched for before it is queued, as the API does for the first
    # task: a learner who joins it while it waits sees it pending, not lost.
    setex = {c.args[0]: c.args[1:] for c in redis_client.return_value.setex.call_args_list}
    assert setex[f"content_task_owner:{next_id}"] == (MODULE_STORY_HARD_LIMIT + 60, "k")
    assert f"content_task:{next_id}" in setex
    assert events == [f"content_task:{next_id}", f"content_task_owner:{next_id}", "dispatch"]
    # The dedup key is handed to the continuation, so a learner's GET joins it.
    script, _n, key, holder, new, ttl = redis_client.return_value.eval.call_args.args
    assert (key, holder, new, ttl) == ("k", TASK_ID, next_id, MODULE_STORY_HARD_LIMIT + 60)
    wiring.release.assert_called_once_with("k", TASK_ID)


def test_a_queued_continuation_is_pending_for_the_status_endpoint(wiring):
    """Against a real Redis: the continuation is vouched for while the key names it."""
    import asyncio

    from app.api.v1 import content as content_api
    from app.domain.services.story_module_service import StoryDeadlineReached

    client = _redis_or_skip()
    key = story_dispatch_key(MODULE_ID, "fr")
    FakeModuleStoryService.outcome = StoryDeadlineReached(["1.1"])
    wiring.hold.side_effect = _REAL_HOLD
    wiring.release.side_effect = _REAL_RELEASE
    next_id = None
    try:
        client.set(key, TASK_ID, ex=60)
        with patch.object(generate_module_story_task, "apply_async"):
            result = run_task(str(MODULE_ID), "fr", dedup_key=key)
        next_id = result["continued_by"]
        assert client.get(key) == next_id  # handed over, not released
        assert client.get(f"content_task_owner:{next_id}") == key
        assert client.get(f"content_task:{next_id}")

        async def status() -> dict:
            from app.infrastructure.cache.redis import redis_client

            try:
                with patch.object(
                    content_api, "AsyncResult", return_value=SimpleNamespace(state="PENDING")
                ):
                    response = await content_api.get_generation_status(next_id)
                import json

                return json.loads(response.body)
            finally:
                with contextlib.suppress(Exception):
                    await redis_client.aclose()

        assert asyncio.run(status()) == {"status": "pending"}
    finally:
        client.delete(key)
        if next_id:
            client.delete(f"content_task_owner:{next_id}", f"content_task:{next_id}")
        client.close()


def test_a_continuation_never_forces_and_the_last_one_stops(wiring):
    from app.domain.services.story_module_service import StoryDeadlineReached

    FakeModuleStoryService.outcome = SimpleNamespace(id=STORY_ID, is_valid=True)
    run_task(str(MODULE_ID), "fr", force_regenerate=True, continuation=1)
    (service,) = FakeModuleStoryService.instances
    assert service.calls[0]["force_regenerate"] is False

    FakeModuleStoryService.outcome = StoryDeadlineReached(["1.3"])
    with (
        patch.object(generate_module_story_task, "apply_async") as dispatch,
        patch("redis.Redis.from_url"),
    ):
        result = run_task(str(MODULE_ID), "fr", continuation=2)
    dispatch.assert_not_called()
    assert result["status"] == "failed" and result["error"] == "time_limit_exceeded"


def test_the_soft_time_limit_fails_the_task_and_releases_the_key(wiring):
    FakeModuleStoryService.outcome = SoftTimeLimitExceeded()
    result = run_task(str(MODULE_ID), "en", dedup_key="k")
    assert result == {
        "status": "failed",
        "content_id": None,
        "is_valid": False,
        "error": "time_limit_exceeded",
    }
    wiring.engine.dispose.assert_awaited_once()
    wiring.release.assert_called_once_with("k", TASK_ID)


def test_any_other_error_is_reported_not_raised(wiring):
    FakeModuleStoryService.outcome = RuntimeError("database down")
    result = run_task(str(MODULE_ID), "en")
    assert result == {
        "status": "failed",
        "content_id": None,
        "is_valid": False,
        "error": "database down",
    }
    wiring.release.assert_called_once_with(None, TASK_ID)


def test_the_soft_time_limit_releases_the_real_dedup_key_it_owns(wiring):
    """Against a real Redis: the compare-and-delete removes only this task's key."""
    import redis

    from app.infrastructure.config.settings import settings

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
    try:
        client.ping()
    except redis.RedisError as exc:
        pytest.skip(f"no Redis server: {exc}"[:200])
    owned = story_dispatch_key(MODULE_ID, "en")
    other = story_dispatch_key(MODULE_ID, "fr")
    try:
        client.set(owned, TASK_ID, ex=60)
        client.set(other, "another-task", ex=60)
        FakeModuleStoryService.outcome = SoftTimeLimitExceeded()
        # The fixture replaced the release with a mock: let it run the real one.
        wiring.release.side_effect = _REAL_RELEASE
        result = run_task(str(MODULE_ID), "en", dedup_key=owned)
        assert result["error"] == "time_limit_exceeded"
        assert client.get(owned) is None
        # A key the task does not own (here, another task's) is left alone.
        _REAL_RELEASE(other, TASK_ID)
        assert client.get(other) == "another-task"
    finally:
        client.delete(owned, other)
        client.close()


@pytest.mark.parametrize("left_at_start", ["seconds", "none"])
def test_the_key_covers_the_whole_run_however_long_the_task_was_queued(wiring, left_at_start):
    """Against a real Redis: a queue wait must not come off the run's cover.

    The API claims the key for HARD + 60 s when it dispatches. A task that
    waited in a worker's prefetch buffer behind long tasks finds seconds of
    that left, or none. While it runs the key must name it for longer than its
    hard limit, so a view in the meantime joins it instead of dispatching a
    second, paid, generation of the same chapters.
    """
    client = _redis_or_skip()
    key = story_dispatch_key(MODULE_ID, "en")
    seen: dict[str, Any] = {}

    def look() -> None:
        seen.update(holder=client.get(key), ttl=client.ttl(key))

    FakeModuleStoryService.during = look
    wiring.hold.side_effect = _REAL_HOLD
    wiring.release.side_effect = _REAL_RELEASE
    try:
        if left_at_start == "seconds":
            client.set(key, TASK_ID, ex=2)
        else:
            client.delete(key)  # expired while the task was queued; nobody claimed it
        result = run_task(str(MODULE_ID), "en", dedup_key=key)
        assert result["status"] == "complete"
        assert seen["holder"] == TASK_ID
        assert seen["ttl"] > MODULE_STORY_HARD_LIMIT
        assert client.get(key) is None  # released as the task ended
    finally:
        client.delete(key)
        client.close()


def test_a_key_another_dispatch_holds_is_never_re_armed(wiring):
    """Against a real Redis: the task re-arms only its own key, or a free one."""
    client = _redis_or_skip()
    key = story_dispatch_key(MODULE_ID, "en")
    seen: dict[str, Any] = {}
    FakeModuleStoryService.during = lambda: seen.update(holder=client.get(key), ttl=client.ttl(key))
    wiring.hold.side_effect = _REAL_HOLD
    wiring.release.side_effect = _REAL_RELEASE
    try:
        client.set(key, "another-task", ex=30)
        run_task(str(MODULE_ID), "en", dedup_key=key)
        assert seen["holder"] == "another-task" and 0 < seen["ttl"] <= 30
        assert client.get(key) == "another-task"
    finally:
        client.delete(key)
        client.close()


def test_re_arming_the_key_never_raises():
    with patch("redis.Redis.from_url", side_effect=ConnectionError("redis down")):
        _REAL_HOLD("k", TASK_ID, 60)
    _REAL_HOLD(None, TASK_ID, 60)  # nothing claimed


# --------------------------------------------------------------------------
# End to end: the real task and service, on PostgreSQL and Redis
# --------------------------------------------------------------------------


def _redis_or_skip():
    import redis

    from app.infrastructure.config.settings import settings

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
    try:
        client.ping()
    except redis.RedisError as exc:
        pytest.skip(f"no Redis server: {exc}"[:200])
    return client


def test_end_to_end_a_time_limit_then_a_complete_run(monkeypatch):
    """Soft limit mid-run: packs cancelled, no module written, key released; then it completes."""
    import asyncio

    from app.infrastructure.config.settings import settings
    from tests._story_db import create_tables, scratch_database, story_tables
    from tests.test_story_module_service import (
        FakeLessonService,
        FakeModel,
        FakeQuizService,
        Sessions,
        chapter_rows,
        seed,
    )

    client = _redis_or_skip()
    with scratch_database("story_task") as url:
        create_tables(url, story_tables())

        async def with_sessions(work):
            sessions = Sessions(url)
            try:
                return await work(sessions)
            finally:
                await sessions.engine.dispose()

        async def module_row(sessions, seeded):
            async with sessions.maker() as session:
                return await find_module_story(session, seeded.module_id, "fr")

        seeded = asyncio.run(with_sessions(lambda sessions: seed(sessions)))
        monkeypatch.setattr(settings, "database_url", url)
        key = story_dispatch_key(seeded.module_id, "fr")

        def run_with(model) -> dict:
            client.set(key, TASK_ID, ex=60)
            with (
                patch("app.ai.claude_service.ClaudeService", return_value=model),
                patch("app.ai.rag.embeddings.EmbeddingService"),
                patch("app.ai.rag.retriever.SemanticRetriever"),
                patch(
                    "app.domain.services.lesson_service.LessonGenerationService",
                    return_value=FakeLessonService(),
                ),
                patch(
                    "app.domain.services.quiz_service.QuizService",
                    return_value=FakeQuizService(),
                ),
                patch("app.infrastructure.storage.s3.S3StorageService", return_value=_NoFigures()),
                patch("app.tasks.quality_assessment.assess_and_regenerate_unit_task"),
            ):
                return run_task(str(seeded.module_id), "fr", country="BF", dedup_key=key)

        try:
            slow = FakeModel(delay=0.05)
            slow.broken[("story", "1.1")] = SoftTimeLimitExceeded()
            result = run_with(slow)
            assert result["status"] == "failed" and result["error"] == "time_limit_exceeded"
            assert client.get(key) is None
            assert asyncio.run(with_sessions(lambda s: module_row(s, seeded))) is None
            assert asyncio.run(with_sessions(lambda s: chapter_rows(s, seeded))) == {}

            model = FakeModel()
            result = run_with(model)
            record = asyncio.run(with_sessions(lambda s: module_row(s, seeded)))
            assert result == {
                "status": "complete",
                "content_id": str(record.id),
                "is_valid": True,
            }
            # The plan and every pack were kept from the first run: only the stories now.
            assert model.calls == [
                ("story", "1.1"),
                ("story", "1.2"),
                ("story", "1.3"),
                ("story", "rally"),
            ]
            assert record.status == "published"
            assert client.get(key) is None
        finally:
            client.delete(key)
            client.close()


class _NoFigures:
    async def object_exists(self, key: str) -> bool:
        return False


def test_end_to_end_a_signalled_time_limit_closes_every_session(monkeypatch):
    """The soft limit as Celery delivers it: a signal while the packs await the model.

    The signal lands in the event loop's ``select()``, outside any task, so
    ``asyncio.run``'s teardown cancels every task. The teardown cancels in
    set order; the test puts the packs first. No connection may be checked
    out when the engine is disposed (or stay open in a long-lived worker).
    """
    import asyncio
    import signal
    import threading
    import time

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.infrastructure.config.settings import settings
    from tests._story_db import create_tables, scratch_database, story_tables, sync_engine
    from tests.test_story_module_service import (
        FakeLessonService,
        FakeModel,
        FakeQuizService,
        Sessions,
        seed,
    )

    with scratch_database("story_signal") as url:
        create_tables(url, story_tables())
        database = url.rsplit("/", 1)[1]

        async def with_sessions(work):
            sessions = Sessions(url)
            try:
                return await work(sessions)
            finally:
                await sessions.engine.dispose()

        async def module_row(sessions, seeded):
            async with sessions.maker() as session:
                return await find_module_story(session, seeded.module_id, "fr")

        seeded = asyncio.run(with_sessions(lambda sessions: seed(sessions)))
        monkeypatch.setattr(settings, "database_url", url)

        real_all_tasks = asyncio.tasks.all_tasks

        def packs_first(loop=None):
            found = real_all_tasks(loop)
            return sorted(found, key=lambda t: not t.get_name().startswith("story-pack-"))

        checked_out_at_dispose: list[int] = []
        real_dispose = AsyncEngine.dispose

        async def dispose(self, close=True):
            checked_out_at_dispose.append(self.sync_engine.pool.checkedout())
            return await real_dispose(self, close)

        def soft_timeout_sighandler(signum, frame):  # billiard's, in a prefork child
            raise SoftTimeLimitExceeded()

        model = FakeModel(delay=0.01)
        slow_kinds = {"pack", "story"}
        real_call = model.generate_structured_content

        async def slow(system, user, content_type, max_retries=1):
            if FakeModel.kind_of(user)[0] in slow_kinds:
                model.delay = 30.0
            return await real_call(system, user, content_type, max_retries)

        model.generate_structured_content = slow  # type: ignore[method-assign]
        main_thread = threading.main_thread().ident

        def signal_once_the_packs_wait() -> None:
            deadline = time.monotonic() + 20
            while model.in_flight < 4 and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(0.1)  # the loop is back in select()
            signal.pthread_kill(main_thread, signal.SIGALRM)

        previous = signal.signal(signal.SIGALRM, soft_timeout_sighandler)
        sender = threading.Thread(target=signal_once_the_packs_wait, daemon=True)
        try:
            with (
                patch("app.ai.claude_service.ClaudeService", return_value=model),
                patch("app.ai.rag.embeddings.EmbeddingService"),
                patch("app.ai.rag.retriever.SemanticRetriever"),
                patch(
                    "app.domain.services.lesson_service.LessonGenerationService",
                    return_value=FakeLessonService(),
                ),
                patch(
                    "app.domain.services.quiz_service.QuizService",
                    return_value=FakeQuizService(),
                ),
                patch("app.infrastructure.storage.s3.S3StorageService", return_value=_NoFigures()),
                patch("app.tasks.quality_assessment.assess_and_regenerate_unit_task"),
                patch("asyncio.tasks.all_tasks", packs_first),
                patch.object(AsyncEngine, "dispose", dispose),
            ):
                sender.start()
                result = run_task(str(seeded.module_id), "fr", country="BF", dedup_key=None)
        finally:
            sender.join(timeout=30)
            signal.signal(signal.SIGALRM, previous)

        assert result["status"] == "failed" and result["error"] == "time_limit_exceeded"
        assert len({c for c in model.cancelled if c[0] == "pack"}) >= 4
        assert asyncio.run(with_sessions(lambda s: module_row(s, seeded))) is None
        assert checked_out_at_dispose == [0]
        monitor = sync_engine(url)
        try:
            with monitor.connect() as conn:
                still_open = conn.execute(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": database},
                ).scalar_one()
        finally:
            monitor.dispose()
        assert still_open == 0
