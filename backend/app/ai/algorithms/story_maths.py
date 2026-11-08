"""Maths engine v1 for the ``story-course/1`` course format.

Every answer in a story course that maths can check carries a ``verify`` call
(format Appendix A.7). The app and the validator both recompute the answer with
this engine, so a course file can never ship an answer the engine disagrees
with.

Two hard rules shape this module:

* **Exact arithmetic.** Everything flows through :class:`fractions.Fraction`,
  never binary floats, so ``1 ÷ 3`` stays a third and ``round_dp`` rounds the
  number the author wrote rather than its float approximation.
* **No ``eval``.** Expressions come from authored course files, which are data,
  so they are parsed by the recursive-descent parser below and nothing else.

The engine also backs the paper-exercise photo checks (Appendix A.6): an AI
copies the child's handwritten working into a JSON shape, and the step checkers
here — never the AI — decide which step is first wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

__all__ = [
    "ENGINE_FUNCTIONS",
    "EngineError",
    "StepCheck",
    "answers_match",
    "call",
    "calc",
    "calc_lines",
    "format_number",
    "index_form",
    "is_index_form",
    "ladder_steps",
    "parse_number",
    "tree_splits",
]

# Error codes shared with the app's photo-check flow (Appendix A.6).
ERR_ARITHMETIC = "arithmetic"
ERR_NOT_PRIME = "not_prime"
ERR_NOT_A_DIVISOR = "not_a_divisor"
ERR_STOPPED_EARLY = "stopped_early"
ERR_MISSING_FACTOR = "missing_factor"
ERR_NOT_INDEX_FORM = "not_index_form"
ERR_WRONG_FINAL = "wrong_final"
ERR_UNREADABLE = "unreadable"

MINUS = "−"  # U+2212 MINUS SIGN, the sign A.2 mandates in authored text
TIMES = "×"
DIVIDE = "÷"

_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUPERSCRIPT_TO_ASCII = {ch: str(i) for i, ch in enumerate(_SUPERSCRIPT_DIGITS)}

_WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


class EngineError(ValueError):
    """Raised when an expression cannot be parsed or a function is misused.

    Carries an Appendix A.6 ``code`` so callers can turn the failure straight
    into a learner-facing error code instead of re-classifying the message.
    """

    def __init__(self, message: str, code: str = ERR_ARITHMETIC) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Expression lexer + parser (BIDMAS, exact)
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# A thousands group is a space (or thin/narrow space) followed by exactly three
# digits that are not themselves followed by another digit: "4 284", never the
# "4" and "284" of "4 284" read as two operands.
_THOUSANDS_RE = re.compile(r"[    ](\d{3})(?!\d)")


@dataclass(frozen=True)
class _Token:
    kind: str  # "num" | "op" | "lparen" | "rparen" | "pow"
    text: str
    value: Fraction | int | None = None


def _normalize_expr(expr: str) -> str:
    """Fold the authored Unicode operators onto ASCII the lexer understands."""
    return (
        expr.replace(MINUS, "-")
        .replace("–", "-")  # en dash, a common typo for the minus sign
        .replace("—", "-")
        .replace(TIMES, "*")
        .replace("⋅", "*")
        .replace(DIVIDE, "/")
        .replace("∕", "/")
        .replace(",", "")  # thousands commas; A.2 forbids the decimal comma here
    )


def _tokenize(expr: str) -> list[_Token]:
    """Turn an expression into tokens, resolving thousands spaces and powers."""
    text = _normalize_expr(expr)
    tokens: list[_Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        # Superscripts must be tested before the number branch: "²".isdigit()
        # is True in Python, but the \d of _NUMBER_RE only matches decimal
        # digits, so a superscript would otherwise fall into the number branch
        # and fail to match.
        if ch in _SUPERSCRIPT_TO_ASCII:
            digits = ""
            while i < n and text[i] in _SUPERSCRIPT_TO_ASCII:
                digits += _SUPERSCRIPT_TO_ASCII[text[i]]
                i += 1
            tokens.append(_Token("pow", digits, int(digits)))
            continue
        if ch.isdecimal() or (ch == "." and i + 1 < n and text[i + 1].isdecimal()):
            match = _NUMBER_RE.match(text, i)
            if match is None:  # pragma: no cover - guarded by the isdigit test
                raise EngineError(f"Bad number at position {i} in {expr!r}")
            literal = match.group(0)
            i = match.end()
            # Absorb any thousands groups that follow.
            while True:
                grouped = _THOUSANDS_RE.match(text, i)
                if grouped is None or "." in literal:
                    break
                literal += grouped.group(1)
                i = grouped.end()
            tokens.append(_Token("num", literal, Fraction(Decimal(literal))))
            continue
        if ch == "^":
            tokens.append(_Token("op", "^"))
            i += 1
            continue
        if ch in "+-*/":
            tokens.append(_Token("op", ch))
            i += 1
            continue
        if ch == "(":
            tokens.append(_Token("lparen", ch))
            i += 1
            continue
        if ch == ")":
            tokens.append(_Token("rparen", ch))
            i += 1
            continue
        raise EngineError(f"Unexpected character {ch!r} in {expr!r}")
    return tokens


class _Parser:
    """Recursive-descent parser enforcing BIDMAS over exact fractions."""

    def __init__(self, tokens: list[_Token], source: str) -> None:
        self._tokens = tokens
        self._source = source
        self._pos = 0

    def parse(self) -> Fraction:
        if not self._tokens:
            raise EngineError(f"Empty expression {self._source!r}")
        value = self._parse_sum()
        if self._pos != len(self._tokens):
            tok = self._tokens[self._pos]
            raise EngineError(f"Trailing {tok.text!r} in {self._source!r}")
        return value

    def _peek(self) -> _Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _parse_sum(self) -> Fraction:
        value = self._parse_product()
        while (tok := self._peek()) is not None and tok.kind == "op" and tok.text in "+-":
            self._pos += 1
            rhs = self._parse_product()
            value = value + rhs if tok.text == "+" else value - rhs
        return value

    def _parse_product(self) -> Fraction:
        value = self._parse_unary()
        while (tok := self._peek()) is not None and tok.kind == "op" and tok.text in "*/":
            self._pos += 1
            rhs = self._parse_unary()
            if tok.text == "/":
                if rhs == 0:
                    raise EngineError(f"Division by zero in {self._source!r}")
                value = value / rhs
            else:
                value = value * rhs
        return value

    def _parse_unary(self) -> Fraction:
        tok = self._peek()
        if tok is not None and tok.kind == "op" and tok.text in "+-":
            self._pos += 1
            value = self._parse_unary()
            return -value if tok.text == "-" else value
        return self._parse_power()

    def _parse_power(self) -> Fraction:
        base = self._parse_atom()
        while (tok := self._peek()) is not None and tok.kind in {"pow", "op"}:
            if tok.kind == "pow":
                self._pos += 1
                base = self._int_power(base, int(tok.text))
                continue
            if tok.text != "^":
                break
            self._pos += 1
            exponent = self._parse_unary()
            if exponent.denominator != 1:
                raise EngineError(f"Only whole-number powers are supported in {self._source!r}")
            base = self._int_power(base, int(exponent))
        return base

    def _int_power(self, base: Fraction, exponent: int) -> Fraction:
        if exponent < 0 and base == 0:
            raise EngineError(f"Division by zero in {self._source!r}")
        return base**exponent

    def _parse_atom(self) -> Fraction:
        tok = self._peek()
        if tok is None:
            raise EngineError(f"Expression ends early: {self._source!r}")
        if tok.kind == "num":
            self._pos += 1
            assert tok.value is not None
            return Fraction(tok.value)
        if tok.kind == "lparen":
            self._pos += 1
            value = self._parse_sum()
            closing = self._peek()
            if closing is None or closing.kind != "rparen":
                raise EngineError(f"Missing ')' in {self._source!r}")
            self._pos += 1
            return value
        raise EngineError(f"Unexpected {tok.text!r} in {self._source!r}")


def calc(expr: str | int | float | Fraction) -> Fraction:
    """Evaluate ``expr`` exactly, honouring BIDMAS.

    >>> calc("10 − 2 × (1 − 4)²")
    Fraction(-8, 1)
    """
    if isinstance(expr, Fraction):
        return expr
    if isinstance(expr, int):
        return Fraction(expr)
    if isinstance(expr, float):
        return Fraction(Decimal(str(expr)))
    return _Parser(_tokenize(expr), expr).parse()


# ---------------------------------------------------------------------------
# Number parsing + formatting (Appendix A.2 conventions)
# ---------------------------------------------------------------------------


def parse_number(text: str | int | float | Fraction) -> Fraction:
    """Read a learner-or-author written number as an exact fraction.

    Tolerates the forms A.5 says the app accepts: thousands spaces/commas, the
    U+2212 minus, and a stray unit suffix. A decimal comma is accepted here so
    the validator can compare an authored ``3,25`` against ``3.25``; the app is
    what shows the "use a decimal point" reminder.
    """
    if isinstance(text, Fraction):
        return text
    if isinstance(text, int):
        return Fraction(text)
    if isinstance(text, float):
        return Fraction(Decimal(str(text)))

    cleaned = text.strip().replace(MINUS, "-")
    for ch in (" ", " ", " ", " "):
        cleaned = cleaned.replace(ch, "")
    # A comma is a decimal separator only when it is the sole comma and is not
    # acting as a thousands group (i.e. not followed by exactly three digits).
    if cleaned.count(",") == 1 and not re.search(r",\d{3}(?!\d)", cleaned):
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    # Drop a trailing unit ("12 cm" -> "12"), keeping digits, sign and point.
    match = re.match(r"^[-+]?\d*\.?\d+", cleaned)
    if match is None:
        raise EngineError(f"Cannot read {text!r} as a number")
    return Fraction(Decimal(match.group(0)))


def format_number(value: Fraction | int, *, group: bool = True) -> str:
    """Render a value in the A.2 conventions: decimal point, space thousands.

    Non-terminating fractions fall back to a 6-decimal rendering; authored
    answers are expected to be exact, so this only shows up in error messages.
    """
    frac = Fraction(value)
    if frac.denominator == 1:
        digits = str(abs(frac.numerator))
        if group:
            digits = _group_thousands(digits)
        return (MINUS if frac < 0 else "") + digits

    with localcontext() as ctx:
        ctx.prec = 40
        dec = Decimal(frac.numerator) / Decimal(frac.denominator)
    text = format(dec.normalize(), "f")
    if len(text.split(".")[-1]) > 6:
        text = str(round(dec, 6))
    sign = MINUS if text.startswith("-") else ""
    text = text.lstrip("-")
    whole, _, decimals = text.partition(".")
    if group:
        whole = _group_thousands(whole)
    return sign + (f"{whole}.{decimals}" if decimals else whole)


def _group_thousands(digits: str) -> str:
    if len(digits) <= 4:
        # A.2's own example groups 4 284, so group from four digits up.
        return f"{digits[0]} {digits[1:]}" if len(digits) == 4 else digits
    out = ""
    for idx, ch in enumerate(reversed(digits)):
        if idx and idx % 3 == 0:
            out = " " + out
        out = ch + out
    return out


def _to_superscript(number: int) -> str:
    return "".join(_SUPERSCRIPT_DIGITS[int(d)] for d in str(number))


# ---------------------------------------------------------------------------
# Rounding (returns exact text, so trailing zeros survive)
# ---------------------------------------------------------------------------


def _as_decimal(value: str | int | float | Fraction) -> Decimal:
    frac = parse_number(value) if isinstance(value, str) else Fraction(value)
    with localcontext() as ctx:
        ctx.prec = 50
        return Decimal(frac.numerator) / Decimal(frac.denominator)


def round_dp(value: str | int | float | Fraction, places: int) -> str:
    """Round to ``places`` decimals and return text, keeping trailing zeros.

    >>> round_dp(6.0954, 2)
    '6.10'
    """
    if places < 0:
        raise EngineError("round_dp needs a non-negative number of places")
    quantum = Decimal(1).scaleb(-places)
    rounded = _as_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:.{places}f}"


def round_sf(value: str | int | float | Fraction, figures: int) -> str:
    """Round to ``figures`` significant figures and return text.

    >>> round_sf(0.04718, 2)
    '0.047'
    """
    if figures < 1:
        raise EngineError("round_sf needs at least one significant figure")
    dec = _as_decimal(value)
    if dec == 0:
        return "0"
    exponent = dec.adjusted()
    decimals = figures - 1 - exponent
    if decimals >= 0:
        quantum = Decimal(1).scaleb(-decimals)
        rounded = dec.quantize(quantum, rounding=ROUND_HALF_UP)
        # Rounding can carry into a new digit (9.99 -> 10.0 at 2 s.f.); redo
        # once at the new magnitude so the figure count stays right.
        if rounded != 0 and rounded.adjusted() != exponent:
            decimals = figures - 1 - rounded.adjusted()
            if decimals < 0:
                return _round_to_tens(dec, -decimals)
            rounded = dec.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        return f"{rounded:.{max(decimals, 0)}f}"
    return _round_to_tens(dec, -decimals)


def _round_to_tens(dec: Decimal, zeros: int) -> str:
    """Round to a multiple of 10**zeros, rendered without a decimal point."""
    scale = Decimal(1).scaleb(zeros)
    rounded = (dec / scale).quantize(Decimal(1), rounding=ROUND_HALF_UP) * scale
    return f"{rounded:.0f}"


def estimate_1sf(expr: str) -> Fraction:
    """Round every number in ``expr`` to 1 s.f., then evaluate.

    >>> estimate_1sf("(7.8 × 21.4) ÷ 0.39")
    Fraction(400, 1)
    """
    tokens = _tokenize(expr)
    rebuilt: list[str] = []
    for tok in tokens:
        if tok.kind == "num":
            rebuilt.append(round_sf(Fraction(Decimal(tok.text)), 1))
        elif tok.kind == "pow":
            rebuilt.append(f"^{tok.text}")
        else:
            rebuilt.append(tok.text)
    return calc(" ".join(rebuilt))


# ---------------------------------------------------------------------------
# Number theory
# ---------------------------------------------------------------------------


def _as_int(value: str | int | float | Fraction, name: str) -> int:
    frac = parse_number(value) if isinstance(value, str) else Fraction(value)
    if frac.denominator != 1:
        raise EngineError(f"{name} needs a whole number, got {value!r}")
    return int(frac)


def is_prime(n: str | int) -> bool:
    """>>> is_prime(91)
    False
    """
    value = _as_int(n, "is_prime")
    if value < 2:
        return False
    if value < 4:
        return True
    if value % 2 == 0:
        return False
    divisor = 3
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += 2
    return True


def factors(n: str | int) -> list[int]:
    """Every factor of ``n``, ascending.

    >>> factors(36)
    [1, 2, 3, 4, 6, 9, 12, 18, 36]
    """
    value = _as_int(n, "factors")
    if value < 1:
        raise EngineError("factors needs a positive whole number")
    small: list[int] = []
    large: list[int] = []
    divisor = 1
    while divisor * divisor <= value:
        if value % divisor == 0:
            small.append(divisor)
            partner = value // divisor
            if partner != divisor:
                large.append(partner)
        divisor += 1
    return small + large[::-1]


def multiples(n: str | int, count: str | int) -> list[int]:
    """The first ``count`` multiples of ``n``.

    >>> multiples(12, 3)
    [12, 24, 36]
    """
    value = _as_int(n, "multiples")
    how_many = _as_int(count, "multiples")
    if how_many < 0:
        raise EngineError("multiples needs a non-negative count")
    return [value * k for k in range(1, how_many + 1)]


def primes_between(low: str | int, high: str | int) -> list[int]:
    """Primes from ``low`` to ``high`` inclusive.

    >>> primes_between(30, 40)
    [31, 37]
    """
    start = _as_int(low, "primes_between")
    end = _as_int(high, "primes_between")
    if start > end:
        start, end = end, start
    return [n for n in range(max(start, 2), end + 1) if is_prime(n)]


def prime_factors(n: str | int) -> list[int]:
    """Prime factorisation with repeats, ascending.

    >>> prime_factors(360)
    [2, 2, 2, 3, 3, 5]
    """
    value = _as_int(n, "prime_factors")
    if value < 2:
        raise EngineError("prime_factors needs a whole number above 1")
    out: list[int] = []
    for prime in (2, 3):
        while value % prime == 0:
            out.append(prime)
            value //= prime
    divisor = 5
    step = 2
    while divisor * divisor <= value:
        while value % divisor == 0:
            out.append(divisor)
            value //= divisor
        divisor += step
        step = 6 - step  # 5, 7, 11, 13, ... skipping multiples of 2 and 3
    if value > 1:
        out.append(value)
    return out


def index_form(n: str | int) -> str:
    """Prime factorisation in index form, using superscripts and ×.

    >>> index_form(360)
    '2³ × 3² × 5'
    """
    primes = prime_factors(n)
    parts: list[str] = []
    for prime in dict.fromkeys(primes):
        power = primes.count(prime)
        parts.append(f"{prime}{_to_superscript(power)}" if power > 1 else str(prime))
    return f" {TIMES} ".join(parts)


def hcf(*values: str | int) -> int:
    """>>> hcf(24, 36)
    12
    """
    from math import gcd

    if not values:
        raise EngineError("hcf needs at least one number")
    numbers = [abs(_as_int(v, "hcf")) for v in values]
    result = numbers[0]
    for number in numbers[1:]:
        result = gcd(result, number)
    return result


def lcm(*values: str | int) -> int:
    """>>> lcm(24, 36)
    72
    """
    from math import lcm as _lcm

    if not values:
        raise EngineError("lcm needs at least one number")
    numbers = [abs(_as_int(v, "lcm")) for v in values]
    if 0 in numbers:
        raise EngineError("lcm needs non-zero numbers")
    return _lcm(*numbers)


def digit_sum(n: str | int) -> int:
    """>>> digit_sum(7425)
    18
    """
    return sum(int(d) for d in str(abs(_as_int(n, "digit_sum"))))


def alt_sum(n: str | int) -> int:
    """Alternating digit sum from the right — the divisibility-by-11 test.

    >>> alt_sum(5346)
    0
    """
    digits = [int(d) for d in str(abs(_as_int(n, "alt_sum")))][::-1]
    return sum(d if i % 2 == 0 else -d for i, d in enumerate(digits))


# ---------------------------------------------------------------------------
# Time and days
# ---------------------------------------------------------------------------


def add_minutes(time_text: str, minutes: str | int) -> str:
    """Add minutes to a ``hh:mm`` clock time, wrapping at midnight.

    >>> add_minutes("08:00", 36)
    '08:36'
    """
    match = re.match(r"^\s*(\d{1,2})\s*[:h.]\s*(\d{1,2})\s*$", str(time_text))
    if match is None:
        raise EngineError(f"Cannot read {time_text!r} as a hh:mm time")
    hours, mins = int(match.group(1)), int(match.group(2))
    if hours > 23 or mins > 59:
        raise EngineError(f"{time_text!r} is not a valid time")
    total = (hours * 60 + mins + _as_int(minutes, "add_minutes")) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def add_days(day_name: str, days: str | int) -> str:
    """Advance a weekday name by ``days``.

    >>> add_days("Monday", 12)
    'Saturday'
    """
    wanted = str(day_name).strip().lower()
    for index, name in enumerate(_WEEKDAYS):
        if name.lower() == wanted:
            return _WEEKDAYS[(index + _as_int(days, "add_days")) % 7]
    raise EngineError(f"{day_name!r} is not an English weekday name")


# ---------------------------------------------------------------------------
# Photo-check step checkers (Appendix A.6)
# ---------------------------------------------------------------------------


@dataclass
class StepCheck:
    """Outcome of checking copied handwritten working.

    ``first_wrong`` indexes the earliest bad step, which is the only step the
    AI is allowed to write a hint about.
    """

    ok: bool
    error_code: str | None = None
    first_wrong: int | None = None
    detail: str = ""
    expected_final: str = ""


def _final_matches(final: object, expected: Fraction | str) -> bool:
    if final is None:
        return False
    text = str(final).strip()
    if isinstance(expected, str):
        return _normalize_index_form(text) == _normalize_index_form(expected)
    try:
        return parse_number(text) == expected
    except EngineError:
        return False


def calc_lines(steps: list[dict], final: object = None, *, expect: object = None) -> StepCheck:
    """Recompute every copied ``{"expr", "value"}`` line in order."""
    if not steps:
        return StepCheck(False, ERR_UNREADABLE, None, "no steps copied")
    for index, step in enumerate(steps):
        expr = str(step.get("expr", "")).strip()
        if not expr:
            return StepCheck(False, ERR_UNREADABLE, index, "missing expression")
        try:
            computed = calc(expr)
        except EngineError as exc:
            return StepCheck(False, ERR_ARITHMETIC, index, str(exc))
        if "value" not in step:
            continue
        try:
            written = parse_number(str(step["value"]))
        except EngineError:
            return StepCheck(False, ERR_UNREADABLE, index, "unreadable value")
        if written != computed:
            return StepCheck(
                False,
                ERR_ARITHMETIC,
                index,
                f"{expr} is {format_number(computed)}, not {format_number(written)}",
            )
    if expect is not None:
        expected = expect if isinstance(expect, str) else parse_number(expect)
        if not _final_matches(final, expected):
            return StepCheck(False, ERR_WRONG_FINAL, len(steps) - 1, "final answer differs")
    return StepCheck(True, expected_final=str(final or ""))


def _root_number(declared: str | int | None, rows: list[dict], name: str) -> int:
    """The number the working starts from: the declared ``n``, else the top row."""
    if declared is not None:
        return _as_int(declared, name)
    return _as_int(rows[0].get("n"), name)


def tree_splits(
    splits: list[dict], final: object = None, *, n: str | int | None = None
) -> StepCheck:
    """Check a factor tree: every split multiplies back, every leaf is prime."""
    if not splits:
        return StepCheck(False, ERR_UNREADABLE, None, "no splits copied")
    produced: dict[int, list[int]] = {}
    for index, split in enumerate(splits):
        try:
            parent = _as_int(split.get("n"), "tree_splits")
            children = [_as_int(c, "tree_splits") for c in split.get("into", [])]
        except EngineError:
            return StepCheck(False, ERR_UNREADABLE, index, "unreadable split")
        if len(children) < 2:
            return StepCheck(False, ERR_MISSING_FACTOR, index, f"{parent} split into one part")
        product = 1
        for child in children:
            product *= child
        if product != parent:
            return StepCheck(
                False,
                ERR_ARITHMETIC,
                index,
                f"{' × '.join(str(c) for c in children)} is {product}, not {parent}",
            )
        produced[parent] = children

    root = _root_number(n, splits, "tree_splits")
    if root not in produced:
        return StepCheck(False, ERR_MISSING_FACTOR, 0, f"the tree never splits {root}")

    leaves: list[int] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node in produced:
            stack.extend(produced[node])
        else:
            leaves.append(node)
    for index, leaf in enumerate(sorted(leaves)):
        if not is_prime(leaf):
            return StepCheck(False, ERR_NOT_PRIME, index, f"{leaf} is not prime")
    if sorted(leaves) != prime_factors(root):
        return StepCheck(False, ERR_MISSING_FACTOR, 0, "the leaves do not rebuild the number")
    if final is not None and not _final_matches(final, index_form(root)):
        return StepCheck(False, ERR_NOT_INDEX_FORM, None, "final is not the index form")
    return StepCheck(True, expected_final=index_form(root))


def ladder_steps(
    rows: list[dict], final: object = None, *, n: str | int | None = None
) -> StepCheck:
    """Check a division ladder: prime divisors, exact division, ending at 1."""
    if not rows:
        return StepCheck(False, ERR_UNREADABLE, None, "no rows copied")
    try:
        root = _root_number(n, rows, "ladder_steps")
    except EngineError:
        return StepCheck(False, ERR_UNREADABLE, 0, "unreadable starting number")
    current = root

    for index, row in enumerate(rows):
        try:
            prime = _as_int(row.get("p"), "ladder_steps")
            written = _as_int(row.get("n"), "ladder_steps")
        except EngineError:
            return StepCheck(False, ERR_UNREADABLE, index, "unreadable row")
        if written != current:
            return StepCheck(False, ERR_ARITHMETIC, index, f"this row should start from {current}")
        if not is_prime(prime):
            return StepCheck(False, ERR_NOT_PRIME, index, f"{prime} is not prime")
        if current % prime != 0:
            return StepCheck(False, ERR_NOT_A_DIVISOR, index, f"{prime} does not divide {current}")
        current //= prime

    if current != 1:
        return StepCheck(False, ERR_STOPPED_EARLY, len(rows) - 1, f"stopped at {current}, not 1")
    if final is not None and not _final_matches(final, index_form(root)):
        return StepCheck(False, ERR_NOT_INDEX_FORM, None, "final is not the index form")
    return StepCheck(True, expected_final=index_form(root))


# ---------------------------------------------------------------------------
# Dispatch + answer comparison
# ---------------------------------------------------------------------------

#: Functions a course file may name in ``verify`` (Appendix A.7) and in the
#: ``check`` of a ``photo_check`` (Appendix A.6). Anything outside this registry
#: has to be declared in ``engine_requests``.
ENGINE_FUNCTIONS: dict[str, object] = {
    "calc": calc,
    "round_dp": round_dp,
    "round_sf": round_sf,
    "estimate_1sf": estimate_1sf,
    "is_prime": is_prime,
    "factors": factors,
    "multiples": multiples,
    "primes_between": primes_between,
    "prime_factors": prime_factors,
    "index_form": index_form,
    "hcf": hcf,
    "lcm": lcm,
    "add_minutes": add_minutes,
    "add_days": add_days,
    "digit_sum": digit_sum,
    "alt_sum": alt_sum,
}

#: Step checkers usable as a ``photo_check.check`` function.
STEP_CHECKERS: dict[str, object] = {
    "calc_lines": calc_lines,
    "tree_splits": tree_splits,
    "ladder_steps": ladder_steps,
}

#: Functions whose result is compared letter by letter rather than numerically.
TEXT_RESULT_FUNCTIONS = frozenset({"round_dp", "round_sf", "index_form"})


@dataclass
class EngineResult:
    """What a ``verify`` call produced, plus how it should be compared."""

    value: object
    text: str
    is_text: bool = False
    extras: dict = field(default_factory=dict)


def call(fn: str, args: list | tuple | None = None, kwargs: dict | None = None) -> EngineResult:
    """Run an engine function by name, as a ``verify`` block asks.

    Raises :class:`EngineError` for an unknown name so the validator can report
    it as a missing ``engine_requests`` entry rather than crashing.
    """
    target = ENGINE_FUNCTIONS.get(fn)
    if target is None:
        raise EngineError(f"Unknown engine function {fn!r}", code="not_in_engine")
    call_args = list(args or [])
    call_kwargs = dict(kwargs or {})
    try:
        value = target(*call_args, **call_kwargs)  # type: ignore[operator]
    except EngineError:
        raise
    except (TypeError, ValueError, ZeroDivisionError, ArithmeticError) as exc:
        raise EngineError(f"{fn} failed: {exc}") from exc

    if isinstance(value, bool):
        return EngineResult(value, "true" if value else "false")
    if isinstance(value, str):
        return EngineResult(value, value, is_text=True)
    if isinstance(value, list):
        return EngineResult(value, ", ".join(format_number(v) for v in value))
    return EngineResult(value, format_number(Fraction(value)), is_text=fn in TEXT_RESULT_FUNCTIONS)


def _normalize_index_form(text: str) -> str:
    """Canonicalise index form so ``2^3``, ``2³`` and ``3² × 2³ × 5`` agree.

    Formatting is normalised (superscripts, ``x``/``×``/``*``, spacing, factor
    order) but the power *structure* is preserved on purpose: ``2³ × 3² × 5``
    must NOT equal ``2 × 2 × 2 × 3 × 3 × 5``, because that expanded form is a
    documented trap for ``m_not_index_form`` and Appendix C.2 requires every
    trap to differ from the answer.
    """
    out = str(text).strip().lower()
    for sup, digit in _SUPERSCRIPT_TO_ASCII.items():
        out = out.replace(sup, f"^{digit}")
    out = out.replace(TIMES, "*").replace("x", "*").replace("·", "*")
    out = re.sub(r"\s*\^\s*", "^", out)
    out = re.sub(r"\s+", "", out)
    parts: list[tuple[int, int, str]] = []
    for part in out.split("*"):
        if not part:
            continue
        base, _, power = part.partition("^")
        try:
            parts.append((int(base), int(power) if power else 1, ""))
        except ValueError:
            parts.append((0, 0, part))
    parts.sort()
    return "*".join(raw if raw else f"{base}^{exp}" for base, exp, raw in parts)


def is_index_form(text: str) -> bool:
    """True when no prime appears twice as a separate factor.

    Backs the ``require_index`` check: ``2³ × 3² × 5`` passes, the expanded
    ``2 × 2 × 2 × 3 × 3 × 5`` does not.
    """
    normalized = _normalize_index_form(text)
    bases = [part.partition("^")[0] for part in normalized.split("*") if part]
    return len(bases) == len(set(bases))


def answers_match(answer: object, result: EngineResult, *, fn: str = "") -> bool:
    """Compare an authored ``answer`` against a recomputed engine result.

    Rounding and index form compare as text (A.2/Appendix C.2 require "letter by
    letter" and "prime by prime"); everything else compares numerically so
    ``12`` and ``"12"`` agree.
    """
    if isinstance(result.value, bool):
        if isinstance(answer, bool):
            return answer is result.value
        return str(answer).strip().lower() in (
            ("true", "yes", "vrai") if result.value else ("false", "no", "faux")
        )

    if isinstance(result.value, list):
        if isinstance(answer, str):
            pieces = [p for p in re.split(r"[,;]", answer) if p.strip()]
        elif isinstance(answer, (list, tuple)):
            pieces = list(answer)
        else:
            return False
        if len(pieces) != len(result.value):
            return False
        try:
            return all(
                parse_number(str(got)) == parse_number(str(want))
                for got, want in zip(pieces, result.value, strict=True)
            )
        except EngineError:
            return False

    if fn == "index_form" or (result.is_text and fn == ""):
        return _normalize_index_form(str(answer)) == _normalize_index_form(result.text)

    if result.is_text:
        # Rounding: identical characters once spaces are stripped, so "2.1" and
        # "2.10" stay different answers.
        return str(answer).strip().replace(" ", "").replace(MINUS, "-") == result.text.replace(
            MINUS, "-"
        )

    try:
        return parse_number(str(answer)) == Fraction(result.value)  # type: ignore[arg-type]
    except (EngineError, TypeError, ValueError):
        return False
