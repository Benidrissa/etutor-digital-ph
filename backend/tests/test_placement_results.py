"""Tests for placement test results endpoint and compute_domain_scores."""

from app.domain.services.placement_service import PlacementService


class TestComputeDomainScores:
    """Unit tests for PlacementService.compute_domain_scores."""

    def setup_method(self):
        from unittest.mock import AsyncMock

        self.service = PlacementService(user_repo=AsyncMock())

    def test_perfect_score_all_domains(self):
        answers = {
            "1": "c",
            "2": "a",
            "3": "b",
            "4": "d",
            "5": "a",
            "6": "b",
            "7": "c",
            "8": "a",
            "9": "d",
            "10": "b",
            "11": "a",
            "12": "c",
            "13": "b",
            "14": "a",
            "15": "d",
            "16": "b",
            "17": "c",
            "18": "a",
            "19": "b",
            "20": "d",
        }
        scores = self.service.compute_domain_scores(answers)

        assert scores["basic_public_health"] == 100.0
        assert scores["epidemiology"] == 100.0
        assert scores["biostatistics"] == 100.0
        assert scores["data_analysis"] == 100.0

    def test_zero_score_all_wrong(self):
        answers = {str(i): "z" for i in range(1, 21)}
        scores = self.service.compute_domain_scores(answers)

        for domain in ["basic_public_health", "epidemiology", "biostatistics", "data_analysis"]:
            assert scores[domain] == 0.0

    def test_partial_score(self):
        answers = {
            "1": "c",
            "2": "a",
            "3": "z",
            "4": "z",
            "5": "z",
        }
        scores = self.service.compute_domain_scores(answers)

        assert scores["basic_public_health"] == 40.0

    def test_empty_answers_returns_zeros(self):
        scores = self.service.compute_domain_scores({})

        for domain in ["basic_public_health", "epidemiology", "biostatistics", "data_analysis"]:
            assert scores[domain] == 0.0

    def test_returns_all_four_domains(self):
        scores = self.service.compute_domain_scores({})
        assert set(scores.keys()) == {
            "basic_public_health",
            "epidemiology",
            "biostatistics",
            "data_analysis",
        }
