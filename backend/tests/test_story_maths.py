"""Tests for the ``story-course/1`` maths engine (format Appendix A.6/A.7).

Every documented example in the spec's engine table is pinned here, because a
course file's answers are only as trustworthy as the engine that recomputes
them.
"""

from fractions import Fraction

import pytest

from app.ai.algorithms import story_maths as m

TIMES = "×"
DIVIDE = "÷"
MINUS = "−"


class TestEngineFunctionTable:
    """The worked examples printed in Appendix A.7."""

    def test_calc_honours_bidmas_exactly(self):
        assert m.calc(f"10 {MINUS} 2 {TIMES} (1 {MINUS} 4)²") == Fraction(-8)

    def test_round_dp_keeps_trailing_zero(self):
        assert m.round_dp(6.0954, 2) == "6.10"

    def test_round_sf(self):
        assert m.round_sf(0.04718, 2) == "0.047"

    def test_estimate_1sf_rounds_each_number_first(self):
        assert m.estimate_1sf(f"(7.8 {TIMES} 21.4) {DIVIDE} 0.39") == Fraction(400)

    def test_is_prime(self):
        assert m.is_prime(91) is False
        assert m.is_prime(31) is True

    def test_factors(self):
        assert m.factors(36) == [1, 2, 3, 4, 6, 9, 12, 18, 36]

    def test_multiples(self):
        assert m.multiples(12, 3) == [12, 24, 36]

    def test_primes_between(self):
        assert m.primes_between(30, 40) == [31, 37]

    def test_prime_factors(self):
        assert m.prime_factors(360) == [2, 2, 2, 3, 3, 5]

    def test_index_form(self):
        assert m.index_form(360) == f"2³ {TIMES} 3² {TIMES} 5"
        assert m.index_form(252) == f"2² {TIMES} 3² {TIMES} 7"

    def test_hcf_and_lcm(self):
        assert m.hcf(24, 36) == 12
        assert m.lcm(24, 36) == 72

    def test_add_minutes(self):
        assert m.add_minutes("08:00", 36) == "08:36"
        assert m.add_minutes("23:50", 20) == "00:10"

    def test_add_days(self):
        assert m.add_days("Monday", 12) == "Saturday"

    def test_digit_sum_and_alt_sum(self):
        assert m.digit_sum(7425) == 18
        assert m.alt_sum(5346) == 0
        assert m.alt_sum(121) == 0  # 121 = 11^2, the divisibility-by-11 test


class TestExactArithmetic:
    """Fractions, never binary floats."""

    def test_thirds_stay_exact(self):
        assert m.calc(f"1 {DIVIDE} 3") == Fraction(1, 3)

    def test_decimal_sum_has_no_float_drift(self):
        assert m.calc("0.1 + 0.2") == Fraction(3, 10)

    def test_superscript_binds_tighter_than_unary_minus(self):
        assert m.calc(f"{MINUS}3²") == Fraction(-9)

    def test_caret_power_also_works(self):
        assert m.calc("2^3 + 1") == Fraction(9)

    def test_thousands_space_reads_as_one_number(self):
        assert m.calc("4 284 + 1") == Fraction(4285)


class TestParserIsNotEval:
    """Authored expressions are data; nothing may execute."""

    @pytest.mark.parametrize(
        "expr",
        [
            "__import__('os')",
            "open('/etc/passwd')",
            "1 + x",
            "(1 + 2",
            "1 +",
            "",
            f"1 {DIVIDE} 0",
        ],
    )
    def test_rejected(self, expr):
        with pytest.raises(m.EngineError):
            m.calc(expr)


class TestNumberConventions:
    """Appendix A.2: decimal point, space thousands, U+2212 minus."""

    def test_thousands_grouping(self):
        assert m.format_number(Fraction(4284)) == "4 284"
        assert m.format_number(Fraction(12345)) == "12 345"
        assert m.format_number(Fraction(284)) == "284"

    def test_minus_sign(self):
        assert m.format_number(Fraction(-8)) == f"{MINUS}8"

    def test_parse_number_tolerates_learner_input(self):
        assert m.parse_number("4 284") == Fraction(4284)
        assert m.parse_number(f"{MINUS}12") == Fraction(-12)
        assert m.parse_number("12 cm") == Fraction(12)
        assert m.parse_number("3,25") == Fraction(13, 4)


