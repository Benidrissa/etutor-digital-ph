"""Module service for handling module progression and unlock logic."""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress


class ModuleService:
    """Service for module-related business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_modules_with_progress(self, user_id: UUID) -> list[dict[str, Any]]:
        """Get all modules with user progress and unlock status."""
        # Fetch all modules
        modules_result = await self.db.execute(select(Module).order_by(Module.module_number))
        modules = modules_result.scalars().all()

        # Fetch user progress for all modules
        progress_result = await self.db.execute(
            select(UserModuleProgress).where(UserModuleProgress.user_id == user_id)
        )
        progress_dict = {p.module_id: p for p in progress_result.scalars().all()}

        result = []
        for module in modules:
            progress = progress_dict.get(module.id)

            # Determine unlock status
            is_unlocked = await self._is_module_unlocked(user_id, module, progress_dict)

            result.append(
                {
                    "id": str(module.id),
                    "module_number": module.module_number,
                    "level": module.level,
                    "title_fr": module.title_fr,
                    "title_en": module.title_en,
                    "description_fr": module.description_fr,
                    "description_en": module.description_en,
                    "estimated_hours": module.estimated_hours,
                    "bloom_level": module.bloom_level,
                    "prereq_modules": [str(pid) for pid in (module.prereq_modules or [])],
                    "books_sources": module.books_sources,
                    "progress": {
                        "status": progress.status
                        if progress
                        else ("unlocked" if is_unlocked else "locked"),
                        "completion_pct": progress.completion_pct if progress else 0.0,
                        "quiz_score_avg": progress.quiz_score_avg if progress else None,
                        "time_spent_minutes": progress.time_spent_minutes if progress else 0,
                        "last_accessed": progress.last_accessed.isoformat()
                        if progress and progress.last_accessed
                        else None,
                    }
                    if progress or is_unlocked
                    else {
                        "status": "locked",
                        "completion_pct": 0.0,
                        "quiz_score_avg": None,
                        "time_spent_minutes": 0,
                        "last_accessed": None,
                    },
                    "is_unlocked": is_unlocked,
                }
            )

        return result

    async def get_module_unlock_status(self, user_id: UUID, module_id: UUID) -> dict[str, Any]:
        """Get detailed unlock status for a specific module."""
        # Get the module
        module_result = await self.db.execute(select(Module).where(Module.id == module_id))
        module = module_result.scalar_one_or_none()
        if not module:
            raise ValueError(f"Module {module_id} not found")

        # Get user progress
        progress_result = await self.db.execute(
            select(UserModuleProgress).where(
                and_(
                    UserModuleProgress.user_id == user_id, UserModuleProgress.module_id == module_id
                )
            )
        )
        progress = progress_result.scalar_one_or_none()

        # Get all user progress for prerequisite checking
        all_progress_result = await self.db.execute(
            select(UserModuleProgress).where(UserModuleProgress.user_id == user_id)
        )
        progress_dict = {p.module_id: p for p in all_progress_result.scalars().all()}

        # Check unlock status
        is_unlocked, prereq_status = await self._check_module_unlock_detailed(
            user_id, module, progress_dict
        )

        return {
            "module_id": str(module_id),
            "is_unlocked": is_unlocked,
            "current_status": progress.status
            if progress
            else ("unlocked" if is_unlocked else "locked"),
            "prerequisites": prereq_status,
        }

    async def _is_module_unlocked(
        self, user_id: UUID, module: Module, progress_dict: dict[UUID, UserModuleProgress]
    ) -> bool:
        """Check if a module should be unlocked for the user."""
        # M01 is always unlocked (no prerequisites)
        if module.module_number == 1:
            return True

        # If no prerequisites defined, module is unlocked
        if not module.prereq_modules:
            return True

        # Check all prerequisites meet the 80% completion and quiz score requirement
        for prereq_id in module.prereq_modules:
            prereq_progress = progress_dict.get(prereq_id)
            if not prereq_progress:
                return False

            # Must have ≥80% completion AND ≥80% quiz score average
            if (
                prereq_progress.completion_pct < 80.0
                or prereq_progress.quiz_score_avg is None
                or prereq_progress.quiz_score_avg < 80.0
            ):
                return False

        return True

    async def _check_module_unlock_detailed(
        self, user_id: UUID, module: Module, progress_dict: dict[UUID, UserModuleProgress]
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Check module unlock status with detailed prerequisite information."""
        # M01 is always unlocked
        if module.module_number == 1:
            return True, []

        # If no prerequisites, module is unlocked
        if not module.prereq_modules:
            return True, []

        prereq_status = []
        all_prereqs_met = True

        for prereq_id in module.prereq_modules:
            # Get prerequisite module info
            prereq_result = await self.db.execute(select(Module).where(Module.id == prereq_id))
            prereq_module = prereq_result.scalar_one_or_none()

            prereq_progress = progress_dict.get(prereq_id)

            completion_met = prereq_progress and prereq_progress.completion_pct >= 80.0
            quiz_score_met = (
                prereq_progress
                and prereq_progress.quiz_score_avg is not None
                and prereq_progress.quiz_score_avg >= 80.0
            )

            is_met = completion_met and quiz_score_met
            if not is_met:
                all_prereqs_met = False

            prereq_status.append(
                {
                    "module_id": str(prereq_id),
                    "module_number": prereq_module.module_number if prereq_module else None,
                    "title": prereq_module.title_en if prereq_module else "Unknown Module",
                    "completion_pct": prereq_progress.completion_pct if prereq_progress else 0.0,
                    "quiz_score_avg": prereq_progress.quiz_score_avg if prereq_progress else None,
                    "completion_met": completion_met,
                    "quiz_score_met": quiz_score_met,
                    "overall_met": is_met,
                }
            )

        return all_prereqs_met, prereq_status

    async def unlock_module_if_eligible(self, user_id: UUID, module_id: UUID) -> bool:
        """Unlock a module if it's eligible and create progress entry."""
        module_result = await self.db.execute(select(Module).where(Module.id == module_id))
        module = module_result.scalar_one_or_none()
        if not module:
            return False

        # Get all user progress for checking prerequisites
        progress_result = await self.db.execute(
            select(UserModuleProgress).where(UserModuleProgress.user_id == user_id)
        )
        progress_dict = {p.module_id: p for p in progress_result.scalars().all()}

        # Check if module should be unlocked
        is_unlocked = await self._is_module_unlocked(user_id, module, progress_dict)

        if is_unlocked:
            # Check if progress record already exists
            existing_progress = progress_dict.get(module_id)
            if not existing_progress:
                # Create new progress record with "unlocked" status
                new_progress = UserModuleProgress(
                    user_id=user_id,
                    module_id=module_id,
                    status="unlocked",
                    completion_pct=0.0,
                    quiz_score_avg=None,
                    time_spent_minutes=0,
                )
                self.db.add(new_progress)
                await self.db.commit()
                return True
            elif existing_progress.status == "locked":
                # Update existing locked progress to unlocked
                existing_progress.status = "unlocked"
                await self.db.commit()
                return True

        return False
