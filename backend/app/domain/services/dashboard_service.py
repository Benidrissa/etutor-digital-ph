"""Dashboard service for calculating user streak and daily statistics."""

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.flashcard import FlashcardReview
from app.domain.models.lesson_reading import LessonReading
from app.domain.models.progress import UserModuleProgress
from app.domain.models.quiz import QuizAttempt
from app.domain.models.user import User


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_stats(self, user_id: str, timezone_offset_hours: int = 0) -> dict[str, Any]:
        """
        Calculate comprehensive user dashboard statistics.

        Args:
            user_id: UUID of the user
            timezone_offset_hours: User's timezone offset from UTC (e.g., +1 for CET)

        Returns:
            Dictionary containing streak, stats, and activity data
        """
        # Get user data
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User {user_id} not found")

        # Calculate streak
        current_streak = await self._calculate_streak(user_id, timezone_offset_hours)

        # Update user's streak if needed
        if current_streak != user.streak_days:
            user.streak_days = current_streak
            await self.db.commit()

        # Calculate other stats
        stats = {
            "streak_days": current_streak,
            "average_quiz_score": await self._get_average_quiz_score(user_id),
            "total_time_studied_this_week": await self._get_weekly_study_time(
                user_id, timezone_offset_hours
            ),
            "is_active_today": await self._is_active_today(user_id, timezone_offset_hours),
            "next_review_count": await self._get_due_flashcard_count(user_id),
            "modules_in_progress": await self._get_modules_in_progress(user_id),
            "completion_percentage": await self._get_overall_completion(user_id),
        }

        return stats

    async def _calculate_streak(self, user_id: str, timezone_offset_hours: int) -> int:
        """Calculate consecutive days of activity."""
        today = self._get_user_date(timezone_offset_hours)
        streak = 0
        check_date = today

        while True:
            if await self._was_active_on_date(user_id, check_date, timezone_offset_hours):
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        return streak

    async def _was_active_on_date(
        self, user_id: str, check_date: date, timezone_offset_hours: int
    ) -> bool:
        """
        Check if user was active on a specific date.
        Active = ≥1 quiz answer OR ≥5 flashcard reviews OR ≥1 lesson read
        """
        start_dt = datetime.combine(check_date, datetime.min.time()) - timedelta(
            hours=timezone_offset_hours
        )
        end_dt = start_dt + timedelta(days=1)

        # Check quiz attempts
        quiz_result = await self.db.execute(
            select(func.count(QuizAttempt.id)).where(
                and_(
                    QuizAttempt.user_id == user_id,
                    QuizAttempt.attempted_at >= start_dt,
                    QuizAttempt.attempted_at < end_dt,
                )
            )
        )
        quiz_count = quiz_result.scalar() or 0

        if quiz_count >= 1:
            return True

        # Check flashcard reviews
        flashcard_result = await self.db.execute(
            select(func.count(FlashcardReview.id)).where(
                and_(
                    FlashcardReview.user_id == user_id,
                    FlashcardReview.reviewed_at >= start_dt,
                    FlashcardReview.reviewed_at < end_dt,
                )
            )
        )
        flashcard_count = flashcard_result.scalar() or 0

        if flashcard_count >= 5:
            return True

        # Check lesson readings
        lesson_result = await self.db.execute(
            select(func.count(LessonReading.id)).where(
                and_(
                    LessonReading.user_id == user_id,
                    LessonReading.read_at >= start_dt,
                    LessonReading.read_at < end_dt,
                )
            )
        )
        lesson_count = lesson_result.scalar() or 0

        return lesson_count >= 1

    async def _is_active_today(self, user_id: str, timezone_offset_hours: int) -> bool:
        """Check if user is active today."""
        today = self._get_user_date(timezone_offset_hours)
        return await self._was_active_on_date(user_id, today, timezone_offset_hours)

    async def _get_average_quiz_score(self, user_id: str) -> float:
        """Calculate average quiz score across all modules."""
        result = await self.db.execute(
            select(func.avg(QuizAttempt.score)).where(
                and_(QuizAttempt.user_id == user_id, QuizAttempt.score.is_not(None))
            )
        )
        avg_score = result.scalar()
        return float(avg_score) if avg_score else 0.0

    async def _get_weekly_study_time(self, user_id: str, timezone_offset_hours: int) -> int:
        """Get total time studied this week in minutes."""
        week_start = self._get_user_date(timezone_offset_hours) - timedelta(days=6)
        week_start_dt = datetime.combine(week_start, datetime.min.time()) - timedelta(
            hours=timezone_offset_hours
        )

        # Sum time from user_module_progress (already in minutes)
        progress_result = await self.db.execute(
            select(func.sum(UserModuleProgress.time_spent_minutes)).where(
                and_(
                    UserModuleProgress.user_id == user_id,
                    UserModuleProgress.last_accessed >= week_start_dt,
                )
            )
        )
        progress_time = progress_result.scalar() or 0

        # Sum time from lesson readings (convert seconds to minutes)
        lesson_result = await self.db.execute(
            select(func.sum(LessonReading.time_spent_seconds)).where(
                and_(LessonReading.user_id == user_id, LessonReading.read_at >= week_start_dt)
            )
        )
        lesson_time_seconds = lesson_result.scalar() or 0
        lesson_time_minutes = lesson_time_seconds // 60

        return int(progress_time + lesson_time_minutes)

    async def _get_due_flashcard_count(self, user_id: str) -> int:
        """Get count of flashcards due for review."""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(func.count(FlashcardReview.id)).where(
                and_(FlashcardReview.user_id == user_id, FlashcardReview.next_review <= now)
            )
        )
        return result.scalar() or 0

    async def _get_modules_in_progress(self, user_id: str) -> int:
        """Get count of modules currently in progress."""
        result = await self.db.execute(
            select(func.count(UserModuleProgress.module_id)).where(
                and_(
                    UserModuleProgress.user_id == user_id,
                    UserModuleProgress.status == "in_progress",
                )
            )
        )
        return result.scalar() or 0

    async def _get_overall_completion(self, user_id: str) -> float:
        """Calculate overall completion percentage across all modules."""
        result = await self.db.execute(
            select(func.avg(UserModuleProgress.completion_pct)).where(
                UserModuleProgress.user_id == user_id
            )
        )
        avg_completion = result.scalar()
        return float(avg_completion) if avg_completion else 0.0

    def _get_user_date(self, timezone_offset_hours: int) -> date:
        """Get current date in user's timezone."""
        utc_now = datetime.utcnow()
        user_time = utc_now + timedelta(hours=timezone_offset_hours)
        return user_time.date()
