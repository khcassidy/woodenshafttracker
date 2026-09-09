"""core/grouping.py: pure, no DB. The golden regression below pins the
solver's real-data result so it can never silently drift back to a
wrong answer. See test_max_dozens_finds_two_where_a_single_window_search
_would_find_one for the general "why CP-SAT, not greedy" argument -- that
one still holds cleanly on synthetic data.

The box constraint is a strict "<" on spread, not "<=" (core/grouping.py):
a group whose extremes sit exactly at the tolerance doesn't qualify, the
same way a "3 lb tolerance" means the group's spine values span less than
3 lb, not up to and including 3 lb. Before that fix, the real 100-shaft
workbook data solved to 2 dozens under the shipped default (3.000 lb
spine, 0.50 g weight); under the corrected comparison it's 1 -- fewer
shafts sit strictly inside a 3.000 lb window than sit at-or-inside one.
CP-SAT's OPTIMAL status is the solver's own proof of that figure, not a
heuristic guess.
"""

from pathlib import Path

import pytest

from app.io.xlsx_read import open_workbook
from core.grouping import ShaftCandidate, solve_leftover_groups, solve_max_dozens, solve_max_set
from scripts.import_workbook import build_report, read_batch_sheet

WORKBOOK_PATH = Path(__file__).resolve().parent.parent / "planning" / (
    "Arrow Batch 19 20 20260901.xlsx"
)


def _candidates(*values):
    """values: list of (avg_spine_mlb, weight_cg) pairs -> ShaftCandidates
    with synthetic ids 0..n-1."""
    return [ShaftCandidate(i, spine, weight) for i, (spine, weight) in enumerate(values)]


def _spread(candidates, ids, attr):
    vals = [getattr(c, attr) for c in candidates if c.id in ids]
    return max(vals) - min(vals)


# ---- solve_max_set ----


def test_max_set_on_empty_pool_returns_nothing():
    result = solve_max_set([], spine_tol_mlb=3000, weight_tol_cg=50)
    assert result.groups == []
    assert result.unused_shaft_ids == []


def test_max_set_picks_the_unambiguous_biggest_window():
    # 10, 11, 12 span a spread of 2; the box constraint is a strict "<"
    # (core/grouping.py), so the tolerance must clear that spread, not
    # just match it. 50 sits far outside regardless.
    candidates = _candidates((10, 100), (11, 100), (12, 100), (50, 100))
    result = solve_max_set(candidates, spine_tol_mlb=3, weight_tol_cg=1000)
    assert len(result.groups) == 1
    assert set(result.groups[0].shaft_ids) == {0, 1, 2}
    assert result.unused_shaft_ids == [3]


def test_max_set_respects_both_spine_and_weight_tolerance_at_once():
    # 0 and 1 are close in spine but far in weight; 0 and 2 are close in
    # weight but far in spine. Only {0} alone, or pairs sharing BOTH axes,
    # can ever be grouped -- here nothing shares both, so every group is size 1.
    candidates = _candidates((0, 0), (1, 1000), (1000, 1))
    result = solve_max_set(candidates, spine_tol_mlb=5, weight_tol_cg=5)
    assert len(result.groups) == 1
    assert len(result.groups[0].shaft_ids) == 1


# ---- solve_max_dozens ----


def test_max_dozens_below_dozen_size_never_calls_the_solver():
    candidates = _candidates(*[(i, 100) for i in range(5)])
    result = solve_max_dozens(candidates, spine_tol_mlb=100, weight_tol_cg=100, dozen_size=12)
    assert result.groups == []
    assert set(result.unused_shaft_ids) == {c.id for c in candidates}


def test_max_dozens_finds_two_where_a_single_window_search_would_find_one():
    """24 shafts at spine values 0..23 (weight held constant so only the
    spine axis is in contention), tol=12, dozen_size=12. A 12-shaft window
    spans 11 integer steps, and the box constraint is a strict "<" (see
    core/grouping.py), so tol must be 12 to admit it, not 11. The single
    biggest matched-set window has size exactly 12 -- many windows tie for
    that size, including ones straddling [6,17], which strands the
    remaining 12 shafts as two 6-shaft fragments that can never recombine
    into a second dozen. Only a solver considering both dozens jointly
    finds the non-overlapping split ([0..11], [12..23]) that uses every
    shaft. This is the synthetic version of the real, verified defect.
    """
    candidates = _candidates(*[(spine, 100) for spine in range(24)])
    result = solve_max_dozens(candidates, spine_tol_mlb=12, weight_tol_cg=1000, dozen_size=12)

    assert len(result.groups) == 2
    all_members = [sid for g in result.groups for sid in g.shaft_ids]
    assert sorted(all_members) == list(range(24))
    assert result.unused_shaft_ids == []
    for group in result.groups:
        assert len(group.shaft_ids) == 12
        assert _spread(candidates, group.shaft_ids, "avg_spine_mlb") < 12


