"""Analysis parameter presets and the entry-rule bands the client mirrors
for inline validation (GET /api/config/entry-rules)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import EntryRulePatchRequest, ParamSetCreateRequest, ParamSetPatchRequest
from app.db import repo_params
from app.deps import get_db

router = APIRouter(prefix="/api", tags=["params"])

_PARAM_FIELD_MAP = {
    "name": "name",
    "spineTolMlb": "spine_tol_mlb",
    "weightTolCg": "weight_tol_cg",
    "objective": "objective",
    "dozenSize": "dozen_size",
    "specMinMlb": "spec_min_mlb",
    "specMaxMlb": "spec_max_mlb",
    "abTolCp": "ab_tol_cp",
    "minGroupSize": "min_group_size",
}

_ENTRY_RULE_FIELD_MAP = {
    "spineMaxDp": "spine_max_dp",
    "weightMaxDp": "weight_max_dp",
    "spineStepCp": "spine_step_cp",
    "weightStepCg": "weight_step_cg",
    "spineHardMinCp": "spine_hard_min_cp",
    "spineHardMaxCp": "spine_hard_max_cp",
    "spineWarnMinCp": "spine_warn_min_cp",
    "spineWarnMaxCp": "spine_warn_max_cp",
    "weightHardMinCg": "weight_hard_min_cg",
    "weightHardMaxCg": "weight_hard_max_cg",
    "weightWarnMinCg": "weight_warn_min_cg",
    "weightWarnMaxCg": "weight_warn_max_cg",
    "batchOutlierSpineCp": "batch_outlier_spine_cp",
    "batchOutlierWeightCg": "batch_outlier_weight_cg",
    "grainsPerGram": "grains_per_gram",
}


def _param_set_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "isDefault": bool(row["is_default"]),
        "spineTolMlb": row["spine_tol_mlb"],
        "weightTolCg": row["weight_tol_cg"],
        "objective": row["objective"],
        "dozenSize": row["dozen_size"],
        "specMinMlb": row["spec_min_mlb"],
        "specMaxMlb": row["spec_max_mlb"],
        "abTolCp": row["ab_tol_cp"],
        "minGroupSize": row["min_group_size"],
    }


@router.get("/params")
def list_params(db: sqlite3.Connection = Depends(get_db)):
    return [_param_set_dict(r) for r in repo_params.list_param_sets(db)]


@router.post("/params", status_code=201)
def create_params(body: ParamSetCreateRequest, db: sqlite3.Connection = Depends(get_db)):
    param_set_id = repo_params.create_param_set(
        db,
        name=body.name,
        spine_tol_mlb=body.spineTolMlb,
        weight_tol_cg=body.weightTolCg,
        objective=body.objective,
        dozen_size=body.dozenSize,
        spec_min_mlb=body.specMinMlb,
        spec_max_mlb=body.specMaxMlb,
        ab_tol_cp=body.abTolCp,
        min_group_size=body.minGroupSize,
    )
    row = db.execute("SELECT * FROM param_set WHERE id = ?", (param_set_id,)).fetchone()
    return _param_set_dict(row)


@router.post("/params/{param_set_id}:makeDefault")
def make_default_params(param_set_id: int, db: sqlite3.Connection = Depends(get_db)):
    try:
        repo_params.set_default_param_set(db, param_set_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    row = db.execute("SELECT * FROM param_set WHERE id = ?", (param_set_id,)).fetchone()
    return _param_set_dict(row)


@router.patch("/params/{param_set_id}")
def patch_params(
    param_set_id: int, body: ParamSetPatchRequest, db: sqlite3.Connection = Depends(get_db)
):
    fields = body.model_dump(exclude_unset=True)
    db_fields = {_PARAM_FIELD_MAP[k]: v for k, v in fields.items()}
    repo_params.update_param_set(db, param_set_id, db_fields)
    row = db.execute("SELECT * FROM param_set WHERE id = ?", (param_set_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no such param set {param_set_id}")
    return _param_set_dict(row)


def _entry_rule_dict(row: sqlite3.Row) -> dict:
    return {
        "spineMaxDp": row["spine_max_dp"],
        "weightMaxDp": row["weight_max_dp"],
        "spineStepCp": row["spine_step_cp"],
        "weightStepCg": row["weight_step_cg"],
        "spineHardMinCp": row["spine_hard_min_cp"],
        "spineHardMaxCp": row["spine_hard_max_cp"],
        "spineWarnMinCp": row["spine_warn_min_cp"],
        "spineWarnMaxCp": row["spine_warn_max_cp"],
        "weightHardMinCg": row["weight_hard_min_cg"],
        "weightHardMaxCg": row["weight_hard_max_cg"],
        "weightWarnMinCg": row["weight_warn_min_cg"],
        "weightWarnMaxCg": row["weight_warn_max_cg"],
        "batchOutlierSpineCp": row["batch_outlier_spine_cp"],
        "batchOutlierWeightCg": row["batch_outlier_weight_cg"],
        "grainsPerGram": row["grains_per_gram"],
    }


@router.get("/config/entry-rules")
def get_entry_rules(db: sqlite3.Connection = Depends(get_db)):
    return _entry_rule_dict(repo_params.get_entry_rules(db))


@router.patch("/config/entry-rules")
def patch_entry_rules(body: EntryRulePatchRequest, db: sqlite3.Connection = Depends(get_db)):
    fields = body.model_dump(exclude_unset=True)
    db_fields = {_ENTRY_RULE_FIELD_MAP[k]: v for k, v in fields.items()}
    repo_params.update_entry_rules(db, db_fields)
    return _entry_rule_dict(repo_params.get_entry_rules(db))
