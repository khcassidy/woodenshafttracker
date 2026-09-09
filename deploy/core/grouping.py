"""The analysis engine: box-constrained shaft grouping via CP-SAT.

Both grouping objectives -- biggest matched set and most complete
dozens -- are the same underlying problem: assign shafts to a small
number of "slots," each slot box-constrained on (avg spine, weight),
maximizing an objective over slot use. MAX_SET is the K=1, no-fixed-size
case; MAX_DOZENS is the K=n//dozen_size, each-active-slot-exactly-
dozen_size case. One modeling technique, one dependency, one place the
box-constraint logic is tested.

The workbook's own proposed dozens fix (score floor(size/12) first, size
second, over a single window) is provably argmax-identical to plain
largest-count -- it does nothing. The real defect is that "most complete
dozens" is a disjoint set-packing problem over the whole partition, not
a single-window search: a single biggest-window pick can strand shafts a
second, non-overlapping dozen elsewhere in the pool needed. See
tests/test_grouping.py's synthetic 24-shaft case for a guaranteed,
by-construction demonstration (greedy finds 1, exact solving finds 2);
its own golden regression against the real 100-shaft workbook pins that
data's own figure (1 dozen at the shipped defaults), which is a property
of the actual spine/weight values at that tolerance, not a fixed
property of greedy vs. exact. solve_max_dozens exists because greedy is
provably wrong for this problem shape, not just slower.

Pure: no DB, no HTTP -- see tests/test_core_purity.py. That test's
denylist doesn't include ortools; this module still touches no DB and
makes no network call, holding the boundary's actual intent (testable
without a database, deterministic).
"""

from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

_RANDOM_SEED = 20260101


@dataclass(frozen=True)
class ShaftCandidate:
    id: int
    avg_spine_mlb: int
    weight_cg: int


@dataclass(frozen=True)
class GroupResult:
    shaft_ids: list[int]


@dataclass(frozen=True)
class GroupingSolution:
    objective: str
    groups: list[GroupResult]
    unused_shaft_ids: list[int]
    status: str


def _add_box_constraints(
    model: cp_model.CpModel,
    member_vars: list[cp_model.IntVar],
    spine_vals: list[int],
    weight_vals: list[int],
    spine_tol_mlb: int,
    weight_tol_cg: int,
    name_prefix: str,
) -> None:
    """member_vars[i] is 1 iff candidate i belongs to this slot. Reifies
    the slot's spine/weight min and max against only its actual members,
    with no big-M: when a candidate's var is 0 its OnlyEnforceIf clause
    never fires, so an empty slot's min/max stay free to collapse to a
    single point and trivially satisfy the spread bound.
    """
    spine_min = model.NewIntVar(min(spine_vals), max(spine_vals), f"{name_prefix}_spine_min")
    spine_max = model.NewIntVar(min(spine_vals), max(spine_vals), f"{name_prefix}_spine_max")
    weight_min = model.NewIntVar(min(weight_vals), max(weight_vals), f"{name_prefix}_weight_min")
    weight_max = model.NewIntVar(min(weight_vals), max(weight_vals), f"{name_prefix}_weight_max")
    for var, spine, weight in zip(member_vars, spine_vals, weight_vals):
        model.Add(spine_min <= spine).OnlyEnforceIf(var)
        model.Add(spine_max >= spine).OnlyEnforceIf(var)
        model.Add(weight_min <= weight).OnlyEnforceIf(var)
        model.Add(weight_max >= weight).OnlyEnforceIf(var)
    # A tolerance of N means the group fits inside an N-wide window, not
    # that its extremes can be a full N apart -- max - min must stay
    # strictly under the tolerance, not merely at or under it.
    model.Add(spine_max - spine_min < spine_tol_mlb)
    model.Add(weight_max - weight_min < weight_tol_cg)


def _solve(model: cp_model.CpModel) -> tuple[int, cp_model.CpSolver]:
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = _RANDOM_SEED
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    return status, solver


