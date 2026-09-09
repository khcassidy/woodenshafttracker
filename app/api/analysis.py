"""GET /api/analysis -- runs the grouping engine over one partition and
returns groups the frontend can hand straight to POST /api/sets to commit."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import repo_analysis, repo_params
from app.deps import get_db

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("")
def get_analysis(
    diameterId: int,
    woodId: int,
    paramSetId: int | None = None,
    poolFilter: str = "all",
    db: sqlite3.Connection = Depends(get_db),
):
    if poolFilter not in ("all", "in_spec"):
        raise HTTPException(400, f"poolFilter must be 'all' or 'in_spec', got {poolFilter!r}")

    param_set_id = paramSetId
    if param_set_id is None:
        default = repo_params.get_default_param_set(db)
        param_set_id = default["id"] if default is not None else -1

    try:
        return repo_analysis.run_analysis(
            db,
            diameter_id=diameterId,
            wood_id=woodId,
            param_set_id=param_set_id,
            pool_filter=poolFilter,
        )
    except KeyError as exc:
        # exc.args[0] is whichever id repo_analysis rejected -- diameter,
        # wood, or param set. str(exc) would repr a single-arg KeyError
        # with stray quotes ("'5'"), so build the message from the
        # request's own values instead of the exception text.
        raise HTTPException(
            404,
            f"no such diameter {diameterId}, wood {woodId}, or param set {param_set_id} "
            f"(missing: {exc.args[0]})",
        ) from exc
