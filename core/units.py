"""Decimal-string parsing and integer minor-unit conversions.

Spine is stored as centipounds (cp), weight as centigrams (cg), and the
two-reading average spine as millipounds (mlb). Nothing here ever produces
or consumes a Python float: every conversion goes string -> Decimal ->
int, with ROUND_HALF_UP made explicit at each quantisation.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENTI = Decimal(100)
MILLI = Decimal(1000)
GRAINS_PER_GRAM = Decimal("15.4324")

_DECIMAL_SHAPE_RE = re.compile(r"^[+-]?(?:\d+\.\d+|\.\d+|\d+)$")


class UnitError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def normalize_decimal_string(raw: str, *, max_dp: int = 2) -> Decimal:
    text = raw.strip()
    if not text:
        raise UnitError("EMPTY", "value is empty")
    text = text.replace(",", ".")
    if not _DECIMAL_SHAPE_RE.match(text):
        raise UnitError("NOT_A_NUMBER", f"{raw!r} is not a valid decimal number")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise UnitError("NOT_A_NUMBER", f"{raw!r} is not a valid decimal number") from exc
    exponent = value.as_tuple().exponent
    dp = -exponent if exponent < 0 else 0
    if dp > max_dp:
        raise UnitError("TOO_MANY_DP", f"{raw!r} has more than {max_dp} decimal places")
    return value


def _to_minor(value: Decimal, scale: Decimal) -> int:
    return int((value * scale).to_integral_value(rounding=ROUND_HALF_UP))


def mean_minor(values: list[int]) -> int:
    """Rounds the mean of already-minor-unit integers (e.g. several
    shafts' avg_spine_mlb) back to an integer minor-unit value, via
    Decimal + ROUND_HALF_UP -- plain `sum(values) / len(values)` would
    silently hand back a float, the one thing nothing in this module ever
    produces."""
    return int(
        (Decimal(sum(values)) / Decimal(len(values))).to_integral_value(rounding=ROUND_HALF_UP)
    )


def parse_spine_lb(raw: str) -> int:
    """Parse a spine reading in pounds to centipounds. Raises UnitError."""
    value = normalize_decimal_string(raw, max_dp=2)
    cp = _to_minor(value, CENTI)
    if cp <= 0:
        raise UnitError("NOT_POSITIVE", f"{raw!r} must be a positive spine value")
    return cp


def parse_weight_g(raw: str) -> int:
    """Parse a weight in grams to centigrams. Raises UnitError."""
    value = normalize_decimal_string(raw, max_dp=2)
    cg = _to_minor(value, CENTI)
    if cg <= 0:
        raise UnitError("NOT_POSITIVE", f"{raw!r} must be a positive weight value")
    return cg


def grains_to_weight_cg(raw: str) -> int:
    """Parse a weight in grains to centigrams. Lossy: 1 g = 15.4324 gr exactly,
    but 1 gr does not divide evenly back into whole centigrams."""
    value = normalize_decimal_string(raw, max_dp=2)
    if value <= 0:
        raise UnitError("NOT_POSITIVE", f"{raw!r} must be a positive weight value")
    grams = value / GRAINS_PER_GRAM
    cg = int((grams * CENTI).to_integral_value(rounding=ROUND_HALF_UP))
    if cg <= 0:
        raise UnitError("NOT_POSITIVE", f"{raw!r} must be a positive weight value")
    return cg


def parse_weight(raw: str, unit: str) -> int:
    """Dispatch on the entered unit. Always returns centigrams."""
    if unit == "g":
        return parse_weight_g(raw)
    if unit == "gr":
        return grains_to_weight_cg(raw)
    raise UnitError("BAD_UNIT", f"unknown weight unit {unit!r}")


def weight_cg_to_grains(cg: int) -> Decimal:
    return (Decimal(cg) / CENTI) * GRAINS_PER_GRAM


def format_spine_cp(cp: int) -> str:
    return str((Decimal(cp) / CENTI).quantize(Decimal("0.01")))


def format_weight_cg(cg: int) -> str:
    return str((Decimal(cg) / CENTI).quantize(Decimal("0.01")))


def format_avg_spine_mlb(mlb: int) -> str:
    return str((Decimal(mlb) / MILLI).quantize(Decimal("0.001")))


def format_grains(cg: int) -> str:
    return str(weight_cg_to_grains(cg).quantize(Decimal("0.01")))
