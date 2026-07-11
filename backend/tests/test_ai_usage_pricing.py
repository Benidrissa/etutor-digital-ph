"""Unit tests for the extended pricing module (#2629) — pure, no DB."""

from app.ai.providers.pricing import (
    calculate_cost_cents,
    estimate_cost_cents,
    get_pricing,
    get_pricing_ex,
)


def test_known_model_not_estimated():
    row, estimated = get_pricing_ex("claude-sonnet-4-6")
    assert estimated is False
    assert row["input"] == 300


def test_unknown_model_flagged_estimated_with_default_rates():
    row, estimated = get_pricing_ex("some-future-model")
    assert estimated is True
    assert row == get_pricing("some-future-model")  # legacy default preserved


def test_chat_cost_fractional_cents():
    cents, estimated = estimate_cost_cents(
        model="claude-sonnet-4-6",
        operation="chat",
        usage={"input_tokens": 1000, "output_tokens": 1000},
    )
    # 1000 * 300/1M + 1000 * 1500/1M = 0.3 + 1.5 = 1.8 cents
    assert abs(cents - 1.8) < 1e-9
    assert estimated is False


def test_embedding_cost_does_not_round_to_zero():
    cents, estimated = estimate_cost_cents(
        model="text-embedding-3-small",
        operation="embedding",
        usage={"input_tokens": 500_000},
    )
    assert cents == 1.0  # 0.5M tokens * 2 cents/M
    assert estimated is False
    # The int-cents legacy path would floor this to 1 too, but small runs
    # must not vanish: 10k tokens = 0.02 cents.
    small, _ = estimate_cost_cents(
        model="text-embedding-3-small",
        operation="embedding",
        usage={"input_tokens": 10_000},
    )
    assert small > 0


def test_image_pricing_by_quality_and_unknown_model():
    known, estimated = estimate_cost_cents(
        model="gpt-image-1", operation="image", images_count=2, image_quality="medium"
    )
    assert known == 12.6
    assert estimated is False
    unknown, estimated2 = estimate_cost_cents(
        model="gemini-2.5-flash-image", operation="image", images_count=1
    )
    assert unknown > 0
    assert estimated2 is True


def test_tts_stt_realtime_estimates():
    tts, est1 = estimate_cost_cents(model="gpt-4o-mini-tts", operation="tts", characters=2000)
    assert abs(tts - 4.0) < 1e-9
    assert est1 is True

    stt, est2 = estimate_cost_cents(model="whisper-1", operation="stt", audio_seconds=120)
    assert abs(stt - 1.2) < 1e-9
    assert est2 is True

    rt, est3 = estimate_cost_cents(
        model="gpt-realtime-mini", operation="realtime", audio_seconds=60
    )
    assert abs(rt - 10.0) < 1e-9
    assert est3 is True


def test_legacy_int_cost_path_unchanged():
    # quality_agent_service depends on this exact behavior.
    cents = calculate_cost_cents(
        "claude-sonnet-4-6", {"input_tokens": 1_000_000, "output_tokens": 0}
    )
    assert cents == 300
