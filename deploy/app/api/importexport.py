"""Export (CSV/JSON download) and two-phase import (preview, then commit).

Preview never writes shaft or batch data -- only a row into import_run.
Nothing lands in the pool until a separate, explicit commit call, so a bad
file costs nothing to try."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.schemas import ImportCommitRequest
from app.db import repo_batches, repo_export, repo_import
from app.deps import get_db
from app.io import csv_io, json_io

router = APIRouter(prefix="/api", tags=["import-export"])


@router.get("/export/json")
def export_json(db: sqlite3.Connection = Depends(get_db)):
    body = json.dumps(json_io.export_json(db), indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=shafttracker-backup.json"},
    )


@router.get("/export/csv")
def export_csv(db: sqlite3.Connection = Depends(get_db)):
    rows = csv_io.from_export_rows(repo_export.export_shaft_rows(db))
    body = csv_io.write_csv(rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=shafttracker-export.csv"},
    )


@router.get("/batches/{batch_id}/export/csv")
def export_batch_csv(batch_id: int, db: sqlite3.Connection = Depends(get_db)):
    batch = repo_batches.get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(404, f"no such batch {batch_id}")
    rows = csv_io.from_export_rows(repo_export.export_shaft_rows(db, batch_id=batch_id))
    body = csv_io.write_csv(rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=batch-{batch['batch_no']}.csv"},
    )


@router.post("/import/preview")
def import_preview(
    file: UploadFile = File(...),
    format: str = Form(...),
    db: sqlite3.Connection = Depends(get_db),
):
    # file.file is the underlying SpooledTemporaryFile, readable
    # synchronously -- every endpoint here is `def`, never `async def`,
    # since sqlite3 blocks and a sync def runs in Starlette's threadpool.
    raw = file.file.read().decode("utf-8-sig")
    if format == "csv":
        staged_rows = csv_io.to_staged_rows(csv_io.read_csv_rows(raw))
    elif format == "json":
        staged_rows = json_io.to_staged_rows(json.loads(raw))
    else:
        raise HTTPException(400, f"unknown import format {format!r}")

    return repo_import.stage_rows(db, staged_rows, file.filename or "upload", format)


@router.post("/import/commit")
def import_commit(body: ImportCommitRequest, db: sqlite3.Connection = Depends(get_db)):
    try:
        return repo_import.commit_import(db, body.token)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
