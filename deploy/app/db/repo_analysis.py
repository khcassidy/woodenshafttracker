"""Runs the analysis engine over one (diameter, wood) partition: fetches
candidates, solves via core.grouping per the param set's objective, and
attaches presentation-only fields to the result. core.grouping never
sees spec bounds or ab_tol_cp -- those are applied here, after the solve,
so a future cache could key the solve itself separately from these purely
cosmetic parameters.
"""

from __future__ import annotations

import sqlite3

from core.derive import ab_consistent, in_spec
from core.grouping import ShaftCandidate, solve_leftover_groups, solve_max_dozens
from core.units import mean_minor
from app.db import repo_shafts


def _pool_version(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT int_value FROM app_meta WHERE key = 'pool_version'"
    ).fetchone()["int_value"]


def _shaft_summary(row: sqlite3.Row, param_set: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "batchNo": row["batch_no"],
        "seq": row["seq"],
        "spineACp": row["spine_a_cp"],
        "spineAText": row["spine_a_text"],
        "spineBCp": row["spine_b_cp"],
        "spineBText": row["spine_b_text"],
        "avgSpineMlb": row["avg_spine_mlb"],
        "spineSpreadCp": row["spine_spread_cp"],
        "weightCg": row["weight_cg"],
        "weightText": row["weight_text"],
        "weightUnit": row["weight_unit"],
        "straightness": row["straightness"],
        "notes": row["notes"],
        "abConsistent": ab_consistent(row["spine_spread_cp"], param_set["ab_tol_cp"]),
        "inSpec": in_spec(row["avg_spine_mlb"], param_set["spec_min_mlb"], param_set["spec_max_mlb"]),
    }


def run_analysis(
    conn: sqlite3.Connection,
    *,
    diameter_id: int,
    wood_id: int,
    param_set_id: int,
    pool_filter: str,
) -> dict:
    param_set = conn.execute(
        "SELECT * FROM param_set WHERE id = ?", (param_set_id,)
    ).fetchone()
    if param_set is None:
        raise KeyError(param_set_id)

    diameter = conn.execute(
        "SELECT id, label FROM diameter_option WHERE id = ?", (diameter_id,)
    ).fetchone()
    wood = conn.execute("SELECT id, label FROM wood_option WHERE id = ?", (wood_id,)).fetchone()
    if diameter is None:
        raise KeyError(diameter_id)
    if wood is None:
        raise KeyError(wood_id)

    rows = repo_shafts.list_partition_shafts(conn, diameter_id, wood_id, available_only=True)
    if pool_filter == "in_spec":
        rows = [
            r for r in rows
            if in_spec(r["avg_spine_mlb"], param_set["spec_min_mlb"], param_set["spec_max_mlb"])
        ]
    rows_by_id = {r["id"]: r for r in rows}
    candidates = [ShaftCandidate(r["id"], r["avg_spine_mlb"], r["weight_cg"]) for r in rows]

    objective = param_set["objective"]
    min_group_size = param_set["min_group_size"]
    if objective == "MAX_DOZENS":
        solution = solve_max_dozens(
            candidates,
            spine_tol_mlb=param_set["spine_tol_mlb"],
            weight_tol_cg=param_set["weight_tol_cg"],
            dozen_size=param_set["dozen_size"],
        )
        status = solution.status
        # A dozen size doesn't divide the pool evenly, or the box
        # constraint simply can't fit more full dozens in -- either way,
        # solve_max_dozens leaves those shafts as "unused" even when many
        # of them would still make a perfectly good smaller matched group.
        # Salvage what's usable (>= min_group_size) from exactly that
        # leftover pool, on top of the dozens already found.
        leftover_candidates = [
            ShaftCandidate(
                sid, rows_by_id[sid]["avg_spine_mlb"], rows_by_id[sid]["weight_cg"]
            )
            for sid in solution.unused_shaft_ids
        ]
        leftover_groups = solve_leftover_groups(
            leftover_candidates,
            spine_tol_mlb=param_set["spine_tol_mlb"],
            weight_tol_cg=param_set["weight_tol_cg"],
            min_group_size=min_group_size,
        )
        leftover_ids = {sid for g in leftover_groups for sid in g.shaft_ids}
        unused_shaft_ids = [sid for sid in solution.unused_shaft_ids if sid not in leftover_ids]
        flagged_groups = [(g, True) for g in solution.groups] + [(g, False) for g in leftover_groups]
    else:
        # "Biggest matched set" means every usable match, not just the
        # single largest -- solve_leftover_groups repeatedly takes the
        # best remaining group (each extraction itself exactly optimal,
        # via solve_max_set) until nothing left clears the usable-group
        # threshold, same mechanism the MAX_DOZENS leftovers use above.
        all_groups = solve_leftover_groups(
            candidates,
            spine_tol_mlb=param_set["spine_tol_mlb"],
            weight_tol_cg=param_set["weight_tol_cg"],
            min_group_size=min_group_size,
        )
        status = "OPTIMAL"
        used_ids = {sid for g in all_groups for sid in g.shaft_ids}
        unused_shaft_ids = [c.id for c in candidates if c.id not in used_ids]
        flagged_groups = [(g, False) for g in all_groups]

    groups = []
    for index, (group, is_dozen) in enumerate(flagged_groups):
        members = [_shaft_summary(rows_by_id[sid], param_set) for sid in group.shaft_ids]
        spine_vals = [m["avgSpineMlb"] for m in members]
        weight_vals = [m["weightCg"] for m in members]
        groups.append(
            {
                "index": index,
                "size": len(members),
                "isDozen": is_dozen,
                "avgSpineMinMlb": min(spine_vals),
                "avgSpineMaxMlb": max(spine_vals),
                "avgSpineMeanMlb": mean_minor(spine_vals),
                "weightMinCg": min(weight_vals),
                "weightMaxCg": max(weight_vals),
                "weightMeanCg": mean_minor(weight_vals),
                "members": members,
            }
        )

    unused_shafts = [_shaft_summary(rows_by_id[sid], param_set) for sid in unused_shaft_ids]

    return {
        "diameter": dict(diameter),
        "wood": dict(wood),
        "objective": objective,
        "dozenSize": param_set["dozen_size"] if objective == "MAX_DOZENS" else None,
        "poolFilter": pool_filter,
        "candidateCount": len(candidates),
        "poolVersion": _pool_version(conn),
        "status": status,
        "groups": groups,
        "unusedShafts": unused_shafts,
    }