def solve_max_set(
    candidates: list[ShaftCandidate], *, spine_tol_mlb: int, weight_tol_cg: int
) -> GroupingSolution:
    """The biggest single subset of candidates whose avg-spine spread
    stays within spine_tol_mlb AND whose weight spread stays within
    weight_tol_cg -- both bounds must hold on the same subset at once,
    which is why this needs a solver rather than sorting on one axis."""
    if not candidates:
        return GroupingSolution("MAX_SET", [], [], "OPTIMAL")

    model = cp_model.CpModel()
    member_vars = [model.NewBoolVar(f"x{i}") for i in range(len(candidates))]
    spine_vals = [c.avg_spine_mlb for c in candidates]
    weight_vals = [c.weight_cg for c in candidates]
    _add_box_constraints(
        model, member_vars, spine_vals, weight_vals, spine_tol_mlb, weight_tol_cg, "set"
    )
    model.Maximize(sum(member_vars))

    status, solver = _solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return GroupingSolution("MAX_SET", [], [c.id for c in candidates], solver.StatusName(status))

    members = [c.id for c, v in zip(candidates, member_vars) if solver.Value(v)]
    unused = [c.id for c, v in zip(candidates, member_vars) if not solver.Value(v)]
    groups = [GroupResult(members)] if members else []
    return GroupingSolution("MAX_SET", groups, unused, solver.StatusName(status))


def solve_max_dozens(
    candidates: list[ShaftCandidate],
    *,
    spine_tol_mlb: int,
    weight_tol_cg: int,
    dozen_size: int,
) -> GroupingSolution:
    """The maximum number of disjoint, exactly-dozen_size groups that can
    be carved from candidates, each satisfying the same box constraint as
    solve_max_set. Deliberately NOT a repeated call to solve_max_set: the
    real, verified defect in the naive approach is that a locally-biggest
    window can eat shafts a second, non-overlapping dozen elsewhere in the
    pool needed -- only solving for every dozen jointly avoids that.
    """
    n = len(candidates)
    max_slots = n // dozen_size if dozen_size > 0 else 0
    if max_slots == 0:
        return GroupingSolution("MAX_DOZENS", [], [c.id for c in candidates], "OPTIMAL")

    model = cp_model.CpModel()
    spine_vals = [c.avg_spine_mlb for c in candidates]
    weight_vals = [c.weight_cg for c in candidates]

    x = [[model.NewBoolVar(f"x{i}_{k}") for k in range(max_slots)] for i in range(n)]
    y = [model.NewBoolVar(f"y{k}") for k in range(max_slots)]

    for i in range(n):
        model.Add(sum(x[i][k] for k in range(max_slots)) <= 1)

    for k in range(max_slots):
        member_vars = [x[i][k] for i in range(n)]
        model.Add(sum(member_vars) == dozen_size * y[k])
        _add_box_constraints(
            model, member_vars, spine_vals, weight_vals, spine_tol_mlb, weight_tol_cg, f"slot{k}"
        )

    # Symmetry-break: slots fill in order, so the solver isn't searching
    # many equivalent relabelings of the same solution.
    for k in range(max_slots - 1):
        model.Add(y[k] >= y[k + 1])

    model.Maximize(sum(y))

    status, solver = _solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return GroupingSolution(
            "MAX_DOZENS", [], [c.id for c in candidates], solver.StatusName(status)
        )

    groups = []
    used_ids: set[int] = set()
    for k in range(max_slots):
        if not solver.Value(y[k]):
            continue
        members = [candidates[i].id for i in range(n) if solver.Value(x[i][k])]
        groups.append(GroupResult(members))
        used_ids.update(members)

    unused = [c.id for c in candidates if c.id not in used_ids]
    return GroupingSolution("MAX_DOZENS", groups, unused, solver.StatusName(status))


def solve_leftover_groups(
    candidates: list[ShaftCandidate],
    *,
    spine_tol_mlb: int,
    weight_tol_cg: int,
    min_group_size: int,
) -> list[GroupResult]:
    """Salvages usable matched groups from shafts solve_max_dozens couldn't
    fit into a full dozen -- candidates should be its unused_shaft_ids,
    looked back up into ShaftCandidates. Repeatedly takes the single best
    remaining group (solve_max_set, so each individual extraction is
    itself exactly optimal, not a heuristic pick) and removes it, stopping
    once the best group left is smaller than min_group_size. This is NOT
    the same "greedy" solve_max_dozens's own docstring calls provably
    wrong: that defect is a single window picked ahead of a FIXED number
    of equal-size slots, which can strand shafts a same-size sibling
    needed. Here there's no fixed slot count or size to plan jointly
    against -- "as many variably-sized usable groups as fit" has no
    equivalent one-shot formulation, so exact-per-step extraction is the
    principled approach, not a shortcut.
    """
    groups: list[GroupResult] = []
    remaining = list(candidates)
    while remaining:
        solution = solve_max_set(remaining, spine_tol_mlb=spine_tol_mlb, weight_tol_cg=weight_tol_cg)
        if not solution.groups or len(solution.groups[0].shaft_ids) < min_group_size:
            break
        group = solution.groups[0]
        groups.append(group)
        used = set(group.shaft_ids)
        remaining = [c for c in remaining if c.id not in used]
    return groups
