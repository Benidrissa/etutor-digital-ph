"""Tests for the backfill_legacy_figure_numbers script (#2055)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

# Load the script as a module without depending on packaging changes.
_SPEC = importlib.util.spec_from_file_location(
    "backfill_legacy_figure_numbers",
    Path(__file__).resolve().parent.parent / "scripts" / "backfill_legacy_figure_numbers.py",
)
assert _SPEC and _SPEC.loader, "spec must load"
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
_repair_one = _MOD._repair_one


class TestRepairOne:
    def test_recovers_dashed_subnumber(self):
        # Real legacy row: figure_number="FIGURE 2", caption starts with "6 ..."
        new_fn, new_cap = _repair_one("FIGURE 2", "6 Dotplot of Pulse Rates")
        assert new_fn == "FIGURE 2-6"
        assert new_cap == "Dotplot of Pulse Rates"

    def test_recovers_titlecase(self):
        new_fn, new_cap = _repair_one("Figure 1", "2 suggests we begin our prep")
        assert new_fn == "Figure 1-2"
        assert new_cap == "suggests we begin our prep"

    def test_strips_dash_after_number(self):
        new_fn, new_cap = _repair_one("FIGURE 2", "8 Pareto Chart")
        assert new_fn == "FIGURE 2-8"
        assert new_cap == "Pareto Chart"

    def test_already_has_subnumber_left_alone(self):
        # TABLE 1-2 was already correctly extracted, nothing to repair
        assert _repair_one("TABLE 1-2", "Levels of Measurement") is None

    def test_no_caption_skipped(self):
        assert _repair_one("Figure 2", None) is None
        assert _repair_one("Figure 2", "") is None

    def test_no_figure_number_skipped(self):
        assert _repair_one(None, "6 Dotplot") is None

    def test_caption_not_starting_with_digit_skipped(self):
        # Genuine chapter-only label, e.g. "Figure 1" with caption starting
        # with "(a)" — leave alone, not a severed-subnumber row
        assert _repair_one("Figure 1", "(a) Survey Results 2 CHAPTER 1") is None

    def test_dotted_subnumber_recovers(self):
        # Some textbooks use "1.5" rather than "1-5"
        new_fn, new_cap = _repair_one("Figure 1", "5 Distribution shapes")
        assert new_fn == "Figure 1-5"
        assert new_cap == "Distribution shapes"

    def test_multi_part_subnumber(self):
        # A leading "5.2" should fold to "Figure 1-5.2"
        new_fn, new_cap = _repair_one("Figure 1", "5.2 Sub-distribution")
        assert new_fn == "Figure 1-5.2"
        assert new_cap == "Sub-distribution"

    def test_strips_separator_chars(self):
        # The remainder after the number should drop leading punctuation
        new_fn, new_cap = _repair_one("FIGURE 3", "4 — A unicode em-dash caption")
        assert new_fn == "FIGURE 3-4"
        assert new_cap == "A unicode em-dash caption"
