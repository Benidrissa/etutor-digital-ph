"""Progress tracking service — tracks lesson access and module completion."""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.lesson_reading import LessonReading
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.progress import UserModuleProgress
from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger()


def _unlock_pct():
    return SettingsCache.instance().get("progress-unlock-threshold-pct", 80.0)


def _unlock_score():
    return SettingsCache.instance().get("progress-unlock-threshold-score", 80.0)


def _unit_pass_score():
    return SettingsCache.instance().get("progress-unit-pass-score", 80.0)


class ProgressService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _unit_number_to_unit_id(unit_number: str, module_number: int) -> str:
        """Convert unit_number like '1.2' to unit_id like 'M01-U02'."""
        try:
            parts = unit_number.split(".")
            if len(parts) != 2:
                return unit_number
            unit_ordinal = int(parts[1])
            return f"M{module_number:02d}-U{unit_ordinal:02d}"
        except (ValueError, IndexError):
            return unit_number

    async def track_lesson_access(
        self,
        user_id: UUID,
        module_id: UUID,
        lesson_id: UUID,
        time_spent_seconds: int = 0,
        reading_completion_pct: float = 0.0,
    ) -> UserModuleProgress:
        """
        Record that a user accessed a lesson and update module progress.

        Marks the module as in_progress if not already completed.
        Creates a lesson_reading record for streak and time tracking.
        """
        now = datetime.utcnow()

        # Upsert lesson reading record
        reading = LessonReading(
            id=uuid.uuid4(),
            user_id=user_id,
            lesson_id=lesson_id,
            time_spent_seconds=time_spent_seconds,
            completion_percentage=reading_completion_pct,
            read_at=now,
        )
        self.db.add(reading)

        # Get or create progress entry
        progress = await self._get_or_create_progress(user_id, module_id, now)

        # Only move to in_progress if currently locked/not started; preserve completed
        if progress.status == "locked":
            progress.status = "in_progress"

        progress.last_accessed = now
        progress.time_spent_minutes = (progress.time_spent_minutes or 0) + max(
            0, time_spent_seconds // 60
        )

        await self.db.commit()
        await self.db.refresh(progress)

        logger.info(
            "Lesson access tracked",
            user_id=str(user_id),
            module_id=str(module_id),
            lesson_id=str(lesson_id),
            progress_status=progress.status,
        )
        return progress

    async def update_progress_after_quiz(
        self,
        user_id: UUID,
        module_id: UUID,
        unit_id: str,
        score: float,
        passed: bool,
    ) -> UserModuleProgress:
        """
        Update module progress after a formative quiz attempt.

        Per FR-02.2: lesson completion requires passing the validation quiz (≥80%).
        Recalculates module completion_pct based on completed units.
        When completion_pct >= 80 AND quiz_score_avg >= 80, marks module completed
        and unlocks the next module (N+1).
        """
        now = datetime.utcnow()

        progress = await self._get_or_create_progress(user_id, module_id, now)
        progress.last_accessed = now

        # Update rolling quiz score average
        if progress.quiz_score_avg is None:
            progress.quiz_score_avg = score
        else:
            progress.quiz_score_avg = (progress.quiz_score_avg + score) / 2.0

        if passed:
            # Recalculate completion percentage based on units
            new_pct = await self._calculate_completion_pct(
                user_id=user_id,
                module_id=module_id,
                just_completed_unit_id=unit_id,
                current_progress=progress,
            )
            progress.completion_pct = new_pct

            if new_pct >= 100.0:
                progress.status = "completed"
            elif progress.status == "locked":
                progress.status = "in_progress"

        await self.db.commit()
        await self.db.refresh(progress)

        # After commit, check whether N+1 unlock conditions are met
        if (
            progress.completion_pct >= _unlock_pct()
            and progress.quiz_score_avg is not None
            and progress.quiz_score_avg >= _unlock_score()
        ):
            await self._unlock_next_module(user_id, module_id)

        # Prefetch next 2 lessons in background if quiz was passed
        if passed:
            await self._dispatch_prefetch_after_quiz(user_id, module_id, unit_id)

        logger.info(
            "Progress updated after quiz",
            user_id=str(user_id),
            module_id=str(module_id),
            unit_id=unit_id,
            score=score,
            passed=passed,
            new_completion_pct=progress.completion_pct,
            status=progress.status,
        )
        return progress

    async def check_quiz_passed_for_unit(
        self,
        user_id: UUID,
        module_id: UUID,
        unit_id: str,
    ) -> bool:
        """
        Return True if the user has at least one quiz attempt with score ≥ 80
        for the given module + unit combination.

        Per FR-02.2: lesson completion requires passing the validation quiz (≥80%).
        """
        from app.domain.models.content import GeneratedContent
        from app.domain.models.quiz import QuizAttempt

        content_result = await self.db.execute(
            select(GeneratedContent.id).where(
                GeneratedContent.module_id == module_id,
                GeneratedContent.content_type == "quiz",
                GeneratedContent.content["unit_id"].astext == unit_id,
            )
        )
        quiz_ids = [row[0] for row in content_result.all()]

        if not quiz_ids:
            return False

        attempt_result = await self.db.execute(
            select(func.max(QuizAttempt.score)).where(
                QuizAttempt.user_id == user_id,
                QuizAttempt.quiz_id.in_(quiz_ids),
            )
        )
        max_score = attempt_result.scalar()
        return max_score is not None and max_score >= _unlock_score()

    async def get_module_progress(
        self, user_id: UUID, module_id: UUID
    ) -> UserModuleProgress | None:
        """Retrieve progress for a specific module."""
        result = await self.db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id == user_id,
                UserModuleProgress.module_id == module_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_module_progress(self, user_id: UUID) -> list[UserModuleProgress]:
        """Retrieve progress for all modules for a user."""
        result = await self.db.execute(
            select(UserModuleProgress).where(UserModuleProgress.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_all_modules_with_progress(
        self, user_id: UUID, course_id: UUID | None = None
    ) -> list[dict]:
        """
        Return modules with their real lock/unlock status for the user.

        When course_id is provided, only modules belonging to that course are returned.
        Modules without a progress record default to 'locked'.
        Returns data ordered by module_number.
        """
        stmt = select(Module).order_by(Module.module_number)
        if course_id is not None:
            stmt = stmt.where(Module.course_id == course_id)
        modules_result = await self.db.execute(stmt)
        modules = list(modules_result.scalars().all())

        progress_result = await self.db.execute(
            select(UserModuleProgress).where(UserModuleProgress.user_id == user_id)
        )
        progress_map: dict[uuid.UUID, UserModuleProgress] = {
            p.module_id: p for p in progress_result.scalars().all()
        }

        result = []
        for module in modules:
            progress = progress_map.get(module.id)
            result.append(
                {
                    "module_id": module.id,
                    "module_number": module.module_number,
                    "title_fr": module.title_fr,
                    "title_en": module.title_en,
                    "description_fr": module.description_fr,
                    "description_en": module.description_en,
                    "level": module.level,
                    "estimated_hours": module.estimated_hours,
                    "user_id": user_id,
                    "status": progress.status if progress else "locked",
                    "completion_pct": progress.completion_pct if progress else 0.0,
                    "quiz_score_avg": progress.quiz_score_avg if progress else None,
                    "time_spent_minutes": progress.time_spent_minutes if progress else 0,
                    "last_accessed": (
                        progress.last_accessed.isoformat()
                        if progress and progress.last_accessed
                        else None
                    ),
                }
            )
        return result

    async def get_module_with_progress(self, user_id: UUID, module_id: UUID) -> dict:
        """
        Return module detail with units and per-unit completion status,
        merging DB data with progress records.
        """
        module_result = await self.db.execute(select(Module).where(Module.id == module_id))
        module = module_result.scalar_one_or_none()
        if not module:
            raise ValueError(f"Module {module_id} not found")

        progress = await self.get_module_progress(user_id, module_id)

        units_result = await self.db.execute(
            select(ModuleUnit)
            .where(ModuleUnit.module_id == module_id)
            .order_by(ModuleUnit.order_index)
        )
        units = list(units_result.scalars().all())

        completed_units = await self._get_completed_units(user_id, module_id)

        units_data = []
        for unit in units:
            unit_id = self._unit_number_to_unit_id(unit.unit_number, module.module_number)
            unit_status = "pending"
            if unit.unit_number in completed_units or unit_id in completed_units:
                unit_status = "completed"
            elif (
                progress
                and progress.status in ("in_progress", "completed")
                and not any(u["status"] == "in_progress" for u in units_data)
            ):
                unit_status = "in_progress"

            units_data.append(
                {
                    "id": unit_id,
                    "unit_number": unit_id,
                    "title_fr": unit.title_fr,
                    "title_en": unit.title_en,
                    "description_fr": unit.description_fr,
                    "description_en": unit.description_en,
                    "estimated_minutes": unit.estimated_minutes,
                    "order_index": unit.order_index,
                    "unit_type": unit.unit_type,
                    "status": unit_status,
                }
            )

        return {
            "id": str(module.id),
            "module_number": module.module_number,
            "level": module.level,
            "title_fr": module.title_fr,
            "title_en": module.title_en,
            "description_fr": module.description_fr,
            "description_en": module.description_en,
            "estimated_hours": module.estimated_hours,
            "prereq_modules": [str(p) for p in (module.prereq_modules or [])],
            "status": progress.status if progress else "locked",
            "completion_pct": progress.completion_pct if progress else 0.0,
            "quiz_score_avg": progress.quiz_score_avg if progress else None,
            "time_spent_minutes": progress.time_spent_minutes if progress else 0,
            "last_accessed": (
                progress.last_accessed.isoformat() if progress and progress.last_accessed else None
            ),
            "units": units_data,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _unlock_next_module(self, user_id: UUID, completed_module_id: UUID) -> None:
        """
        Unlock the module with module_number = N+1 when module N meets threshold.

        Per FR-02.2: creates an in_progress progress record for the next module
        if it doesn't already have one (i.e. is still locked).
        """
        module_result = await self.db.execute(
            select(Module).where(Module.id == completed_module_id)
        )
        module = module_result.scalar_one_or_none()
        if not module:
            return

        next_result = await self.db.execute(
            select(Module).where(Module.module_number == module.module_number + 1)
        )
        next_module = next_result.scalar_one_or_none()
        if not next_module:
            return

        existing = await self.db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id == user_id,
                UserModuleProgress.module_id == next_module.id,
            )
        )
        next_progress = existing.scalar_one_or_none()

        if next_progress is None:
            now = datetime.utcnow()
            next_progress = UserModuleProgress(
                user_id=user_id,
                module_id=next_module.id,
                status="in_progress",
                completion_pct=0.0,
                quiz_score_avg=None,
                time_spent_minutes=0,
                last_accessed=now,
            )
            self.db.add(next_progress)
            await self.db.commit()
            logger.info(
                "Next module unlocked",
                user_id=str(user_id),
                unlocked_module_number=next_module.module_number,
                unlocked_module_id=str(next_module.id),
            )
        elif next_progress.status == "locked":
            next_progress.status = "in_progress"
            await self.db.commit()
            logger.info(
                "Next module status updated to in_progress",
                user_id=str(user_id),
                module_number=next_module.module_number,
            )

        # Prefetch first 2 lessons of the newly unlocked module
        self._dispatch_prefetch(user_id, str(next_module.id), "")

    async def _dispatch_prefetch_after_quiz(
        self, user_id: UUID, module_id: UUID, unit_id: str
    ) -> None:
        """Dispatch background prefetch of the next 2 lessons after quiz pass."""
        self._dispatch_prefetch(user_id, str(module_id), unit_id)

    def _dispatch_prefetch(self, user_id: UUID, module_id: str, current_unit_id: str) -> None:
        """Fire-and-forget Celery task to prefetch next 2 lessons."""
        try:
            from app.tasks.content_generation import prefetch_next_lessons_task

            prefetch_next_lessons_task.apply_async(
                kwargs={
                    "user_id": str(user_id),
                    "module_id": module_id,
                    "current_unit_id": current_unit_id,
                    "language": "fr",
                    "country": "SN",
                    "level": 1,
                },
                priority=3,
            )
        except Exception as exc:
            logger.warning(
                "Failed to dispatch prefetch task",
                user_id=str(user_id),
                module_id=module_id,
                unit_id=current_unit_id,
                error=str(exc),
            )

    async def _get_or_create_progress(
        self, user_id: UUID, module_id: UUID, now: datetime
    ) -> UserModuleProgress:
        result = await self.db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id == user_id,
                UserModuleProgress.module_id == module_id,
            )
        )
        progress = result.scalar_one_or_none()
        if progress is None:
            progress = UserModuleProgress(
                user_id=user_id,
                module_id=module_id,
                status="in_progress",
                completion_pct=0.0,
                quiz_score_avg=None,
                time_spent_minutes=0,
                last_accessed=now,
            )
            self.db.add(progress)
            await self.db.flush()
        return progress

    async def _get_completed_units(self, user_id: UUID, module_id: UUID) -> set[str]:
        """
        Return the set of unit_numbers that have been completed.

        A unit is considered completed when the user passes its associated quiz
        (stored in user_module_progress.content JSON or quiz_attempts).
        For now we derive this from quiz_attempts where score >= 80 for the
        quiz content linked to this module and unit.
        """
        from app.domain.models.content import GeneratedContent
        from app.domain.models.quiz import QuizAttempt

        # Find all quiz content IDs for this module
        content_result = await self.db.execute(
            select(GeneratedContent.id, GeneratedContent.content).where(
                GeneratedContent.module_id == module_id,
                GeneratedContent.content_type == "quiz",
            )
        )
        quiz_contents = content_result.all()

        completed: set[str] = set()
        for quiz_id, content_data in quiz_contents:
            unit_id = content_data.get("unit_id", "") if content_data else ""
            if not unit_id:
                continue

            # Check if user passed this quiz (score >= 80)
            attempt_result = await self.db.execute(
                select(func.max(QuizAttempt.score)).where(
                    QuizAttempt.user_id == user_id,
                    QuizAttempt.quiz_id == quiz_id,
                )
            )
            max_score = attempt_result.scalar()
            if max_score is not None and max_score >= _unit_pass_score():
                completed.add(unit_id)

        return completed

    async def _calculate_completion_pct(
        self,
        user_id: UUID,
        module_id: UUID,
        just_completed_unit_id: str,
        current_progress: UserModuleProgress,
    ) -> float:
        """
        Recalculate module completion percentage.

        Based on number of units with passing quiz scores vs total units.
        """
        total_result = await self.db.execute(
            select(func.count(ModuleUnit.id)).where(ModuleUnit.module_id == module_id)
        )
        total_units = total_result.scalar() or 0

        if total_units == 0:
            return current_progress.completion_pct or 0.0

        completed_units = await self._get_completed_units(user_id, module_id)
        # Include the unit just being completed
        completed_units.add(just_completed_unit_id)

        completed_count = len(completed_units)
        return min(100.0, round((completed_count / total_units) * 100, 1))
