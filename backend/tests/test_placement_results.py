"""Unit tests for GET /placement-test/results endpoint logic."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.api.v1.schemas.placement import PlacementTestAttemptResponse


def _make_attempt(
    user_id: uuid.UUID | None = None,
    assigned_level: int = 2,
    raw_score: float = 55.0,
    adjusted_score: float = 57.0,
    domain_scores: dict | None = None,
    competency_areas: list | None = None,
    recommendations: list | None = None,
    attempted_at: datetime | None = None,
    can_retake_after: datetime | None = None,
) -> MagicMock:
    attempt = MagicMock()
    attempt.id = uuid.uuid4()
    attempt.user_id = user_id or uuid.uuid4()
    attempt.assigned_level = assigned_level
    attempt.raw_score = raw_score
    attempt.adjusted_score = adjusted_score
    attempt.domain_scores = (
        domain_scores
        if domain_scores is not None
        else {"level_1": 80.0, "level_2": 40.0, "level_3": 20.0, "level_4": 0.0}
    )
    attempt.competency_areas = competency_areas if competency_areas is not None else ["Public Health Foundations"]
    attempt.recommendations = recommendations if recommendations is not None else ["Start with Module 4"]
    attempt.attempted_at = attempted_at or datetime.utcnow()
    attempt.can_retake_after = can_retake_after
    return attempt


class TestPlacementTestAttemptResponse:
    def test_schema_from_attempt_fields(self):
        attempt = _make_attempt()
        response = PlacementTestAttemptResponse(
            id=str(attempt.id),
            assigned_level=attempt.assigned_level,
            raw_score=attempt.raw_score,
            adjusted_score=attempt.adjusted_score,
            domain_scores=attempt.domain_scores or {},
            competency_areas=attempt.competency_areas or [],
            recommendations=attempt.recommendations or [],
            attempted_at=attempt.attempted_at,
            can_retake_after=attempt.can_retake_after,
        )
        assert response.assigned_level == 2
        assert response.raw_score == 55.0
        assert response.adjusted_score == 57.0
        assert "level_1" in response.domain_scores
        assert response.can_retake_after is None

    def test_schema_with_retake_date(self):
        retake = datetime.utcnow() + timedelta(days=90)
        attempt = _make_attempt(can_retake_after=retake)
        response = PlacementTestAttemptResponse(
            id=str(attempt.id),
            assigned_level=attempt.assigned_level,
            raw_score=attempt.raw_score,
            adjusted_score=attempt.adjusted_score,
            domain_scores=attempt.domain_scores or {},
            competency_areas=attempt.competency_areas or [],
            recommendations=attempt.recommendations or [],
            attempted_at=attempt.attempted_at,
            can_retake_after=attempt.can_retake_after,
        )
        assert response.can_retake_after is not None
        assert response.can_retake_after > datetime.utcnow()

    def test_schema_level_bounds(self):
        for level in range(1, 5):
            attempt = _make_attempt(assigned_level=level)
            response = PlacementTestAttemptResponse(
                id=str(attempt.id),
                assigned_level=attempt.assigned_level,
                raw_score=attempt.raw_score,
                adjusted_score=attempt.adjusted_score,
                domain_scores=attempt.domain_scores or {},
                competency_areas=attempt.competency_areas or [],
                recommendations=attempt.recommendations or [],
                attempted_at=attempt.attempted_at,
                can_retake_after=attempt.can_retake_after,
            )
            assert 1 <= response.assigned_level <= 4

    def test_schema_empty_domain_scores(self):
        attempt = _make_attempt(domain_scores={})
        response = PlacementTestAttemptResponse(
            id=str(attempt.id),
            assigned_level=attempt.assigned_level,
            raw_score=attempt.raw_score,
            adjusted_score=attempt.adjusted_score,
            domain_scores=attempt.domain_scores if attempt.domain_scores is not None else {},
            competency_areas=attempt.competency_areas or [],
            recommendations=attempt.recommendations or [],
            attempted_at=attempt.attempted_at,
            can_retake_after=attempt.can_retake_after,
        )
        assert response.domain_scores == {}

    def test_schema_id_is_string(self):
        attempt = _make_attempt()
        response = PlacementTestAttemptResponse(
            id=str(attempt.id),
            assigned_level=attempt.assigned_level,
            raw_score=attempt.raw_score,
            adjusted_score=attempt.adjusted_score,
            domain_scores=attempt.domain_scores or {},
            competency_areas=attempt.competency_areas or [],
            recommendations=attempt.recommendations or [],
            attempted_at=attempt.attempted_at,
            can_retake_after=attempt.can_retake_after,
        )
        assert isinstance(response.id, str)
