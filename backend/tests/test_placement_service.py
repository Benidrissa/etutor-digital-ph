"""Unit tests for PlacementService scoring and module unlocking."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.placement_service import (
    PlacementService,
    PlacementTestResult,
)

_ANSWER_KEY: dict[str, str] = {
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

_QUESTION_LEVELS: dict[str, int] = {
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


def _make_user(level: int = 1) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.current_level = level
    return user


def _make_user_repo(user: MagicMock | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_id.return_value = user
    repo.update.return_value = user
    return repo


def _all_correct_answers() -> dict[str, str]:
    return dict(_ANSWER_KEY)


def _answers_for_levels(*levels: int) -> dict[str, str]:
    """Return correct answers only for questions belonging to given levels."""
    return {
        q_id: _ANSWER_KEY[q_id] for q_id, q_level in _QUESTION_LEVELS.items() if q_level in levels
    }


def _wrong_answers_for_levels(*levels: int) -> dict[str, str]:
    """Return wrong answers for questions belonging to given levels."""
    wrong: dict[str, str] = {}
    for q_id, q_level in _QUESTION_LEVELS.items():
        if q_level in levels:
            correct = _ANSWER_KEY[q_id]
            wrong[q_id] = "a" if correct != "a" else "b"
    return wrong


def _make_db_mock_with_preassessment() -> AsyncMock:
    """Return a mock DB that returns a preassessment with the test answer key."""
    preassessment = MagicMock()
    preassessment.answer_key = _ANSWER_KEY
    preassessment.question_levels = _QUESTION_LEVELS

    scalar_one_or_none_results = [
        MagicMock(id=uuid.uuid4()),
        preassessment,
    ]
    call_count = 0

    async def execute_side_effect(*args, **kwargs):
        nonlocal call_count
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar_one_or_none_results[
            min(call_count, len(scalar_one_or_none_results) - 1)
        ]
        result.scalars.return_value.all.return_value = []
        call_count += 1
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()
    return db


class TestLevelThresholds:
    def test_level_1_below_40(self):
        service = PlacementService(_make_user_repo())
        assert service._determine_level(0.0) == 1
        assert service._determine_level(20.0) == 1
        assert service._determine_level(39.9) == 1

    def test_level_2_between_40_and_60(self):
        service = PlacementService(_make_user_repo())
        assert service._determine_level(40.0) == 2
        assert service._determine_level(50.0) == 2
        assert service._determine_level(59.9) == 2

    def test_level_3_between_60_and_80(self):
        service = PlacementService(_make_user_repo())
        assert service._determine_level(60.0) == 3
        assert service._determine_level(70.0) == 3
        assert service._determine_level(79.9) == 3

    def test_level_4_at_or_above_80(self):
        service = PlacementService(_make_user_repo())
        assert service._determine_level(80.0) == 4
        assert service._determine_level(90.0) == 4
        assert service._determine_level(100.0) == 4


class TestScoreAdjustment:
    def test_researcher_bonus_applied(self):
        service = PlacementService(_make_user_repo())
        adjusted = service._adjust_score_for_context(
            50.0, {"professional_role": "epidemiologist"}, 1200
        )
        assert adjusted > 50.0

    def test_student_penalty_applied(self):
        service = PlacementService(_make_user_repo())
        adjusted = service._adjust_score_for_context(50.0, {"professional_role": "student"}, 1200)
        assert adjusted < 50.0

    def test_too_fast_penalty_applied(self):
        service = PlacementService(_make_user_repo())
        adjusted = service._adjust_score_for_context(50.0, {}, time_taken=300)
        assert adjusted < 50.0

    def test_optimal_time_bonus_applied(self):
        service = PlacementService(_make_user_repo())
        adjusted = service._adjust_score_for_context(50.0, {}, time_taken=1200)
        assert adjusted > 50.0

    def test_score_clipped_at_100(self):
        service = PlacementService(_make_user_repo())
        adjusted = service._adjust_score_for_context(
            99.0, {"professional_role": "researcher"}, 1200
        )
        assert adjusted <= 100.0

    def test_score_clipped_at_0(self):
        service = PlacementService(_make_user_repo())
        adjusted = service._adjust_score_for_context(5.0, {"professional_role": "student"}, 300)
        assert adjusted >= 0.0


class TestIdentifyCompetencies:
    def test_high_level1_score_returns_foundations(self):
        service = PlacementService(_make_user_repo())
        competencies = service._identify_competencies(
            {"level_1": 80.0, "level_2": 30.0, "level_3": 20.0, "level_4": 10.0}
        )
        assert "Public Health Foundations" in competencies

    def test_low_scores_returns_foundation_building(self):
        service = PlacementService(_make_user_repo())
        competencies = service._identify_competencies(
            {"level_1": 40.0, "level_2": 30.0, "level_3": 20.0, "level_4": 10.0}
        )
        assert competencies == ["Foundation Building"]

    def test_multiple_strong_areas_returned(self):
        service = PlacementService(_make_user_repo())
        competencies = service._identify_competencies(
            {"level_1": 90.0, "level_2": 85.0, "level_3": 75.0, "level_4": 20.0}
        )
        assert len(competencies) >= 3


class TestGenerateRecommendations:
    def test_level1_recommendations(self):
        service = PlacementService(_make_user_repo())
        recs = service._generate_recommendations(1, {}, {})
        assert any("Module 1" in r for r in recs)

    def test_level2_recommendations_mention_validated_modules(self):
        service = PlacementService(_make_user_repo())
        recs = service._generate_recommendations(2, {}, {})
        assert any("1-3" in r or "Module 4" in r for r in recs)

    def test_level3_recommendations_mention_validated_modules(self):
        service = PlacementService(_make_user_repo())
        recs = service._generate_recommendations(3, {}, {})
        assert any("1-7" in r or "Module 8" in r for r in recs)

    def test_level4_recommendations_mention_validated_modules(self):
        service = PlacementService(_make_user_repo())
        recs = service._generate_recommendations(4, {}, {})
        assert any("1-12" in r or "Module 13" in r for r in recs)

    def test_country_recommendation_senegal(self):
        service = PlacementService(_make_user_repo())
        recs = service._generate_recommendations(2, {}, {"country": "senegal"})
        assert any("Sahel" in r for r in recs)

    def test_max_5_recommendations_returned(self):
        service = PlacementService(_make_user_repo())
        recs = service._generate_recommendations(
            2,
            {"level_2": 30.0, "level_3": 30.0},
            {"country": "ghana"},
        )
        assert len(recs) <= 5


class TestScorePlacementTest:
    async def test_all_correct_answers_returns_level4(self):
        user = _make_user()
        repo = _make_user_repo(user)
        service = PlacementService(repo)
        db = _make_db_mock_with_preassessment()

        answers = _all_correct_answers()
        result = await service.score_placement_test(
            user_id=user.id,
            answers=answers,
            time_taken=1200,
            user_context={"professional_role": "", "country": ""},
            db=db,
        )

        assert result.assigned_level == 4
        assert result.score_percentage >= 80.0

    async def test_no_correct_answers_returns_level1(self):
        user = _make_user()
        repo = _make_user_repo(user)
        service = PlacementService(repo)
        db = _make_db_mock_with_preassessment()

        answers = {q_id: ("a" if _ANSWER_KEY[q_id] != "a" else "b") for q_id in _ANSWER_KEY}
        result = await service.score_placement_test(
            user_id=user.id,
            answers=answers,
            time_taken=1200,
            user_context={"professional_role": "", "country": ""},
            db=db,
        )

        assert result.assigned_level == 1

    async def test_level_scores_computed_per_level(self):
        user = _make_user()
        repo = _make_user_repo(user)
        service = PlacementService(repo)
        db = _make_db_mock_with_preassessment()

        answers = _answers_for_levels(1)
        answers.update(_wrong_answers_for_levels(2, 3, 4))
        result = await service.score_placement_test(
            user_id=user.id,
            answers=answers,
            time_taken=1200,
            user_context={"professional_role": "", "country": ""},
            db=db,
        )

        assert result.level_scores["level_1"] == 100.0
        assert result.level_scores["level_2"] == 0.0
        assert result.level_scores["level_3"] == 0.0
        assert result.level_scores["level_4"] == 0.0

    async def test_raises_if_user_not_found(self):
        repo = _make_user_repo(None)
        service = PlacementService(repo)
        db = AsyncMock()

        with pytest.raises(ValueError, match="not found"):
            await service.score_placement_test(
                user_id=uuid.uuid4(),
                answers={"1": "a"},
                time_taken=1200,
                user_context={},
                db=db,
            )

    async def test_raises_if_no_answers_provided(self):
        user = _make_user()
        repo = _make_user_repo(user)
        service = PlacementService(repo)
        db = AsyncMock()

        with pytest.raises(ValueError, match="No answers"):
            await service.score_placement_test(
                user_id=user.id,
                answers={},
                time_taken=1200,
                user_context={},
                db=db,
            )

    async def test_user_current_level_is_updated(self):
        user = _make_user(level=1)
        repo = _make_user_repo(user)
        service = PlacementService(repo)
        db = _make_db_mock_with_preassessment()

        answers = _all_correct_answers()
        await service.score_placement_test(
            user_id=user.id,
            answers=answers,
            time_taken=1200,
            user_context={},
            db=db,
        )

        repo.update.assert_called_once()
        assert user.current_level == 4

    async def test_result_has_required_fields(self):
        user = _make_user()
        repo = _make_user_repo(user)
        service = PlacementService(repo)
        db = _make_db_mock_with_preassessment()

        result = await service.score_placement_test(
            user_id=user.id,
            answers=_all_correct_answers(),
            time_taken=1200,
            user_context={},
            db=db,
        )

        assert isinstance(result, PlacementTestResult)
        assert 1 <= result.assigned_level <= 4
        assert 0.0 <= result.score_percentage <= 100.0
        assert isinstance(result.level_scores, dict)
        assert len(result.level_scores) == 4
        assert isinstance(result.competency_areas, list)
        assert isinstance(result.recommendations, list)


class TestGetPlacementResult:
    async def test_returns_none_if_user_at_level1(self):
        user = _make_user(level=1)
        service = PlacementService(_make_user_repo(user))
        result = await service.get_placement_result(user.id)
        assert result is None

    async def test_returns_none_if_user_not_found(self):
        service = PlacementService(_make_user_repo(None))
        result = await service.get_placement_result(uuid.uuid4())
        assert result is None

    async def test_returns_result_if_user_above_level1(self):
        user = _make_user(level=3)
        service = PlacementService(_make_user_repo(user))
        result = await service.get_placement_result(user.id)
        assert result is not None
        assert result.assigned_level == 3
