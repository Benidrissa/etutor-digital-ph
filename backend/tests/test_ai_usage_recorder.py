"""Unit tests for the AI usage recorder, context, wrapper, and advice rules (#2629).

All pure-unit — the DB session factory is mocked so nothing here needs the
shared test_engine fixture (issue #554).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.providers.base import LLMResult
from app.ai.providers.recording import RecordingLLMProvider
from app.ai.usage_context import (
    ai_usage_context,
    current_ai_context,
    set_ai_context,
    set_ai_context_user,
)
from app.domain.services.ai_usage_service import (
    AiUsageAggregates,
    build_recommendations,
    record_ai_usage,
)

_SESSION_FACTORY = "app.domain.services.ai_usage_service._session_factory_for_loop"


def _mock_session_factory():
    """A ()-returning factory whose product is an async CM yielding a mock session."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=factory), session


# ---------------------------------------------------------------- context


def test_context_merge_semantics():
    user = uuid.uuid4()
    set_ai_context_user(user)
    with ai_usage_context("lesson_generation"):
        ctx = current_ai_context()
        assert ctx.feature == "lesson_generation"
        assert ctx.user_id == user  # inherited through the feature override
        with ai_usage_context("rag_query", only_if_unset=True):
            # a more specific feature is already set — rag_query must not clobber
            assert current_ai_context().feature == "lesson_generation"
    # reset on exit
    assert current_ai_context().feature is None


def test_set_ai_context_without_scope():
    course = uuid.uuid4()
    set_ai_context("tutor_chat", course_id=course)
    ctx = current_ai_context()
    assert ctx.feature == "tutor_chat"
    assert ctx.course_id == course


def test_set_ai_context_user_tolerates_garbage():
    set_ai_context_user("not-a-uuid")
    assert current_ai_context().user_id is None


# ---------------------------------------------------------------- recorder


@pytest.mark.asyncio
async def test_record_ai_usage_writes_row():
    factory, session = _mock_session_factory()
    with patch(_SESSION_FACTORY, factory), ai_usage_context("lesson_generation"):
        await record_ai_usage(
            provider="anthropic",
            model="claude-sonnet-4-6",
            operation="chat",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    assert session.add.call_count == 1
    event = session.add.call_args[0][0]
    assert event.feature == "lesson_generation"
    assert event.input_tokens == 100
    assert float(event.cost_cents) > 0
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_ai_usage_never_raises():
    factory = MagicMock(side_effect=RuntimeError("db down"))
    with patch(_SESSION_FACTORY, factory):
        # must swallow, not raise
        await record_ai_usage(provider="openai", model="gpt-image-1", operation="image")


@pytest.mark.asyncio
async def test_record_ai_usage_respects_kill_switch():
    factory, session = _mock_session_factory()
    with patch(_SESSION_FACTORY, factory), patch(
        "app.domain.services.ai_usage_service._tracking_enabled", return_value=False
    ):
        await record_ai_usage(provider="openai", model="whisper-1", operation="stt")
    session.add.assert_not_called()


# ---------------------------------------------------------------- wrapper


class _FakeProvider:
    supports_cache_control = True
    is_anthropic = True

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    async def complete(self, **kwargs):
        if self._error:
            raise self._error
        return self._result

    async def stream(self, **kwargs):
        yield "hello "
        yield "world"

    def build_tool_result_messages(self, results):
        return [{"role": "user", "content": "tool"}]


@pytest.mark.asyncio
async def test_wrapper_records_success_and_delegates():
    inner = _FakeProvider(
        result=LLMResult(text="ok", usage={"input_tokens": 10, "output_tokens": 5})
    )
    wrapped = RecordingLLMProvider(inner, "anthropic")
    assert wrapped.is_anthropic is True
    assert wrapped.supports_cache_control is True
    with patch(
        "app.domain.services.ai_usage_service.record_ai_usage", new=AsyncMock()
    ) as rec:
        result = await wrapped.complete(
            system="s", messages=[], max_tokens=10, temperature=0.0, model="claude-sonnet-4-6"
        )
    assert result.text == "ok"
    rec.assert_awaited_once()
    assert rec.call_args.kwargs["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert rec.call_args.kwargs["provider"] == "anthropic"


@pytest.mark.asyncio
async def test_wrapper_records_failure_and_reraises():
    inner = _FakeProvider(error=ValueError("boom"))
    wrapped = RecordingLLMProvider(inner, "openai")
    with patch(
        "app.domain.services.ai_usage_service.record_ai_usage", new=AsyncMock()
    ) as rec, pytest.raises(ValueError, match="boom"):
        await wrapped.complete(
            system="s", messages=[], max_tokens=10, temperature=0.0, model="gpt-5.4-nano"
        )
    assert rec.call_args.kwargs["success"] is False
    assert rec.call_args.kwargs["error_type"] == "ValueError"


@pytest.mark.asyncio
async def test_wrapper_stream_records_estimated_chars():
    wrapped = RecordingLLMProvider(_FakeProvider(), "anthropic")
    with patch(
        "app.domain.services.ai_usage_service.record_ai_usage", new=AsyncMock()
    ) as rec:
        chunks = [
            c
            async for c in wrapped.stream(
                system="s", user_message="m", max_tokens=10, temperature=0.0, model="claude-x"
            )
        ]
    assert "".join(chunks) == "hello world"
    assert rec.call_args.kwargs["characters"] == len("hello world")
    assert rec.call_args.kwargs["cost_estimated"] is True


# ---------------------------------------------------------------- advice rules


def test_recommendations_empty_on_no_usage():
    assert build_recommendations(AiUsageAggregates()) == []


def test_expensive_model_share_rule():
    agg = AiUsageAggregates(
        total_cost_cents=1000,
        chat_cost_cents=1000,
        chat_cost_by_model={"claude-opus-4-8": 800, "kimi-k2.6": 200},
        total_calls=10,
    )
    codes = [r["code"] for r in build_recommendations(agg)]
    assert "expensive_model_share" in codes


def test_reindexing_waste_and_failed_spend_rules():
    agg = AiUsageAggregates(
        total_cost_cents=500,
        total_calls=100,
        error_calls=10,
        failed_cost_cents=200,
        courses_reindexed=3,
        reindex_cost_cents=120,
    )
    recos = {r["code"]: r for r in build_recommendations(agg)}
    assert recos["reindexing_waste"]["data"]["courses"] == 3
    assert "failed_spend" in recos


def test_image_fallback_and_platform_key_rules():
    agg = AiUsageAggregates(
        total_cost_cents=100,
        total_calls=5,
        image_fallback_failures=2,
        image_openai_successes=2,
        tenant_key_calls=0,
    )
    codes = [r["code"] for r in build_recommendations(agg)]
    assert "image_fallback_active" in codes
    assert "platform_key_only" in codes


def test_low_cache_reuse_rule():
    agg = AiUsageAggregates(
        total_cost_cents=100,
        total_calls=5,
        cache_write_tokens=500_000,
        cache_read_tokens=10_000,
        anthropic_input_tokens=1_000_000,
        tenant_key_calls=1,
    )
    codes = [r["code"] for r in build_recommendations(agg)]
    assert "low_cache_reuse" in codes


def test_estimated_pricing_rule():
    agg = AiUsageAggregates(
        total_cost_cents=100,
        estimated_cost_cents=50,
        estimated_models=["mystery-model"],
        total_calls=5,
        tenant_key_calls=1,
    )
    recos = {r["code"]: r for r in build_recommendations(agg)}
    assert recos["add_pricing_for_models"]["data"]["models"] == ["mystery-model"]
