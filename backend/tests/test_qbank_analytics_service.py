"""Unit tests for qbank analytics pure helpers.

DB-backed tests are intentionally thin: the bulk of the logic lives in
pure-Python aggregation helpers (bucketing, category roll-up, trend detection)
which are exercised here without spinning up a session. Query correctness is
covered by the integration test in `test_qbank_analytics_endpoint` below.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.services.qbank_analytics_service import (
    build_attempts_over_time,
    build_category_pass_rates,
    build_score_distribution,
    trend_direction,
)


def test_score_distribution_buckets_inclusive_boundaries():
    scores = [0, 20, 21, 40, 41, 60, 61, 80, 81, 100]
    buckets = build_score_distribution(scores)
    counts_by_label = {b["bucket"]: b["count"] for b in buckets}
    assert counts_by_label == {
        "0-20": 2,
        "21-40": 2,
        "41-60": 2,
        "61-80": 2,
        "81-100": 2,
    }


def test_score_distribution_empty_returns_zero_buckets():
    buckets = build_score_distribution([])
    assert [b["count"] for b in buckets] == [0, 0, 0, 0, 0]
    assert [b["bucket"] for b in buckets] == ["0-20", "21-40", "41-60", "61-80", "81-100"]


def test_category_pass_rates_weak_flag_uses_threshold():
    breakdowns = [
        {"signs": {"correct": 4, "total": 5}, "rules": {"correct": 2, "total": 5}},
        {"signs": {"correct": 5, "total": 5}, "rules": {"correct": 3, "total": 5}},
    ]
    rates = build_category_pass_rates(breakdowns, pass_threshold=80.0)
    by_cat = {r["category"]: r for r in rates}
    assert by_cat["signs"]["pass_rate"] == 90.0
    assert by_cat["signs"]["weak"] is False
    assert by_cat["rules"]["pass_rate"] == 50.0
    assert by_cat["rules"]["weak"] is True
    # Weakest first so the UI can top-slice without re-sorting.
    assert rates[0]["category"] == "rules"


def test_category_pass_rates_skips_none_breakdowns():
    rates = build_category_pass_rates(
        [None, {"a": {"correct": 1, "total": 2}}, None], pass_threshold=80.0
    )
    assert len(rates) == 1
    assert rates[0]["category"] == "a"
    assert rates[0]["total"] == 2


def test_attempts_over_time_produces_dense_30_day_series():
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    series = build_attempts_over_time([(today, 3), (yesterday, 1)])
    assert len(series) == 30
    assert series[-1] == {"date": today.isoformat(), "count": 3}
    assert series[-2] == {"date": yesterday.isoformat(), "count": 1}
    # A middle date not in the input gets a zero so sparklines stay continuous.
    assert series[0]["count"] == 0


def test_trend_direction_detects_improvement_and_regression():
    assert trend_direction([]) == "flat"
    assert trend_direction([80.0]) == "flat"
    assert trend_direction([40.0, 50.0, 80.0, 90.0]) == "up"
    assert trend_direction([90.0, 80.0, 50.0, 40.0]) == "down"
    assert trend_direction([70.0, 71.0, 70.0, 72.0]) == "flat"
