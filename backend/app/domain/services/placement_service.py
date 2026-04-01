"""Placement test service for SantePublique AOF.

Handles placement test scoring and level assignment for new users.
Determines appropriate starting level (1-4) based on knowledge assessment.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from structlog import get_logger

from ..repositories.protocols import UserRepositoryProtocol

logger = get_logger(__name__)


class PlacementTestResult(BaseModel):
    """Placement test scoring result."""

    assigned_level: int
    score_percentage: float
    competency_areas: list[str]
    recommendations: list[str]


class PlacementService:
    """Service for placement test operations."""

    def __init__(self, user_repo: UserRepositoryProtocol):
        self.user_repo = user_repo

        # Placement test questions and scoring rubric
        self._init_placement_test_config()

    def _init_placement_test_config(self):
        """Initialize placement test configuration."""

        # Question categories and weights
        self.categories = {
            "basic_public_health": {"weight": 0.3, "questions": list(range(1, 6))},
            "epidemiology": {"weight": 0.25, "questions": list(range(6, 11))},
            "biostatistics": {"weight": 0.25, "questions": list(range(11, 16))},
            "data_analysis": {"weight": 0.2, "questions": list(range(16, 21))},
        }

        # Level thresholds (percentage scores)
        self.level_thresholds = {
            1: {"min": 0.0, "max": 40.0},  # Beginner: 0-40%
            2: {"min": 40.0, "max": 60.0},  # Intermediate: 40-60%
            3: {"min": 60.0, "max": 80.0},  # Advanced: 60-80%
            4: {"min": 80.0, "max": 100.0},  # Expert: 80-100%
        }

        # Correct answers for scoring (question_id -> correct_option)
        self.answer_key = {
            # Basic Public Health (1-5)
            "1": "c",
            "2": "a",
            "3": "b",
            "4": "d",
            "5": "a",
            # Epidemiology (6-10)
            "6": "b",
            "7": "c",
            "8": "a",
            "9": "d",
            "10": "b",
            # Biostatistics (11-15)
            "11": "a",
            "12": "c",
            "13": "b",
            "14": "a",
            "15": "d",
            # Data Analysis (16-20)
            "16": "b",
            "17": "c",
            "18": "a",
            "19": "b",
            "20": "d",
        }

    def compute_domain_scores(self, answers: dict[str, Any]) -> dict[str, float]:
        """Compute per-domain scores from raw answers.

        Args:
            answers: Question ID -> selected answer mapping

        Returns:
            Domain name -> percentage score (0-100)
        """
        domain_scores: dict[str, float] = {}
        for category, config in self.categories.items():
            correct = 0
            total = 0
            for q_id in config["questions"]:
                q_str = str(q_id)
                if q_str in answers and q_str in self.answer_key:
                    total += 1
                    if answers[q_str] == self.answer_key[q_str]:
                        correct += 1
            domain_scores[category] = (correct / total * 100) if total > 0 else 0.0
        return domain_scores

    async def get_placement_result(self, user_id: UUID) -> PlacementTestResult | None:
        """Get existing placement test result for user.

        Args:
            user_id: User UUID

        Returns:
            Placement test result if already completed, None otherwise
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return None

        # Check if user has already been assigned a level through placement test
        # (current_level > 1 indicates placement test completion)
        if user.current_level > 1:
            # Return cached result (simplified - in production would store full results)
            return PlacementTestResult(
                assigned_level=user.current_level,
                score_percentage=float(user.current_level * 20),  # Estimate
                competency_areas=["Cached result"],
                recommendations=["Continue learning at your assigned level"],
            )

        return None

    async def score_placement_test(
        self, user_id: UUID, answers: dict[str, Any], time_taken: int, user_context: dict[str, Any]
    ) -> PlacementTestResult:
        """Score placement test and assign level.

        Args:
            user_id: User UUID
            answers: Question ID -> selected answer mapping
            time_taken: Test completion time in seconds
            user_context: User background info (role, country, etc.)

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

        # Score by category
        category_scores = {}
        total_correct = 0
        total_questions = 0

        for category, config in self.categories.items():
            correct_in_category = 0
            questions_in_category = 0

            for q_id in config["questions"]:
                q_str = str(q_id)
                if q_str in answers and q_str in self.answer_key:
                    questions_in_category += 1
                    if answers[q_str] == self.answer_key[q_str]:
                        correct_in_category += 1

            if questions_in_category > 0:
                category_scores[category] = (correct_in_category / questions_in_category) * 100
            else:
                category_scores[category] = 0.0

            total_correct += correct_in_category
            total_questions += questions_in_category

        # Calculate overall score
        overall_score = (total_correct / total_questions) * 100 if total_questions > 0 else 0.0

        # Adjust score based on context
        adjusted_score = self._adjust_score_for_context(overall_score, user_context, time_taken)

        # Determine level
        assigned_level = self._determine_level(adjusted_score)

        # Generate competency areas and recommendations
        competency_areas = self._identify_competencies(category_scores)
        recommendations = self._generate_recommendations(
            assigned_level, category_scores, user_context
        )

        # Update user's level
        user.current_level = assigned_level
        await self.user_repo.update(user)

        result = PlacementTestResult(
            assigned_level=assigned_level,
            score_percentage=adjusted_score,
            competency_areas=competency_areas,
            recommendations=recommendations,
        )

        logger.info(
            "Completed placement test scoring",
            user_id=str(user_id),
            raw_score=overall_score,
            adjusted_score=adjusted_score,
            assigned_level=assigned_level,
            category_scores=category_scores,
        )

        return result

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

        # Professional role adjustments
        role = context.get("professional_role", "").lower()
        if "doctor" in role or "physician" in role:
            adjusted += 5  # Medical professionals get bonus
        elif "researcher" in role or "epidemiologist" in role:
            adjusted += 8  # Research professionals get higher bonus
        elif "nurse" in role:
            adjusted += 3  # Nurses get small bonus
        elif "student" in role:
            adjusted -= 3  # Students get small penalty

        # Time-based adjustments
        if time_taken < 600:  # Less than 10 minutes (too fast)
            adjusted -= 10
        elif time_taken > 2400:  # More than 40 minutes (too slow)
            adjusted -= 5
        elif 900 <= time_taken <= 1800:  # 15-30 minutes (optimal)
            adjusted += 2

        # Keep within bounds
        return max(0.0, min(100.0, adjusted))

    def _determine_level(self, score: float) -> int:
        """Determine user level based on adjusted score.

        Args:
            score: Adjusted percentage score (0-100)

        Returns:
            Level 1-4
        """
        for level, threshold in self.level_thresholds.items():
            if threshold["min"] <= score < threshold["max"]:
                return level

        # Default to level 1 if no match
        return 1

    def _identify_competencies(self, category_scores: dict[str, float]) -> list[str]:
        """Identify strong competency areas based on category scores.

        Args:
            category_scores: Score by category (0-100)

        Returns:
            List of strong competency areas
        """
        competencies = []

        for category, score in category_scores.items():
            if score >= 70:
                if category == "basic_public_health":
                    competencies.append("Public Health Fundamentals")
                elif category == "epidemiology":
                    competencies.append("Epidemiological Methods")
                elif category == "biostatistics":
                    competencies.append("Biostatistics & Data Analysis")
                elif category == "data_analysis":
                    competencies.append("Data Interpretation")

        if not competencies:
            competencies = ["Foundation Building"]

        return competencies

    def _generate_recommendations(
        self, level: int, category_scores: dict[str, float], context: dict[str, Any]
    ) -> list[str]:
        """Generate personalized learning recommendations.

        Args:
            level: Assigned level (1-4)
            category_scores: Scores by category
            context: User context

        Returns:
            List of learning recommendations
        """
        recommendations = []

        # Level-based recommendations
        if level == 1:
            recommendations.append("Start with Module 1: Public Health Foundations")
            recommendations.append("Focus on building core concepts before advancing")
        elif level == 2:
            recommendations.append("Begin with Module 4: Epidemiological Methods")
            recommendations.append("Review statistics fundamentals as needed")
        elif level == 3:
            recommendations.append("Start with Module 8: Advanced Epidemiology")
            recommendations.append("Consider specializing in your area of interest")
        else:
            recommendations.append("Begin with Module 13: Health Policy & Systems")
            recommendations.append("Focus on leadership and research skills")

        # Category-based recommendations
        weak_areas = [cat for cat, score in category_scores.items() if score < 50]
        if "biostatistics" in weak_areas:
            recommendations.append("Strengthen biostatistics skills with practice exercises")
        if "epidemiology" in weak_areas:
            recommendations.append("Review epidemiological study designs and measures")

        # Context-based recommendations
        country = context.get("country", "").lower()
        if country in ["senegal", "mali", "burkina"]:
            recommendations.append("Focus on Sahel-specific health challenges")
        elif country in ["ghana", "nigeria"]:
            recommendations.append("Emphasize coastal disease patterns and urban health")

        return recommendations[:5]  # Limit to top 5 recommendations
