"""Step, band, and batch-outlier checks for one already-parsed reading.

Pure: takes minor-unit integers and the current entry_rule bands as plain
arguments, no DB. Errors block the save; warnings do not, and neither
blocks focus advance in the entry grid.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    blocking: bool


class ValidationBlocked(Exception):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("; ".join(i.message for i in issues))


def check_spine_reading(
    value_cp: int,
    *,
    step_cp: int,
    hard_min_cp: int,
    hard_max_cp: int,
    warn_min_cp: int,
    warn_max_cp: int,
) -> list[ValidationIssue]:
    if value_cp < hard_min_cp or value_cp > hard_max_cp:
        return [
            ValidationIssue(
                "OUT_OF_RANGE", f"{value_cp / 100:.2f} lb is outside the plausible range", True
            )
        ]
    issues = []
    if value_cp % step_cp != 0:
        issues.append(
            ValidationIssue(
                "OFF_STEP",
                f"{value_cp / 100:.2f} lb is not a multiple of {step_cp / 100:.2f} lb",
                False,
            )
        )
    if value_cp < warn_min_cp or value_cp > warn_max_cp:
        issues.append(
            ValidationIssue("UNUSUAL_VALUE", f"{value_cp / 100:.2f} lb is an unusual spine value", False)
        )
    return issues


def check_weight_reading(
    value_cg: int,
    *,
    step_cg: int,
    hard_min_cg: int,
    hard_max_cg: int,
    warn_min_cg: int,
    warn_max_cg: int,
) -> list[ValidationIssue]:
    if value_cg < hard_min_cg or value_cg > hard_max_cg:
        return [
            ValidationIssue(
                "OUT_OF_RANGE", f"{value_cg / 100:.2f} g is outside the plausible range", True
            )
        ]
    issues = []
    if value_cg % step_cg != 0:
        issues.append(
            ValidationIssue(
                "OFF_STEP", f"{value_cg / 100:.2f} g is not a multiple of the weight step", False
            )
        )
    if value_cg < warn_min_cg or value_cg > warn_max_cg:
        issues.append(
            ValidationIssue("UNUSUAL_VALUE", f"{value_cg / 100:.2f} g is an unusual weight value", False)
        )
    return issues


def check_batch_outlier(value: int, median: int, tolerance: int, unit_label: str) -> list[ValidationIssue]:
    if abs(value - median) > tolerance:
        return [
            ValidationIssue(
                "BATCH_OUTLIER", f"{value} {unit_label} is far from this batch's median", False
            )
        ]
    return []