def test_max_dozens_is_deterministic_across_runs():
    candidates = _candidates(*[(spine, 100) for spine in range(24)])
    kwargs = dict(spine_tol_mlb=12, weight_tol_cg=1000, dozen_size=12)
    first = solve_max_dozens(candidates, **kwargs)
    second = solve_max_dozens(candidates, **kwargs)
    assert len(first.groups) == len(second.groups) == 2


# ---- solve_leftover_groups ----


def test_leftover_groups_salvages_a_usable_group():
    # 4 shafts tightly clustered (spread 3, well inside tol) plus one
    # lone outlier that can't join anything.
    candidates = _candidates((10, 100), (11, 100), (12, 100), (13, 100), (50, 100))
    groups = solve_leftover_groups(candidates, spine_tol_mlb=4, weight_tol_cg=1000, min_group_size=3)
    assert len(groups) == 1
    assert set(groups[0].shaft_ids) == {0, 1, 2, 3}


def test_leftover_groups_returns_nothing_below_the_threshold():
    # Best possible group here is size 2 -- below a threshold of 3, so
    # nothing is "usable" and the result is empty, not a small group.
    candidates = _candidates((10, 100), (11, 100), (50, 100), (90, 100))
    groups = solve_leftover_groups(candidates, spine_tol_mlb=2, weight_tol_cg=1000, min_group_size=3)
    assert groups == []


def test_leftover_groups_extracts_more_than_one_disjoint_group():
    # Two separate usable clusters (0-3 and 20-23), far enough apart that
    # no single group can span both -- both should come back, disjoint.
    candidates = _candidates(*[(spine, 100) for spine in [0, 1, 2, 3, 20, 21, 22, 23]])
    groups = solve_leftover_groups(candidates, spine_tol_mlb=4, weight_tol_cg=1000, min_group_size=3)
    assert len(groups) == 2
    all_members = sorted(sid for g in groups for sid in g.shaft_ids)
    assert all_members == list(range(8))


def test_leftover_groups_on_empty_input():
    assert solve_leftover_groups([], spine_tol_mlb=100, weight_tol_cg=100, min_group_size=3) == []


# ---- golden regression against the real workbook ----


@pytest.fixture(scope="module")
def combined_candidates():
    wb = open_workbook(WORKBOOK_PATH)
    try:
        batch_no19, label19, rows19 = read_batch_sheet(wb, "BATCH19")
        batch_no20, label20, rows20 = read_batch_sheet(wb, "BATCH20")
    finally:
        wb.close()
    report19 = build_report(batch_no19, label19, rows19)
    report20 = build_report(batch_no20, label20, rows20)
    parsed = report19["parsed"] + report20["parsed"]
    return [
        ShaftCandidate(i, p["derived"].avg_spine_mlb, p["weight_cg"])
        for i, p in enumerate(parsed)
    ]


def test_golden_max_dozens_matches_the_workbook_verified_figure(combined_candidates):
    # Shipped param_set defaults, migrations/0001_initial.sql: spine_tol_mlb
    # 3000, weight_tol_cg 50, dozen_size 12. See the module docstring above
    # for why this is 1, not the pre-strict-inequality-fix figure of 2.
    result = solve_max_dozens(
        combined_candidates, spine_tol_mlb=3000, weight_tol_cg=50, dozen_size=12
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.groups) == 1
    for group in result.groups:
        assert len(group.shaft_ids) == 12
        assert _spread(combined_candidates, group.shaft_ids, "avg_spine_mlb") < 3000
        assert _spread(combined_candidates, group.shaft_ids, "weight_cg") < 50
    all_members = [sid for g in result.groups for sid in g.shaft_ids]
    assert len(all_members) == len(set(all_members))  # disjoint
