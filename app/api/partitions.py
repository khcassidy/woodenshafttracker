"""GET /api/partitions -- the slice-2 contract, delivered in slice 1.

'available' means analysable: not junk, not consumed, and fully measured.
'unmeasured' is explicit, so Mode 2 pass 1 (spine done, no weight yet)
does not silently vanish from the pool counts.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from core.derive import ab_consistent, in_spec

from app.api.shafts import _row_dict as _shaft_dict
from app.db import repo_params, repo_shafts
from app.deps import get_db

router = APIRouter(prefix="/api/partitions", tags=["partitions"])


def _shape_candidate(row: sqlite3.Row, param_set: sqlite3.Row | None) -> dict:
    """The manual set builder's candidate picker needs the same full shaft
    detail (and the same abConsistent/inSpec flags) as a built set's own
    member list -- see app/api/sets.py's _shape_member for why those two
    flags check against the current default param_set rather than a
    stored one."""
    shaped = _shaft_dict(row)
    spread, avg = shaped["spineSpreadCp"], shaped["avgSpineMlb"]
    if param_set is not None and spread is not None and avg is not None:
        shaped["abConsistent"] = ab_consistent(spread, param_set["ab_tol_cp"])
        shaped["inSpec"] = in_spec(avg, param_set["spec_min_mlb"], param_set["spec_max_mlb"])
    else:
        shaped["abConsistent"] = None
        shaped["inSpec"] = None
    return shaped


@router.get("")
def list_partitions(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT
             s.diameter_id, d.label AS diameter_label,
             s.wood_id, w.label AS wood_label,
             COUNT(*) AS total,
             SUM(CASE WHEN s.consumed_set_id IS NOT NULL THEN 1 ELSE 0 END) AS consumed,
             SUM(CASE WHEN s.straightness = 'JUNK' THEN 1 ELSE 0 END) AS junk,
             SUM(CASE WHEN s.consumed_set_id IS NULL
                       AND (s.straightness IS NULL OR s.straightness <> 'JUNK')
                       AND s.avg_spine_mlb IS NOT NULL AND s.weight_cg IS NOT NULL
                  THEN 1 ELSE 0 END) AS available,
             SUM(CASE WHEN s.consumed_set_id IS NULL
                       AND (s.straightness IS NULL OR s.straightness <> 'JUNK')
                       AND (s.avg_spine_mlb IS NULL OR s.weight_cg IS NULL)
                  THEN 1 ELSE 0 END) AS unmeasured
           FROM shaft s
           JOIN diameter_option d ON d.id = s.diameter_id
           JOIN wood_option w ON w.id = s.wood_id
           GROUP BY s.diameter_id, s.wood_id
           ORDER BY d.sort_order, w.sort_order"""
    ).fetchall()
    return [
        {
            "diameter": {"id": r["diameter_id"], "label": r["diameter_label"]},
            "wood": {"id": r["wood_id"], "label": r["wood_label"]},
            "total": r["total"],
            "available": r["available"],
            "consumed": r["consumed"],
            "junk": r["junk"],
            "unmeasured": r["unmeasured"],
        }
        for r in rows
    ]


@router.get("/{diameter_id}/{wood_id}/shafts")
def list_partition_shafts(
    diameter_id: int,
    wood_id: int,
    available_only: bool = True,
    db: sqlite3.Connection = Depends(get_db),
):
    rows = repo_shafts.list_partition_shafts(db, diameter_id, wood_id, available_only)
    param_set = repo_params.get_default_param_set(db)
    return [_shape_candidate(r, param_set) for r in rows]
