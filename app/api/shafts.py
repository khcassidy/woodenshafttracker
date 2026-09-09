"""Shaft entry endpoints: per-field PATCH, bulk flush (the offline-queue
recovery path), and the resume contract (entry-state)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import BulkPatchRequest, ShaftInsertRequest, ShaftPatchRequest
from app.db import repo_batches, repo_shafts
from app.deps import get_db

router = APIRouter(prefix="/api/batches/{batch_id}", tags=["shafts"])


def _row_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "batchId": row["batch_id"],
        "batchNo": row["batch_no"],
        "seq": row["seq"],
        "label": row["label"],
        "diameterId": row["diameter_id"],
        "woodId": row["wood_id"],
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
        "consumedSetId": row["consumed_set_id"],
        "updatedAt": row["updated_at"],
    }


@router.get("/shafts")
def list_shafts(batch_id: int, sort: str = "seq", db: sqlite3.Connection = Depends(get_db)):
    return [_row_dict(r) for r in repo_shafts.list_shafts(db, batch_id=batch_id, sort=sort)]


@router.patch("/shafts/{seq}")
def patch_shaft(
    batch_id: int, seq: int, body: ShaftPatchRequest, db: sqlite3.Connection = Depends(get_db)
):
    fields = body.model_dump(exclude_unset=True)
    try:
        outcome = repo_shafts.patch_shaft_entry(db, batch_id, seq, fields)
    except KeyError:
        raise HTTPException(404, f"no such shaft {batch_id}-{seq}")
    row = repo_shafts.get_shaft(db, batch_id, seq)
    return {**_row_dict(row), "warnings": outcome["warnings"]}


@router.post("/shafts:bulk")
def bulk_patch_shafts(
    batch_id: int, body: BulkPatchRequest, db: sqlite3.Connection = Depends(get_db)
):
    items = [
        {"seq": item.seq, "fields": item.fields.model_dump(exclude_unset=True)}
        for item in body.items
    ]
    return repo_shafts.bulk_patch(db, batch_id, items)


@router.get("/entry-state")
def get_entry_state(batch_id: int, db: sqlite3.Connection = Depends(get_db)):
    try:
        return repo_shafts.entry_state(db, batch_id)
    except KeyError:
        raise HTTPException(404, f"no such batch {batch_id}")


@router.post("/shafts:insert")
def insert_shaft(
    batch_id: int, body: ShaftInsertRequest, db: sqlite3.Connection = Depends(get_db)
):
    try:
        new_seq = repo_batches.insert_shaft(db, batch_id, body.afterSeq)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _row_dict(repo_shafts.get_shaft(db, batch_id, new_seq))


@router.delete("/shafts/{seq}")
def delete_shaft(batch_id: int, seq: int, db: sqlite3.Connection = Depends(get_db)):
    try:
        repo_batches.delete_shaft(db, batch_id, seq)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "deleted"}
