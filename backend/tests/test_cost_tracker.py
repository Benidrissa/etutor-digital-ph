"""Tests for CostTracker service."""

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.services.cost_tracker import CostTracker


@pytest.fixture
def tracker():
    return CostTracker()


@pytest.fixture
def tracker_with_credit_service():
    credit_service = AsyncMock()
    credit_service.deduct = AsyncMock()
    return CostTracker(credit_service=credit_service), credit_service


def _make_anthropic_response(
    input_tokens: int, output_tokens: int, model: str = "claude-sonnet-4-6"
) -> MagicMock:
    response = MagicMock()
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    response.model = model
    return response


def _make_embedding_response(total_tokens: int) -> MagicMock:
    response = MagicMock()
    response.usage.total_tokens = total_tokens
    response.data = [MagicMock(object="text-embedding-3-small")]
    return response


class TestEstimateCost:
    def test_zero_tokens(self, tracker):
        result = tracker.estimate_cost(0, 0)
        assert result["credits"] == 0
        assert result["cost_usd"] == 0.0

    def test_1k_input_tokens_default_rates(self, tracker):
        result = tracker.estimate_cost(1000, 0)
        assert result["credits"] == math.ceil(1.0)
        assert result["credits"] == 1

    def test_1k_output_tokens_default_rates(self, tracker):
        result = tracker.estimate_cost(0, 1000)
        assert result["credits"] == math.ceil(3.0)
        assert result["credits"] == 3

    def test_mixed_tokens_rounds_up(self, tracker):
        result = tracker.estimate_cost(500, 500)
        expected = math.ceil((500 / 1000) * 1.0 + (500 / 1000) * 3.0)
        assert result["credits"] == expected

    def test_returns_cost_usd(self, tracker):
        result = tracker.estimate_cost(1000, 1000)
        assert result["cost_usd"] > 0.0

    def test_small_token_count_rounds_up_to_1(self, tracker):
        result = tracker.estimate_cost(1, 0)
        assert result["credits"] == 1


class TestCalcCredits:
    def test_basic_calculation(self):
        credits = CostTracker._calc_credits(1000, 1000, 1.0, 3.0)
        assert credits == 4

    def test_ceiling_applied(self):
        credits = CostTracker._calc_credits(100, 0, 1.0, 3.0)
        assert credits == math.ceil(0.1)
        assert credits == 1

    def test_zero_tokens(self):
        assert CostTracker._calc_credits(0, 0, 1.0, 3.0) == 0

    def test_custom_rates(self):
        credits = CostTracker._calc_credits(2000, 1000, 2.0, 5.0)
        assert credits == math.ceil(4.0 + 5.0)
        assert credits == 9


class TestCalcEmbeddingCredits:
    def test_basic(self):
        credits = CostTracker._calc_embedding_credits(1000, 0.1)
        assert credits == 1

    def test_rounding_up(self):
        credits = CostTracker._calc_embedding_credits(100, 0.1)
        assert credits == math.ceil(0.01)
        assert credits == 1

    def test_zero(self):
        assert CostTracker._calc_embedding_credits(0, 0.1) == 0