class TestAnswerComparison:
    """Appendix C.2 — verify must equal answer, and traps must not."""

    def test_index_form_matches_regardless_of_typing(self):
        result = m.call("index_form", [360])
        assert m.answers_match(f"2³ {TIMES} 3² {TIMES} 5", result, fn="index_form")
        assert m.answers_match("2^3 x 3^2 x 5", result, fn="index_form")
        assert m.answers_match(f"3² {TIMES} 2³ {TIMES} 5", result, fn="index_form")

    def test_expanded_form_is_a_trap_not_the_answer(self):
        """``2 × 2 × 2 × 3 × 3 × 5`` is the m_not_index_form trap for 360.

        It must compare *different* from the answer, or the Appendix B example
        would ship a trap equal to its own answer.
        """
        result = m.call("index_form", [360])
        expanded = f"2 {TIMES} 2 {TIMES} 2 {TIMES} 3 {TIMES} 3 {TIMES} 5"
        assert not m.answers_match(expanded, result, fn="index_form")

    def test_lost_factor_trap_differs(self):
        result = m.call("index_form", [360])
        assert not m.answers_match(f"2³ {TIMES} 3 {TIMES} 5", result, fn="index_form")

    def test_is_index_form(self):
        assert m.is_index_form(f"2³ {TIMES} 3² {TIMES} 5")
        assert not m.is_index_form(f"2 {TIMES} 2 {TIMES} 2 {TIMES} 3 {TIMES} 3 {TIMES} 5")

    def test_rounding_compares_letter_by_letter(self):
        result = m.call("round_dp", [2.1, 1])
        assert m.answers_match("2.1", result)
        assert not m.answers_match("2.10", result)

    def test_numeric_answers_compare_by_value(self):
        result = m.call("calc", ["84 ÷ 12"])
        assert m.answers_match("7", result)
        assert m.answers_match(7, result)
        assert not m.answers_match("8", result)

    def test_list_answers_compare_elementwise(self):
        result = m.call("primes_between", [30, 40])
        assert m.answers_match([31, 37], result)
        assert m.answers_match("31, 37", result)
        assert not m.answers_match("31, 39", result)

    def test_boolean_answers(self):
        result = m.call("is_prime", [91])
        assert m.answers_match(False, result)
        assert m.answers_match("false", result)
        assert not m.answers_match(True, result)

    def test_unknown_function_is_reported(self):
        with pytest.raises(m.EngineError):
            m.call("surface_area_of_a_cone", [3])


class TestLadderSteps:
    """A.6 division_ladder photo shape, using the Appendix B D1 exercise."""

    GOOD = [
        {"p": 2, "n": 252},
        {"p": 2, "n": 126},
        {"p": 3, "n": 63},
        {"p": 3, "n": 21},
        {"p": 7, "n": 7},
    ]

    def test_worked_ladder_passes_its_own_check(self):
        """Appendix C.7: each exercise's worked ladder must pass its checker."""
        result = m.ladder_steps(self.GOOD, f"2² {TIMES} 3² {TIMES} 7", n=252)
        assert result.ok
        assert result.expected_final == f"2² {TIMES} 3² {TIMES} 7"

    def test_stopped_early(self):
        assert m.ladder_steps(self.GOOD[:4], None, n=252).error_code == "stopped_early"

    def test_divisor_not_prime(self):
        assert m.ladder_steps([{"p": 4, "n": 252}], None, n=252).error_code == "not_prime"

    def test_divisor_does_not_divide(self):
        assert m.ladder_steps([{"p": 5, "n": 252}], None, n=252).error_code == "not_a_divisor"

    def test_final_not_in_index_form(self):
        expanded = f"2 {TIMES} 2 {TIMES} 3 {TIMES} 3 {TIMES} 7"
        assert m.ladder_steps(self.GOOD, expanded, n=252).error_code == "not_index_form"

    def test_unreadable_when_empty(self):
        assert m.ladder_steps([], None, n=252).error_code == "unreadable"


class TestTreeSplits:
    """A.6 factor_tree photo shape."""

    GOOD = [
        {"n": 72, "into": [8, 9]},
        {"n": 8, "into": [2, 4]},
        {"n": 4, "into": [2, 2]},
        {"n": 9, "into": [3, 3]},
    ]

    def test_valid_tree(self):
        result = m.tree_splits(self.GOOD, f"2³ {TIMES} 3²", n=72)
        assert result.ok

    def test_split_that_does_not_multiply_back(self):
        result = m.tree_splits([{"n": 72, "into": [8, 10]}], None, n=72)
        assert result.error_code == "arithmetic"
        assert result.first_wrong == 0

    def test_leaf_that_is_not_prime(self):
        """A tree that stops before every leaf is prime is incomplete."""
        result = m.tree_splits([{"n": 72, "into": [8, 9]}], None, n=72)
        assert result.error_code in {"not_prime", "missing_factor"}


class TestCalcLines:
    """A.6 steps/lines photo shape."""

    def test_recomputes_each_line(self):
        steps = [{"expr": f"84 {DIVIDE} 12", "value": "7"}]
        assert m.calc_lines(steps, "7", expect=7).ok

    def test_catches_the_first_wrong_line(self):
        steps = [
            {"expr": "2 + 2", "value": "4"},
            {"expr": f"4 {TIMES} 3", "value": "11"},
            {"expr": "11 + 1", "value": "12"},
        ]
        result = m.calc_lines(steps, "12")
        assert result.error_code == "arithmetic"
        assert result.first_wrong == 1

    def test_wrong_final_answer(self):
        steps = [{"expr": "2 + 2", "value": "4"}]
        assert m.calc_lines(steps, "5", expect=4).error_code == "wrong_final"
