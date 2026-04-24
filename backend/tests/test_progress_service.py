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
            unit_id="1.1",
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
            unit_id="1.1",
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
            unit_id="1.2",
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
            unit_id="1.1",
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


class TestCheckQuizPassedForUnit:
    async def test_returns_false_when_no_quiz_content_found(
        self, progress_service, mock_db, user_id, module_id
    ):
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        result = await progress_service.check_quiz_passed_for_unit(
            user_id=user_id,
            module_id=module_id,
            unit_id="1.1",
        )

        assert result is False

    async def test_returns_false_when_no_passing_attempt(
        self, progress_service, mock_db, user_id, module_id
    ):
        quiz_id = uuid.uuid4()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.all = MagicMock(return_value=[(quiz_id,)])
            else:
                mock_result.scalar = MagicMock(return_value=70.0)
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.check_quiz_passed_for_unit(
            user_id=user_id,
            module_id=module_id,
            unit_id="1.1",
        )

        assert result is False

    async def test_returns_true_when_passing_attempt_exists(
        self, progress_service, mock_db, user_id, module_id
    ):
        quiz_id = uuid.uuid4()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.all = MagicMock(return_value=[(quiz_id,)])
            else:
                mock_result.scalar = MagicMock(return_value=85.0)
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.check_quiz_passed_for_unit(
            user_id=user_id,
            module_id=module_id,
            unit_id="1.1",
        )

        assert result is True

    async def test_returns_true_exactly_at_80_threshold(
        self, progress_service, mock_db, user_id, module_id
    ):
        quiz_id = uuid.uuid4()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.all = MagicMock(return_value=[(quiz_id,)])
            else:
                mock_result.scalar = MagicMock(return_value=80.0)
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.check_quiz_passed_for_unit(
            user_id=user_id,
            module_id=module_id,
            unit_id="1.1",
        )

        assert result is True

    async def test_returns_false_when_no_attempt_at_all(
        self, progress_service, mock_db, user_id, module_id
    ):
        quiz_id = uuid.uuid4()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.all = MagicMock(return_value=[(quiz_id,)])
            else:
                mock_result.scalar = MagicMock(return_value=None)
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.check_quiz_passed_for_unit(
            user_id=user_id,
            module_id=module_id,
            unit_id="1.1",
        )

        assert result is False


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


class TestUnlockNextModule:
    async def test_unlock_threshold_triggers_next_module_unlock(
        self, progress_service, mock_db, user_id, module_id
    ):
        from app.domain.models.module import Module

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
        existing_progress = UserModuleProgress(
            user_id=user_id,
            module_id=module_id,
            status="in_progress",
            completion_pct=0.0,
            quiz_score_avg=None,
            time_spent_minutes=0,
            last_accessed=None,
        )
        added_objects = []

        def capture_add(obj):
            added_objects.append(obj)

        mock_db.add = MagicMock(side_effect=capture_add)

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # _get_or_create_progress
                mock_result.scalar_one_or_none = MagicMock(return_value=existing_progress)
            elif call_count == 2:
                # _calculate_completion_pct: total units
                mock_result.scalar = MagicMock(return_value=1)
            elif call_count == 3:
                # _get_completed_units: quiz contents
                mock_result.all = MagicMock(return_value=[])
            elif call_count == 4:
                # _unlock_next_module: current module lookup
                mock_result.scalar_one_or_none = MagicMock(return_value=current_module)
            elif call_count == 5:
                # _unlock_next_module: next module lookup
                mock_result.scalar_one_or_none = MagicMock(return_value=next_module)
            elif call_count == 6:
                # _unlock_next_module: check existing progress for next module
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
                mock_result.scalar = MagicMock(return_value=None)
                mock_result.all = MagicMock(return_value=[])
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="1.1",
            score=90.0,
            passed=True,
        )

        assert result.quiz_score_avg == 90.0
        assert result.completion_pct == 100.0
        assert result.status == "completed"

        unlocked = [
            obj
            for obj in added_objects
            if isinstance(obj, UserModuleProgress) and obj.module_id == next_module_id
        ]
        assert len(unlocked) == 1
        assert unlocked[0].status == "in_progress"

    async def test_no_unlock_when_score_below_threshold(
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
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
                mock_result.scalar = MagicMock(return_value=None)
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="1.1",
            score=70.0,
            passed=False,
        )

        assert result.quiz_score_avg == 70.0
        # No unlock should happen — execute called for get_or_create_progress,
        # touch_course_interaction_by_module (select Module.course_id),
        # and rollup_course_completion_by_module (also select Module.course_id).
        assert call_count == 3

    async def test_unlock_updates_existing_locked_next_module(
        self, progress_service, mock_db, user_id, module_id
    ):
        from app.domain.models.module import Module

        next_module_id = uuid.uuid4()
        current_module = Module(
            id=module_id,
            module_number=3,
            level=1,
            title_fr="M03",
            title_en="M03",
            estimated_hours=20,
        )
        next_module = Module(
            id=next_module_id,
            module_number=4,
            level=2,
            title_fr="M04",
            title_en="M04",
            estimated_hours=25,
        )
        locked_next_progress = UserModuleProgress(
            user_id=user_id,
            module_id=next_module_id,
            status="locked",
            completion_pct=0.0,
            quiz_score_avg=None,
            time_spent_minutes=0,
            last_accessed=None,
        )
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
            elif call_count == 4:
                mock_result.scalar_one_or_none = MagicMock(return_value=current_module)
            elif call_count == 5:
                mock_result.scalar_one_or_none = MagicMock(return_value=next_module)
            elif call_count == 6:
                mock_result.scalar_one_or_none = MagicMock(return_value=locked_next_progress)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        mock_db.execute = mock_execute

        await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="3.1",
            score=85.0,
            passed=True,
        )

        assert locked_next_progress.status == "in_progress"

    async def test_no_unlock_when_no_next_module(
        self, progress_service, mock_db, user_id, module_id
    ):
        from app.domain.models.module import Module

        last_module = Module(
            id=module_id,
            module_number=15,
            level=4,
            title_fr="M15",
            title_en="M15",
            estimated_hours=20,
        )
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
            elif call_count == 4:
                mock_result.scalar_one_or_none = MagicMock(return_value=last_module)
            elif call_count == 5:
                # No next module
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        mock_db.execute = mock_execute
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        await progress_service.update_progress_after_quiz(
            user_id=user_id,
            module_id=module_id,
            unit_id="M15-U01",
            score=90.0,
            passed=True,
        )

        new_progress_rows = [
            obj
            for obj in added_objects
            if isinstance(obj, UserModuleProgress) and obj.module_id != module_id
        ]
        assert len(new_progress_rows) == 0


