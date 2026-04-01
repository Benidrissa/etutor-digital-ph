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

logger = structlog.get_logger()


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
            if max_score is not None and max_score >= 80.0:
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