class TestTrackAnthropicCall:
    @pytest.mark.asyncio
    async def test_returns_usage_dict(self, tracker):
        response = _make_anthropic_response(1000, 500)
        result = await tracker.track_anthropic_call(response, None, "lesson")
        assert result["input_tokens"] == 1000
        assert result["output_tokens"] == 500
        assert result["credits"] > 0
        assert result["cost_usd"] > 0.0

    @pytest.mark.asyncio
    async def test_no_session_no_db_write(self, tracker):
        response = _make_anthropic_response(1000, 500)
        result = await tracker.track_anthropic_call(response, uuid.uuid4(), "lesson", session=None)
        assert result["input_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_no_user_id_no_deduct(self, tracker_with_credit_service):
        tracker, credit_service = tracker_with_credit_service
        response = _make_anthropic_response(1000, 500)
        session = AsyncMock()
        await tracker.track_anthropic_call(response, None, "lesson", session=session)
        credit_service.deduct.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_user_id_and_session_deducts_credits(self, tracker_with_credit_service):
        tracker, credit_service = tracker_with_credit_service
        response = _make_anthropic_response(1000, 1000)
        user_id = uuid.uuid4()
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()

        with patch.object(tracker, "_write_usage_log", new_callable=AsyncMock):
            await tracker.track_anthropic_call(response, user_id, "quiz", session=session)

        credit_service.deduct.assert_called_once()
        call_kwargs = credit_service.deduct.call_args.kwargs
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["amount"] > 0
        assert "quiz" in call_kwargs["reason"]

    @pytest.mark.asyncio
    async def test_credit_calculation_matches_estimate(self, tracker):
        input_tokens, output_tokens = 2000, 1000
        response = _make_anthropic_response(input_tokens, output_tokens)
        result = await tracker.track_anthropic_call(response, None, "lesson")
        estimate = tracker.estimate_cost(input_tokens, output_tokens)
        assert result["credits"] == estimate["credits"]

    @pytest.mark.asyncio
    async def test_missing_usage_attr_defaults_to_zero(self, tracker):
        response = MagicMock()
        response.usage.input_tokens = 0
        response.usage.output_tokens = 0
        response.model = "claude-sonnet-4-6"
        result = await tracker.track_anthropic_call(response, None, "test")
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0


class TestTrackEmbeddingCall:
    @pytest.mark.asyncio
    async def test_returns_usage_dict(self, tracker):
        response = _make_embedding_response(1000)
        result = await tracker.track_embedding_call(response, None, "rag_index")
        assert result["total_tokens"] == 1000
        assert result["credits"] >= 1
        assert result["cost_usd"] >= 0.0

    @pytest.mark.asyncio
    async def test_no_user_no_deduct(self, tracker_with_credit_service):
        tracker, credit_service = tracker_with_credit_service
        response = _make_embedding_response(500)
        session = AsyncMock()
        await tracker.track_embedding_call(response, None, "rag", session=session)
        credit_service.deduct.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_user_deducts(self, tracker_with_credit_service):
        tracker, credit_service = tracker_with_credit_service
        response = _make_embedding_response(1000)
        user_id = uuid.uuid4()
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()

        with patch.object(tracker, "_write_usage_log", new_callable=AsyncMock):
            await tracker.track_embedding_call(response, user_id, "query_embed", session=session)

        credit_service.deduct.assert_called_once()
        call_kwargs = credit_service.deduct.call_args.kwargs
        assert call_kwargs["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_zero_tokens(self, tracker):
        response = _make_embedding_response(0)
        result = await tracker.track_embedding_call(response, None, "test")
        assert result["total_tokens"] == 0
        assert result["credits"] == 0


class TestDeductWithNoCreditService:
    @pytest.mark.asyncio
    async def test_logs_warning_without_raising(self, tracker):
        with patch("app.domain.services.cost_tracker.logger") as mock_logger:
            session = AsyncMock()
            await tracker._deduct(uuid.uuid4(), 5, "lesson", session)
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_credits_skipped(self, tracker):
        with patch("app.domain.services.cost_tracker.logger") as mock_logger:
            session = AsyncMock()
            await tracker._deduct(uuid.uuid4(), 0, "lesson", session)
            mock_logger.warning.assert_not_called()


class TestWriteUsageLogFailure:
    @pytest.mark.asyncio
    async def test_db_error_is_swallowed(self, tracker):
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=Exception("table does not exist"))
        session.flush = AsyncMock()

        await tracker._write_usage_log(
            user_id=uuid.uuid4(),
            api_provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            credits=4,
            cost_usd=0.009,
            context="lesson",
            session=session,
        )


class TestSettingsRateReading:
    def test_default_rates_are_floats(self, tracker):
        assert isinstance(tracker._rate_input(), float)
        assert isinstance(tracker._rate_output(), float)
        assert isinstance(tracker._rate_embedding(), float)

    def test_default_rate_values(self, tracker):
        assert tracker._rate_input() == 1.0
        assert tracker._rate_output() == 3.0
        assert tracker._rate_embedding() == 0.1
