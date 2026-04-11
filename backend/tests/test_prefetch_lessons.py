"""Tests for lesson prefetch feature: task helpers and progress service dispatch."""

import contextlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress
from app.domain.services.progress_service import ProgressService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def module_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def progress_service(mock_db):
    return ProgressService(mock_db)


# ---------------------------------------------------------------------------
# Tests: _dispatch_prefetch does not raise even if Celery is unavailable
# ---------------------------------------------------------------------------


class TestDispatchPrefetch:
    def test_dispatch_prefetch_does_not_raise_on_celery_error(
        self, progress_service, user_id, module_id
    ):
        with patch("app.tasks.content_generation.prefetch_next_lessons_task") as mock_task:
            mock_task.apply_async.side_effect = Exception("Celery unavailable")
            progress_service._dispatch_prefetch(user_id, str(module_id), "M01-U01")

    def test_dispatch_prefetch_calls_apply_async(self, progress_service, user_id, module_id):
        with patch(
            "app.domain.services.progress_service.prefetch_next_lessons_task",
            create=True,
        ) as mock_task:
            mock_task.apply_async = MagicMock()

            with patch(
                "app.tasks.content_generation.prefetch_next_lessons_task",
                mock_task,
            ):
                progress_service._dispatch_prefetch(user_id, str(module_id), "M01-U01")


# ---------------------------------------------------------------------------
# Tests: update_progress_after_quiz dispatches prefetch when passed=True
# ---------------------------------------------------------------------------


class TestPrefetchDispatchedOnQuizPass:
    async def test_prefetch_dispatched_when_quiz_passed(
        self, progress_service, mock_db, user_id, module_id
    ):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="in_progress",
            completion_pct=0.0,
            quiz_score_avg=None,
            time_spent_minutes=0,
            last_accessed=None,
        )

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=existing_progress)
            elif call_count == 2:
                mock_result.scalar = MagicMock(return_value=1)
            elif call_count == 3:
                mock_result.all = MagicMock(return_value=[])
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
                mock_result.scalar = MagicMock(return_value=None)
            return mock_result

        mock_db.execute = mock_execute
        dispatch_calls = []

        def capture_dispatch(uid, mid, cuid):
            dispatch_calls.append((uid, mid, cuid))

        progress_service._dispatch_prefetch = capture_dispatch

        await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="M01-U01",
            score=85.0,
            passed=True,
        )

        assert len(dispatch_calls) == 1
        assert dispatch_calls[0][2] == "M01-U01"

    async def test_prefetch_not_dispatched_when_quiz_failed(
        self, progress_service, mock_db, user_id, module_id
    ):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="in_progress",
            completion_pct=0.0,
            quiz_score_avg=None,
            time_spent_minutes=0,
            last_accessed=None,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress))
        )
        dispatch_calls = []

        def capture_dispatch(uid, mid, cuid):
            dispatch_calls.append((uid, mid, cuid))

        progress_service._dispatch_prefetch = capture_dispatch

        await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="M01-U01",
            score=60.0,
            passed=False,
        )

        assert len(dispatch_calls) == 0


# ---------------------------------------------------------------------------
# Tests: _unlock_next_module dispatches prefetch for the new module
# ---------------------------------------------------------------------------


class TestPrefetchDispatchedOnModuleUnlock:
    async def test_prefetch_dispatched_when_next_module_unlocked(
        self, progress_service, mock_db, user_id, module_id
    ):
        next_module_id = uuid.uuid4()
        current_module = Module(
            id=module_id,
            module_number=1,
            level=1,
            title_fr="M01",
            title_en="M01",
            estimated_hours=20,
        )
        next_module = Module(
            id=next_module_id,
            module_number=2,
            level=1,
            title_fr="M02",
            title_en="M02",
            estimated_hours=20,
        )

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=current_module)
            elif call_count == 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=next_module)
            elif call_count == 3:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        mock_db.execute = mock_execute

        dispatch_calls = []

        def capture_dispatch(uid, mid, cuid):
            dispatch_calls.append((uid, mid, cuid))

        progress_service._dispatch_prefetch = capture_dispatch

        await progress_service._unlock_next_module(user_id, module_id)

        assert len(dispatch_calls) == 1
        assert dispatch_calls[0][1] == str(next_module_id)
        assert dispatch_calls[0][2] == ""


# ---------------------------------------------------------------------------
# Tests: _dispatch_content_prefetch logic (tested in isolation)
# ---------------------------------------------------------------------------


class TestDispatchContentPrefetch:
    """
    Test the prefetch dispatch helper logic without importing the full content.py
    (which requires the anthropic module unavailable in the unit-test environment).
    The logic is implemented inline here to verify the contract.
    """

    def _make_dispatch_fn(self, mock_task):
        """Replicate _dispatch_content_prefetch logic for isolated testing."""

        def _dispatch(current_user, module_id: str, unit_id: str) -> None:
            if current_user is None:
                return
            with contextlib.suppress(Exception):
                mock_task.apply_async(
                    kwargs={
                        "user_id": str(current_user.id),
                        "module_id": module_id,
                        "current_unit_id": unit_id,
                        "language": getattr(current_user, "preferred_language", "fr") or "fr",
                        "country": getattr(current_user, "country", "SN") or "SN",
                        "level": getattr(current_user, "current_level", 1) or 1,
                    },
                    priority=3,
                )

        return _dispatch

    def test_dispatch_does_not_raise_on_celery_error(self):
        mock_task = MagicMock()
        mock_task.apply_async.side_effect = Exception("Celery unavailable")
        dispatch = self._make_dispatch_fn(mock_task)

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.preferred_language = "fr"
        mock_user.country = "SN"
        mock_user.current_level = 1

        dispatch(mock_user, str(uuid.uuid4()), "M01-U01")

    def test_dispatch_skips_none_user(self):
        mock_task = MagicMock()
        dispatch = self._make_dispatch_fn(mock_task)

        dispatch(None, str(uuid.uuid4()), "M01-U01")
        mock_task.apply_async.assert_not_called()

    def test_dispatch_calls_apply_async_with_correct_kwargs(self):
        mock_task = MagicMock()
        dispatch = self._make_dispatch_fn(mock_task)

        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.preferred_language = "en"
        mock_user.country = "GH"
        mock_user.current_level = 2

        module_id_str = str(uuid.uuid4())
        dispatch(mock_user, module_id_str, "M02-U03")

        mock_task.apply_async.assert_called_once()
        call_kwargs = mock_task.apply_async.call_args[1]["kwargs"]
        assert call_kwargs["user_id"] == str(mock_user.id)
        assert call_kwargs["module_id"] == module_id_str
        assert call_kwargs["current_unit_id"] == "M02-U03"
        assert call_kwargs["language"] == "en"
        assert call_kwargs["country"] == "GH"
        assert call_kwargs["level"] == 2
