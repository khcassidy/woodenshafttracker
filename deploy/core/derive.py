"""Per-shaft derived fields from a set of spine readings.

avg_spine_mlb generalises to any reading count, and is provably identical
to spine_sum_cp * 5 at count == 2 (see tests/test_derive.py). The formula
is round-half-up, expressed in pure integer arithmetic so it never touches
a float or Python's default round-half-to-even.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpineDerivation:
    spine_count: int
    spine_sum_cp: int
    spine_min_cp: int
    spine_max_cp: int
    avg_spine_mlb: int
    spine_spread_cp: int


def derive_spine(readings_cp: list[int]) -> SpineDerivation | None:
    if not readings_cp:
        return None
    count = len(readings_cp)
    total = sum(readings_cp)
    lo = min(readings_cp)
    hi = max(readings_cp)
    # round_half_up(total * 10 / count) in mlb, via floor((2n + d) / (2d))
    # with n = total * 10, d = count.
    avg_mlb = (total * 20 + count) // (2 * count)
    return SpineDerivation(
        spine_count=count,
        spine_sum_cp=total,
        spine_min_cp=lo,
        spine_max_cp=hi,
        avg_spine_mlb=avg_mlb,
        spine_spread_cp=hi - lo,
    )


def in_spec(avg_spine_mlb: int, spec_min_mlb: int, spec_max_mlb: int) -> bool:
    return spec_min_mlb <= avg_spine_mlb <= spec_max_mlb


def ab_consistent(spine_spread_cp: int, ab_tol_cp: int) -> bool:
    return spine_spread_cp <= ab_tol_cp
