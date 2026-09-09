"""The manual set builder. POST /api/sets is the endpoint slice 2's own
grouping engine will eventually call too, so its idempotency key, mixed-
partition guard, and 409-on-already-consumed are exercised here against
real data ahead of that solver landing.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from core.derive import ab_consistent, in_spec

from app.api.schemas import SetCreateRequest, SetMembersRequest, SetPatchRequest
from app.api.shafts import _row_dict as _shaft_dict
from app.db import repo_params, repo_sets
from app.deps import get_db

router = APIRouter(prefix="/api/sets", tags=["sets"])


def _shape_member(m: dict, param_set: sqlite3.Row | None) -> dict:
    """repo_sets returns a set's members straight from shaft_entry_v --
    raw snake_case columns, unlike every other endpoint. Reuse shafts.py's
    own row shaper rather than duplicate its field list here, then add the
    two fields the Analysis tab already shows (abConsistent, inSpec) so a
    set's own member list carries the same information. A manually built
    set has no param_set of its own (unlike a would-be Analysis-tab
    grouping run), so this uses whichever param_set is the current
    default -- display-only, not stored -- same as the Analysis tab's own
    default selection."""
    shaped = _shaft_dict(m)
    spread, avg = shaped["spineSpreadCp"], shaped["avgSpineMlb"]
    if param_set is not None and spread is not None and avg is not None:
        shaped["abConsistent"] = ab_consistent(spread, param_set["ab_tol_cp"])
        shaped["inSpec"] = in_spec(avg, param_set["spec_min_mlb"], param_set["spec_max_mlb"])
    else:
        shaped["abConsistent"] = None
        shaped["inSpec"] = None
    return shaped


def _shape_set(result: dict, db: sqlite3.Connection) -> dict:
    param_set = repo_params.get_default_param_set(db)
    return {**result, "members": [_shape_member(m, param_set) for m in result["members"]]}


@router.get("")
def list_sets(db: sqlite3.Connection = Depends(get_db)):
    return repo_sets.list_sets(db)


@router.get("/{set_id}")
def get_set(set_id: int, db: sqlite3.Connection = Depends(get_db)):
    result = repo_sets.get_set(db, set_id)
    if result is None:
        raise HTTPException(404, f"no such set {set_id}")
    return _shape_set(result, db)


@router.post("")
def create_set(body: SetCreateRequest, db: sqlite3.Connection = Depends(get_db)):
    try:
        result = repo_sets.create_set(
            db,
            name=body.name,
            diameter_id=body.diameterId,
            wood_id=body.woodId,
            shaft_ids=body.shaftIds,
            target_size=body.targetSize,
            notes=body.notes,
            idempotency_key=body.idempotencyKey,
        )
        return _shape_set(result, db)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except repo_sets.SetMembersConsumedError as exc:
        raise HTTPException(
            409, f"already used in another set: {exc.shaft_ids}"
        ) from exc


@router.patch("/{set_id}")
def patch_set(set_id: int, body: SetPatchRequest, db: sqlite3.Connection = Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    try:
        if "notes" in fields:
            result = repo_sets.update_set_notes(db, set_id, fields["notes"])
        else:
            result = repo_sets.get_set(db, set_id)
            if result is None:
                raise KeyError(set_id)
    except KeyError:
        raise HTTPException(404, f"no such set {set_id}")
    return _shape_set(result, db)


@router.delete("/{set_id}")
def disband_set(set_id: int, db: sqlite3.Connection = Depends(get_db)):
    try:
        return _shape_set(repo_sets.disband_set(db, set_id), db)
    except KeyError:
        raise HTTPException(404, f"no such set {set_id}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{set_id}:purge")
def purge_set(set_id: int, db: sqlite3.Connection = Depends(get_db)):
    try:
        repo_sets.delete_set(db, set_id)
    except KeyError:
        raise HTTPException(404, f"no such set {set_id}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@router.post("/{set_id}/members:add")
def add_set_members(
    set_id: int, body: SetMembersRequest, db: sqlite3.Connection = Depends(get_db)
):
    try:
        result = repo_sets.add_members(db, set_id, body.shaftIds)
    except KeyError:
        raise HTTPException(404, f"no such set {set_id}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except repo_sets.SetMembersConsumedError as exc:
        raise HTTPException(
            409, f"already used in another set: {exc.shaft_ids}"
        ) from exc
    return _shape_set(result, db)


@router.post("/{set_id}/members:remove")
def remove_set_members(
    set_id: int, body: SetMembersRequest, db: sqlite3.Connection = Depends(get_db)
):
    try:
        result = repo_sets.remove_members(db, set_id, body.shaftIds)
    except KeyError:
        raise HTTPException(404, f"no such set {set_id}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _shape_set(result, db)