class TestGetAllModulesWithProgress:
    async def test_returns_all_modules_when_no_course_id(self, progress_service, mock_db, user_id):
        from app.domain.models.module import Module

        course_id = uuid.uuid4()
        module1 = Module(
            id=uuid.uuid4(),
            module_number=1,
            level=1,
            title_fr="M01 FR",
            title_en="M01 EN",
            estimated_hours=20,
            course_id=course_id,
        )
        module2 = Module(
            id=uuid.uuid4(),
            module_number=2,
            level=1,
            title_fr="M02 FR",
            title_en="M02 EN",
            estimated_hours=25,
            course_id=uuid.uuid4(),
        )

        call_count = 0
        executed_stmts = []

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            executed_stmts.append(stmt)
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalars.return_value.all.return_value = [module1, module2]
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.get_all_modules_with_progress(user_id)

        assert len(result) == 2
        assert result[0]["module_number"] == 1
        assert result[1]["module_number"] == 2

    async def test_filters_by_course_id_when_provided(self, progress_service, mock_db, user_id):
        from app.domain.models.module import Module

        target_course_id = uuid.uuid4()
        module_in_course = Module(
            id=uuid.uuid4(),
            module_number=1,
            level=1,
            title_fr="M01 FR",
            title_en="M01 EN",
            estimated_hours=20,
            course_id=target_course_id,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalars.return_value.all.return_value = [module_in_course]
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.get_all_modules_with_progress(
            user_id, course_id=target_course_id
        )

        assert len(result) == 1
        assert result[0]["module_number"] == 1

    async def test_defaults_status_to_locked_when_no_progress(
        self, progress_service, mock_db, user_id
    ):
        from app.domain.models.module import Module

        module = Module(
            id=uuid.uuid4(),
            module_number=1,
            level=1,
            title_fr="M01 FR",
            title_en="M01 EN",
            estimated_hours=20,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalars.return_value.all.return_value = [module]
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.get_all_modules_with_progress(user_id)

        assert len(result) == 1
        assert result[0]["status"] == "locked"
        assert result[0]["completion_pct"] == 0.0

    async def test_returns_empty_list_when_course_has_no_modules(
        self, progress_service, mock_db, user_id
    ):
        course_id = uuid.uuid4()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalars.return_value.all.return_value = []
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mock_db.execute = mock_execute

        result = await progress_service.get_all_modules_with_progress(user_id, course_id=course_id)

        assert result == []
