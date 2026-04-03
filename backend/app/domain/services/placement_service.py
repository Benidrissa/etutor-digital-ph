"""Placement test service for SantePublique AOF.

Handles placement test scoring, level assignment, and module unlocking for new users.
Determines appropriate starting level (1-4) based on knowledge assessment spanning all levels.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ..models.module import Module
from ..models.progress import UserModuleProgress
from ..repositories.protocols import UserRepositoryProtocol
from .platform_settings_service import SettingsCache

logger = get_logger(__name__)

LEVEL_THRESHOLDS = {
    1: {"min": 0.0, "max": 40.0},
    2: {"min": 40.0, "max": 60.0},
    3: {"min": 60.0, "max": 80.0},
    4: {"min": 80.0, "max": 101.0},
}

MODULES_BY_LEVEL: dict[int, list[int]] = {
    1: [1, 2, 3],
    2: [4, 5, 6, 7],
    3: [8, 9, 10, 11, 12],
    4: [13, 14, 15],
}

QUESTION_LEVELS: dict[str, int] = {
    "1": 1,
    "2": 1,
    "3": 1,
    "4": 1,
    "5": 1,
    "6": 2,
    "7": 2,
    "8": 2,
    "9": 2,
    "10": 2,
    "11": 3,
    "12": 3,
    "13": 3,
    "14": 3,
    "15": 3,
    "16": 4,
    "17": 4,
    "18": 4,
    "19": 4,
    "20": 4,
}

ANSWER_KEY: dict[str, str] = {
    "1": "c",
    "2": "a",
    "3": "b",
    "4": "b",
    "5": "b",
    "6": "b",
    "7": "c",
    "8": "b",
    "9": "c",
    "10": "b",
    "11": "b",
    "12": "a",
    "13": "b",
    "14": "d",
    "15": "a",
    "16": "b",
    "17": "c",
    "18": "b",
    "19": "b",
    "20": "d",
}


class PlacementTestResult(BaseModel):
    """Placement test scoring result."""

    assigned_level: int
    score_percentage: float
    level_scores: dict[str, float]
    competency_areas: list[str]
    recommendations: list[str]


class PlacementService:
    """Service for placement test operations."""

    def __init__(self, user_repo: UserRepositoryProtocol):
        self.user_repo = user_repo

    async def get_placement_result(self, user_id: UUID) -> PlacementTestResult | None:
        """Get existing placement test result for user.

        Returns:
            Placement test result if already completed, None otherwise
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user or user.current_level == 1:
            return None

        return PlacementTestResult(
            assigned_level=user.current_level,
            score_percentage=float(user.current_level * 20),
            level_scores={},
            competency_areas=["Cached result"],
            recommendations=["Continue learning at your assigned level"],
        )

    async def score_placement_test(
        self,
        user_id: UUID,
        answers: dict[str, Any],
        time_taken: int,
        user_context: dict[str, Any],
        db: AsyncSession,
    ) -> PlacementTestResult:
        """Score placement test, assign level, and unlock modules.

        Args:
            user_id: User UUID
            answers: Question ID -> selected answer mapping
            time_taken: Test completion time in seconds
            user_context: User background info (role, country, etc.)
            db: Database session for module unlocking

        Returns:
            Placement test result with assigned level

        Raises:
            ValueError: If invalid answers or user not found
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        if not answers:
            raise ValueError("No answers provided")

        level_correct: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
        level_total: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

        for q_id, selected in answers.items():
            q_level = QUESTION_LEVELS.get(q_id)
            if q_level is None or q_id not in ANSWER_KEY:
                continue
            level_total[q_level] += 1
            if selected == ANSWER_KEY[q_id]:
                level_correct[q_level] += 1

        level_scores: dict[str, float] = {}
        for lvl in range(1, 5):
            total = level_total[lvl]
            level_scores[f"level_{lvl}"] = (level_correct[lvl] / total * 100) if total > 0 else 0.0

        total_answered = sum(level_total.values())
        total_correct = sum(level_correct.values())
        overall_score = (total_correct / total_answered * 100) if total_answered > 0 else 0.0

        adjusted_score = self._adjust_score_for_context(overall_score, user_context, time_taken)
        assigned_level = self._determine_level(adjusted_score)

        competency_areas = self._identify_competencies(level_scores)
        recommendations = self._generate_recommendations(assigned_level, level_scores, user_context)

        user.current_level = assigned_level
        await self.user_repo.update(user)

        await self._unlock_modules_after_placement(user_id, assigned_level, db)

        result = PlacementTestResult(
            assigned_level=assigned_level,
            score_percentage=adjusted_score,
            level_scores=level_scores,
            competency_areas=competency_areas,
            recommendations=recommendations,
        )

        logger.info(
            "Completed placement test scoring",
            user_id=str(user_id),
            overall_score=overall_score,
            adjusted_score=adjusted_score,
            assigned_level=assigned_level,
            level_scores=level_scores,
        )

        return result

    async def _unlock_modules_after_placement(
        self, user_id: UUID, assigned_level: int, db: AsyncSession
    ) -> None:
        """Unlock modules based on placement result.

        - Modules below assessed level → status = "completed", completion_pct = 100
        - First module of assessed level → status = "in_progress"
        - Remaining modules of assessed level and above → status = "locked"

        Args:
            user_id: User UUID
            assigned_level: Level assigned by placement test (1-4)
            db: Database session
        """
        modules_result = await db.execute(select(Module).order_by(Module.module_number))
        all_modules = list(modules_result.scalars().all())

        first_module_at_level: UUID | None = None
        for module in all_modules:
            if module.level == assigned_level:
                first_module_at_level = module.id
                break

        for module in all_modules:
            if module.level < assigned_level:
                status = "completed"
                completion_pct = 100.0
            elif module.id == first_module_at_level:
                status = "in_progress"
                completion_pct = 0.0
            else:
                status = "locked"
                completion_pct = 0.0

            existing_result = await db.execute(
                select(UserModuleProgress).where(
                    UserModuleProgress.user_id == user_id,
                    UserModuleProgress.module_id == module.id,
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing is not None:
                existing.status = status
                existing.completion_pct = completion_pct
                existing.last_accessed = datetime.utcnow()
            else:
                progress = UserModuleProgress(
                    user_id=user_id,
                    module_id=module.id,
                    status=status,
                    completion_pct=completion_pct,
                    time_spent_minutes=0,
                    last_accessed=datetime.utcnow(),
                )
                db.add(progress)

        await db.commit()

        logger.info(
            "Modules unlocked after placement",
            user_id=str(user_id),
            assigned_level=assigned_level,
        )

    def _adjust_score_for_context(
        self, raw_score: float, context: dict[str, Any], time_taken: int
    ) -> float:
        """Adjust raw score based on user context and completion time.

        Args:
            raw_score: Raw percentage score (0-100)
            context: User background information
            time_taken: Test completion time in seconds

        Returns:
            Adjusted score (0-100)
        """
        adjusted = raw_score

        role_bonuses = SettingsCache.instance().get(
            "placement.role_bonuses", {
                "doctor": 5, "physician": 5,
                "researcher": 8, "epidemiologist": 8,
                "nurse": 3, "student": -3,
            },
        )
        role = context.get("professional_role", "").lower()
        for keyword, bonus in role_bonuses.items():
            if keyword in role:
                adjusted += bonus
                break

        time_adj = SettingsCache.instance().get(
            "placement.time_adjustments", {
                "too_fast_threshold": 600, "too_fast_penalty": -10,
                "too_slow_threshold": 2400, "too_slow_penalty": -5,
                "optimal_min": 900, "optimal_max": 1800,
                "optimal_bonus": 2,
            },
        )
        if time_taken < time_adj["too_fast_threshold"]:
            adjusted += time_adj["too_fast_penalty"]
        elif time_taken > time_adj["too_slow_threshold"]:
            adjusted += time_adj["too_slow_penalty"]
        elif time_adj["optimal_min"] <= time_taken <= time_adj["optimal_max"]:
            adjusted += time_adj["optimal_bonus"]

        return max(0.0, min(100.0, adjusted))

    def _determine_level(self, score: float) -> int:
        """Determine user level based on adjusted score.

        Args:
            score: Adjusted percentage score (0-100)

        Returns:
            Level 1-4
        """
        thresholds = SettingsCache.instance().get(
            "placement.level_thresholds", LEVEL_THRESHOLDS,
        )
        # Keys may be strings when loaded from JSON settings
        for level, threshold in thresholds.items():
            if threshold["min"] <= score < threshold["max"]:
                return int(level)
        return 1

    def _identify_competencies(self, level_scores: dict[str, float]) -> list[str]:
        """Identify strong competency areas based on per-level scores.

        Args:
            level_scores: Score by level key e.g. {"level_1": 80.0, ...}

        Returns:
            List of strong competency areas
        """
        label_map = {
            "level_1": "Public Health Foundations",
            "level_2": "Epidemiology & Surveillance",
            "level_3": "Advanced Statistics & Programming",
            "level_4": "Health Policy & Research",
        }
        _comp_threshold = SettingsCache.instance().get(
            "placement.competency_threshold", 70,
        )
        competencies = [label_map[k] for k, v in level_scores.items() if v >= _comp_threshold and k in label_map]
        return competencies if competencies else ["Foundation Building"]

    def _generate_recommendations(
        self, level: int, level_scores: dict[str, float], context: dict[str, Any]
    ) -> list[str]:
        """Generate personalized learning recommendations.

        Args:
            level: Assigned level (1-4)
            level_scores: Scores by level
            context: User context

        Returns:
            List of learning recommendations
        """
        recommendations: list[str] = []

        if level == 1:
            recommendations.append("Start with Module 1: Public Health Foundations")
            recommendations.append("Focus on building core concepts before advancing")
        elif level == 2:
            recommendations.append("Begin with Module 4: Epidemiological Methods")
            recommendations.append("Modules 1-3 have been validated — you may review them anytime")
        elif level == 3:
            recommendations.append("Start with Module 8: Advanced Epidemiology")
            recommendations.append("Modules 1-7 have been validated — you may review them anytime")
        else:
            recommendations.append("Begin with Module 13: Health Policy & Systems")
            recommendations.append("Modules 1-12 have been validated — you may review them anytime")

        weak_levels = [k for k, v in level_scores.items() if v < 50]
        if "level_2" in weak_levels:
            recommendations.append("Strengthen epidemiological study design knowledge")
        if "level_3" in weak_levels:
            recommendations.append("Reinforce biostatistics and data analysis skills")

        country = context.get("country", "").lower()
        if country in ["senegal", "mali", "burkina faso", "guinea"]:
            recommendations.append("Focus on Sahel-specific health challenges")
        elif country in ["ghana", "nigeria", "benin", "togo"]:
            recommendations.append("Emphasize coastal disease patterns and urban health")
        elif country in ["cote d'ivoire", "liberia", "sierra leone"]:
            recommendations.append("Focus on tropical disease burden in your region")

        return recommendations[:5]
