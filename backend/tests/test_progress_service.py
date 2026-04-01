"""Tests for the progress tracking service."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.lesson_reading import LessonReading
from app.domain.models.progress import UserModuleProgress
from app.domain.services.progress_service import ProgressService


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def module_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def lesson_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_db():
    """Mock async database session."""
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def progress_service(mock_db):
    return ProgressService(mock_db)


class TestTrackLessonAccess:
    async def test_creates_lesson_reading_record(
        self, progress_service, mock_db, user_id, module_id, lesson_id
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
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress)),
            ]
        )

        await progress_service.track_lesson_access(
            user_id=user_id,
            module_id=module_id,
            lesson_id=lesson_id,
            time_spent_seconds=120,
            reading_completion_pct=50.0,
        )

        assert mock_db.add.call_count == 1
        added_obj = mock_db.add.call_args[0][0]
        assert isinstance(added_obj, LessonReading)
        assert added_obj.user_id == user_id
        assert added_obj.lesson_id == lesson_id
        assert added_obj.time_spent_seconds == 120
        assert added_obj.completion_percentage == 50.0

    async def test_marks_locked_module_as_in_progress(
        self, progress_service, mock_db, user_id, module_id, lesson_id
    ):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="locked",
            completion_pct=0.0,
            quiz_score_avg=None,
            time_spent_minutes=0,
            last_accessed=None,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress))
        )

        result = await progress_service.track_lesson_access(
            user_id=user_id,
            module_id=module_id,
            lesson_id=lesson_id,
        )

        assert result.status == "in_progress"

    async def test_does_not_downgrade_completed_module(
        self, progress_service, mock_db, user_id, module_id, lesson_id
    ):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="completed",
            completion_pct=100.0,
            quiz_score_avg=90.0,
            time_spent_minutes=120,
            last_accessed=None,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress))
        )

        result = await progress_service.track_lesson_access(
            user_id=user_id,
            module_id=module_id,
            lesson_id=lesson_id,
        )

        assert result.status == "completed"

    async def test_accumulates_time_spent(
        self, progress_service, mock_db, user_id, module_id, lesson_id
    ):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="in_progress",
            completion_pct=20.0,
            quiz_score_avg=None,
            time_spent_minutes=30,
            last_accessed=None,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress))
        )

        result = await progress_service.track_lesson_access(
            user_id=user_id,
            module_id=module_id,
            lesson_id=lesson_id,
            time_spent_seconds=600,
        )

        assert result.time_spent_minutes == 40

    async def test_creates_new_progress_if_not_exists(
        self, progress_service, mock_db, user_id, module_id, lesson_id
    ):
        new_progress = UserModuleProgress(
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
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=new_progress)
            return mock_result

        mock_db.execute = mock_execute

        def capture_add(obj):
            if isinstance(obj, UserModuleProgress):
                new_progress.status = obj.status

        mock_db.add = MagicMock(side_effect=capture_add)

        await progress_service.track_lesson_access(
            user_id=user_id,
            module_id=module_id,
            lesson_id=lesson_id,
        )

        assert mock_db.commit.called


class TestUpdateProgressAfterQuiz:
    async def test_updates_quiz_score_avg_on_fail(
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

        result = await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="M01-U01",
            score=60.0,
            passed=False,
        )

        assert result.quiz_score_avg == 60.0
        assert result.status == "in_progress"

    async def test_sets_first_quiz_score_directly(
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

        result = await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="M01-U01",
            score=85.0,
            passed=False,
        )

        assert result.quiz_score_avg == 85.0

    async def test_averages_multiple_quiz_scores(
        self, progress_service, mock_db, user_id, module_id
    ):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="in_progress",
            completion_pct=0.0,
            quiz_score_avg=70.0,
            time_spent_minutes=0,
            last_accessed=None,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress))
        )

        result = await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="M01-U02",
            score=90.0,
            passed=False,
        )

        assert result.quiz_score_avg == 80.0

    async def test_does_not_update_completion_pct_on_fail(
        self, progress_service, mock_db, user_id, module_id
    ):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="in_progress",
            completion_pct=20.0,
            quiz_score_avg=None,
            time_spent_minutes=0,
            last_accessed=None,
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress))
        )

        result = await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="M01-U01",
            score=50.0,
            passed=False,
        )

        assert result.completion_pct == 20.0


class TestGetModuleProgress:
    async def test_returns_none_when_not_found(self, progress_service, mock_db, user_id, module_id):
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        result = await progress_service.get_module_progress(user_id, module_id)

        assert result is None

    async def test_returns_existing_progress(self, progress_service, mock_db, user_id, module_id):
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="in_progress",
            completion_pct=45.0,
            quiz_score_avg=78.5,
            time_spent_minutes=60,
            last_accessed=datetime.now(UTC),
        )
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_progress))
        )

        result = await progress_service.get_module_progress(user_id, module_id)

        assert result is not None
        assert result.status == "in_progress"
        assert result.completion_pct == 45.0
        assert result.quiz_score_avg == 78.5

    async def test_returns_all_module_progress(self, progress_service, mock_db, user_id):
        module1_id = uuid.uuid4()
        module2_id = uuid.uuid4()
        progress_list = [
            UserModuleProgress(
                user_id=user_id,
                module_id=module1_id,
                status="completed",
                completion_pct=100.0,
                quiz_score_avg=88.0,
                time_spent_minutes=120,
                last_accessed=None,
            ),
            UserModuleProgress(
                user_id=user_id,
                module_id=module2_id,
                status="in_progress",
                completion_pct=35.0,
                quiz_score_avg=None,
                time_spent_minutes=30,
                last_accessed=None,
            ),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = progress_list
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await progress_service.get_all_module_progress(user_id)

        assert len(result) == 2
        statuses = [p.status for p in result]
        assert "completed" in statuses
        assert "in_progress" in statuses


class TestUnitNumberToUnitId:
    def test_converts_basic_format(self):
        assert ProgressService._unit_number_to_unit_id("1.1", 1) == "M01-U01"

    def test_converts_with_padding(self):
        assert ProgressService._unit_number_to_unit_id("1.2", 1) == "M01-U02"

    def test_converts_module_number_padded(self):
        assert ProgressService._unit_number_to_unit_id("12.3", 12) == "M12-U03"

    def test_converts_high_unit_ordinal(self):
        assert ProgressService._unit_number_to_unit_id("3.10", 3) == "M03-U10"

    def test_returns_input_on_invalid_format(self):
        assert ProgressService._unit_number_to_unit_id("bad", 1) == "bad"

    def test_returns_input_on_single_part(self):
        assert ProgressService._unit_number_to_unit_id("M01-U01", 1) == "M01-U01"

    def test_roundtrip_with_lesson_service(self):
        from app.domain.services.lesson_service import LessonGenerationService

        unit_id = "M01-U03"
        module_number = 1
        unit_number = LessonGenerationService._unit_id_to_unit_number(unit_id, module_number)
        assert unit_number is not None
        result = ProgressService._unit_number_to_unit_id(unit_number, module_number)
        assert result == unit_id


class TestProgressServiceIntegration:
    async def test_tracking_lesson_updates_last_accessed(
        self, progress_service, mock_db, user_id, module_id, lesson_id
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

        result = await progress_service.track_lesson_access(
            user_id=user_id,
            module_id=module_id,
            lesson_id=lesson_id,
        )

        assert result.last_accessed is not None
