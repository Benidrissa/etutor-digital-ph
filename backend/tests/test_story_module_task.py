"""The Celery task that makes a module story: its budget, wiring and results.

The task runs for real (``asyncio.run`` included) with the services it builds
replaced by fakes: no database, no model, no provider client. Releasing the
API's dedup key is checked against a real Redis when one is reachable.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.ai.usage_context import current_ai_context
from app.domain.services.story_module_service import ChapterGenerationFailed, story_dispatch_key
from app.tasks import content_generation
from app.tasks.content_generation import (
    MODULE_STORY_HARD_LIMIT,
    MODULE_STORY_SOFT_LIMIT,
    POLL_SOFT_LIMIT,
    generate_module_story_task,
)

MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")
#: The real compare-and-delete, taken before any test replaces it.
_REAL_RELEASE = content_generation._release_story_dispatch
STORY_ID = uuid.UUID(int=99)
TASK_ID = "task-42"


def test_the_task_is_declared_with_its_budget_and_no_retry():
    from app.domain.services.story_from_lesson_service import MAX_REPAIR_CALLS
    from app.tasks.celery_app import celery_app

    task = generate_module_story_task
    assert task.name == "app.tasks.content_generation.generate_module_story_task"
    assert (MODULE_STORY_SOFT_LIMIT, MODULE_STORY_HARD_LIMIT) == (1200, 1260)
    assert task.soft_time_limit == MODULE_STORY_SOFT_LIMIT
    assert task.time_limit == MODULE_STORY_HARD_LIMIT
    assert task.rate_limit == "5/m"
    assert not getattr(task, "autoretry_for", ())
    # A chapter's slowest path: its lesson, the covering quiz, then every spine call.
    assert MODULE_STORY_SOFT_LIMIT >= 2 * POLL_SOFT_LIMIT + (1 + MAX_REPAIR_CALLS) * 150
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

    def __init__(self, claude_service, lesson_service, quiz_service, **kwargs) -> None:
        self.args = (claude_service, lesson_service, quiz_service)
        self.kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        FakeModuleStoryService.instances.append(self)

    async def get_or_generate_module_story(
        self, module_id, language, session_factory, *, level, country, force_regenerate
    ):
        self.calls.append(
            {
                "module_id": module_id,
                "language": language,
                "session_factory": session_factory,
                "level": level,
                "country": country,
                "force_regenerate": force_regenerate,
                "feature": current_ai_context().feature,
            }
        )
        outcome = FakeModuleStoryService.outcome
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture
def wiring():
    """Every collaborator the task builds, replaced; yields what the test inspects."""
    FakeModuleStoryService.instances = []
    FakeModuleStoryService.outcome = SimpleNamespace(id=STORY_ID, is_valid=True)
    engine = MagicMock()
    engine.dispose = AsyncMock()
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
    wiring.release.assert_called_once_with(key, TASK_ID)


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
    """Soft limit mid-run: chapters cancelled, nothing written, key released; then it completes."""
    import asyncio
    import json
    from pathlib import Path

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.infrastructure.config.settings import settings
    from tests._story_db import create_tables, scratch_database, story_tables
    from tests.test_story_module_service import (
        LESSONS,
        FakeClaude,
        FakeLessonService,
        FakeQuizService,
        Sessions,
        chapter_rows,
        module_row,
        seed,
    )

    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "lesson_story_unit.json").read_text("utf-8")
    )
    client = _redis_or_skip()
    with scratch_database("story_task") as url:
        create_tables(url, story_tables())

        async def with_sessions(work):
            engine = create_async_engine(url)
            try:
                return await work(Sessions(engine))
            finally:
                await engine.dispose()

        seeded = asyncio.run(with_sessions(lambda sessions: seed(sessions, raw)))
        monkeypatch.setattr(settings, "database_url", url)
        key = story_dispatch_key(seeded.module_id, "en")

        def run_with(model: FakeClaude) -> dict:
            client.set(key, TASK_ID, ex=60)
            with (
                patch("app.ai.claude_service.ClaudeService", return_value=model),
                patch("app.ai.rag.embeddings.EmbeddingService"),
                patch("app.ai.rag.retriever.SemanticRetriever"),
                patch(
                    "app.domain.services.lesson_service.LessonGenerationService",
                    return_value=FakeLessonService(raw),
                ),
                patch(
                    "app.domain.services.quiz_service.QuizService",
                    return_value=FakeQuizService(raw),
                ),
                patch("app.tasks.quality_assessment.assess_and_regenerate_unit_task"),
            ):
                return run_task(str(seeded.module_id), "en", dedup_key=key)

        try:
            slow = FakeClaude(raw, "en", delay=30.0, soft_limit_on_call=2)
            result = run_with(slow)
            assert result["status"] == "failed" and result["error"] == "time_limit_exceeded"
            assert len(slow.cancelled) == 3
            assert client.get(key) is None
            assert asyncio.run(with_sessions(lambda s: module_row(s, seeded))) is None
            # The lessons generated before the limit are cached; no chapter is.
            assert asyncio.run(with_sessions(lambda s: chapter_rows(s, seeded))) == {}

            model = FakeClaude(raw, "en")
            result = run_with(model)
            record = asyncio.run(with_sessions(lambda s: module_row(s, seeded)))
            assert result == {
                "status": "complete",
                "content_id": str(record.id),
                "is_valid": True,
            }
            assert sorted(model.calls) == LESSONS
            assert record.status == "published"
            assert client.get(key) is None
        finally:
            client.delete(key)
            client.close()


def test_end_to_end_a_signalled_time_limit_closes_every_chapter_session(monkeypatch):
    """The soft limit as Celery delivers it: a signal while every chapter awaits the model.

    The signal lands in the event loop's ``select()``, outside any task, so
    ``asyncio.run``'s teardown cancels every task, and the main task's
    TaskGroup then cancels the chapters a second time. A chapter already in
    its session's ``__aexit__`` ends on that second cancel while the shielded
    close task still holds its connection. The teardown cancels in set order;
    the test puts the chapters first, the order that left those connections
    checked out when the engine was disposed (and open in a long-lived worker).
    """
    import asyncio
    import json
    import signal
    import threading
    import time
    from pathlib import Path

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

    from app.infrastructure.config.settings import settings
    from tests._story_db import create_tables, scratch_database, story_tables, sync_engine
    from tests.test_story_module_service import (
        LESSONS,
        FakeClaude,
        FakeLessonService,
        FakeQuizService,
        Sessions,
        module_row,
        seed,
    )

    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "lesson_story_unit.json").read_text("utf-8")
    )
    with scratch_database("story_signal") as url:
        create_tables(url, story_tables())
        database = url.rsplit("/", 1)[1]

        async def with_sessions(work):
            engine = create_async_engine(url)
            try:
                return await work(Sessions(engine))
            finally:
                await engine.dispose()

        seeded = asyncio.run(with_sessions(lambda sessions: seed(sessions, raw)))
        monkeypatch.setattr(settings, "database_url", url)

        real_all_tasks = asyncio.tasks.all_tasks

        def chapters_first(loop=None):
            found = real_all_tasks(loop)
            return sorted(found, key=lambda t: not t.get_name().startswith("story-chapter-"))

        checked_out_at_dispose: list[int] = []
        real_dispose = AsyncEngine.dispose

        async def dispose(self, close=True):
            checked_out_at_dispose.append(self.sync_engine.pool.checkedout())
            return await real_dispose(self, close)

        def soft_timeout_sighandler(signum, frame):  # billiard's, in a prefork child
            raise SoftTimeLimitExceeded()

        model = FakeClaude(raw, "en", delay=30.0)
        main_thread = threading.main_thread().ident

        def signal_once_every_chapter_waits() -> None:
            deadline = time.monotonic() + 20
            while model.in_flight < len(LESSONS) and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(0.1)  # the loop is back in select()
            signal.pthread_kill(main_thread, signal.SIGALRM)

        previous = signal.signal(signal.SIGALRM, soft_timeout_sighandler)
        sender = threading.Thread(target=signal_once_every_chapter_waits, daemon=True)
        try:
            with (
                patch("app.ai.claude_service.ClaudeService", return_value=model),
                patch("app.ai.rag.embeddings.EmbeddingService"),
                patch("app.ai.rag.retriever.SemanticRetriever"),
                patch(
                    "app.domain.services.lesson_service.LessonGenerationService",
                    return_value=FakeLessonService(raw),
                ),
                patch(
                    "app.domain.services.quiz_service.QuizService",
                    return_value=FakeQuizService(raw),
                ),
                patch("app.tasks.quality_assessment.assess_and_regenerate_unit_task"),
                patch("asyncio.tasks.all_tasks", chapters_first),
                patch.object(AsyncEngine, "dispose", dispose),
            ):
                sender.start()
                result = run_task(str(seeded.module_id), "en", dedup_key=None)
        finally:
            sender.join(timeout=30)
            signal.signal(signal.SIGALRM, previous)

        assert result["status"] == "failed" and result["error"] == "time_limit_exceeded"
        assert sorted(model.cancelled) == LESSONS  # every chapter was waiting on the model
        assert asyncio.run(with_sessions(lambda s: module_row(s, seeded))) is None
        # Every chapter session was closed before the engine went away...
        assert checked_out_at_dispose == [0]
        # ...so no connection outlives the task (no garbage collection needed).
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
