"""CSV/JSON import: stage into import_run for preview, then commit.

Both formats feed the same pipeline through one canonical row shape --
csv_io.to_staged_rows() and json_io.to_staged_rows() each adapt their own
format into it, so everything below reads exactly one set of keys:
  batchNo, seq, diameter, wood, shop, purchaseDate, nominalSpineLabel,
  description, entryMode, spineA, spineB, weightText, weightUnit,
  straightness, notes

Staging always validates shape, positivity and the hard plausibility band
up front (via core.units and core.validate), so a committed import should
never fail on a value it already accepted at preview time. Commit reuses
create_batch and patch_shaft_entry rather than re-implementing batch/shaft
writes -- one place owns "how a batch and its shafts get written".

Scope, deliberately: import only ever CREATES batches whose batch_no does
not already exist. A batch_no already present is reported and skipped,
never merged or overwritten -- that avoids the much harder problem of
reconciling seq/seq_width against an existing batch, and the grid already
handles editing an existing batch's shafts.
"""

from __future__ import annotations

import json
import secrets
import sqlite3

from app.db import repo_batches, repo_shafts
from core.units import UnitError, parse_spine_lb, parse_weight
from core.validate import check_spine_reading, check_weight_reading

_STRAIGHTNESS_VALUES = {"EXCELLENT", "OK", "BAD", "JUNK"}


def _lookup_maps(conn: sqlite3.Connection) -> dict:
    def by_label(table):
        return {
            r["label"].lower(): r["id"]
            for r in conn.execute(f"SELECT id, label FROM {table}").fetchall()
        }

    return {"diameter": by_label("diameter_option"), "wood": by_label("wood_option"), "shop": by_label("shop")}


def stage_rows(conn: sqlite3.Connection, rows: list[dict], source_name: str, fmt: str) -> dict:
    """rows must already be in the canonical staged-row shape (see module
    docstring) -- callers use csv_io.to_staged_rows() or
    json_io.to_staged_rows() to get there from a raw upload."""
    lookups = _lookup_maps(conn)
    existing_batch_nos = {
        r["batch_no"] for r in conn.execute("SELECT batch_no FROM batch").fetchall()
    }
    rules = conn.execute("SELECT * FROM entry_rule WHERE id = 1").fetchone()

    errors: list[str] = []
    all_batch_nos: set[int] = set()
    groups: dict[int, dict] = {}  # batch_no -> {"meta": {...}, "shafts": {seq: {...}}}

    for i, row in enumerate(rows):
        line = i + 2  # header is line 1
        if row.get("batchNo") is None or row.get("seq") is None:
            errors.append(f"row {line}: missing batch number or seq")
            continue
        try:
            batch_no = int(row["batchNo"])
            seq = int(row["seq"])
        except (TypeError, ValueError):
            errors.append(f"row {line}: batch and seq must be whole numbers")
            continue
        all_batch_nos.add(batch_no)
        if batch_no in existing_batch_nos:
            continue  # reported in the summary, not per row

        group = groups.setdefault(batch_no, {"meta": {}, "shafts": {}})
        meta = group["meta"]
        for key in ("nominalSpineLabel", "purchaseDate", "description", "entryMode"):
            value = row.get(key)
            if value and key not in meta:
                meta[key] = value

        for kind, meta_key in (("diameter", "diameterId"), ("wood", "woodId"), ("shop", "shopId")):
            label = row.get(kind)
            if not label:
                continue
            option_id = lookups[kind].get(label.lower())
            if option_id is None:
                errors.append(f"row {line}: unknown {kind} '{label}'")
            else:
                meta[meta_key] = option_id

        spine_a_cp = spine_b_cp = None
        try:
            if row.get("spineA"):
                spine_a_cp = parse_spine_lb(row["spineA"])
                issue = next(iter(check_spine_reading(
                    spine_a_cp, step_cp=rules["spine_step_cp"],
                    hard_min_cp=rules["spine_hard_min_cp"], hard_max_cp=rules["spine_hard_max_cp"],
                    warn_min_cp=rules["spine_warn_min_cp"], warn_max_cp=rules["spine_warn_max_cp"],
                )), None)
                if issue and issue.blocking:
                    errors.append(f"row {line}: spine A {issue.message}")
            if row.get("spineB"):
                spine_b_cp = parse_spine_lb(row["spineB"])
        except UnitError as exc:
            errors.append(f"row {line}: spine reading -- {exc}")

        weight_cg = None
        weight_text, weight_unit = row.get("weightText"), row.get("weightUnit")
        if weight_text:
            try:
                weight_cg = parse_weight(weight_text, weight_unit)
                issue = next(iter(check_weight_reading(
                    weight_cg, step_cg=rules["weight_step_cg"],
                    hard_min_cg=rules["weight_hard_min_cg"], hard_max_cg=rules["weight_hard_max_cg"],
                    warn_min_cg=rules["weight_warn_min_cg"], warn_max_cg=rules["weight_warn_max_cg"],
                )), None)
                if issue and issue.blocking:
                    errors.append(f"row {line}: weight {issue.message}")
            except UnitError as exc:
                errors.append(f"row {line}: weight -- {exc}")

        straightness = row.get("straightness")
        if straightness:
            straightness = straightness.strip().upper()
            if straightness not in _STRAIGHTNESS_VALUES:
                errors.append(f"row {line}: unknown straightness '{straightness}'")
                straightness = None

        if seq in group["shafts"]:
            errors.append(f"row {line}: duplicate seq {seq} in batch {batch_no}")
            continue

        group["shafts"][seq] = {
            "spineA": row.get("spineA") if spine_a_cp else None,
            "spineB": row.get("spineB") if spine_b_cp else None,
            "weightText": weight_text if weight_cg else None,
            "weightUnit": weight_unit if weight_cg else None,
            "straightness": straightness,
            "notes": row.get("notes"),
        }

    row_count = sum(len(g["shafts"]) for g in groups.values())
    report = {
        "rowCount": row_count,
        "batchesNew": sorted(groups.keys()),
        "batchesSkippedExisting": sorted(all_batch_nos & existing_batch_nos),
        "errors": errors,
    }

    token = secrets.token_urlsafe(16)
    conn.execute(
        "INSERT INTO import_run"
        "(token, source_name, format, mode, row_count, status, payload_json, report_json) "
        "VALUES (?, ?, ?, 'create_only', ?, 'previewed', ?, ?)",
        (token, source_name, fmt, row_count, json.dumps(groups), json.dumps(report)),
    )
    conn.commit()
    return {"token": token, "report": report}


def commit_import(conn: sqlite3.Connection, token: str) -> dict:
    run = conn.execute("SELECT * FROM import_run WHERE token = ?", (token,)).fetchone()
    if run is None:
        raise ValueError(f"no staged import {token}")
    if run["status"] != "previewed":
        raise ValueError(f"import {token} is already {run['status']}")
    if run["report_json"] and json.loads(run["report_json"]).get("errors"):
        raise ValueError("this import has errors and cannot be committed")

    groups = json.loads(run["payload_json"])
    batches_created = 0
    shafts_written = 0

    for batch_no_str, group in groups.items():
        batch_no = int(batch_no_str)
        meta = group["meta"]
        expected_count = max((int(s) for s in group["shafts"]), default=0)
        nominal_min, nominal_max = repo_batches.parse_nominal_range(meta.get("nominalSpineLabel"))

        batch_id = repo_batches.create_batch(
            conn,
            batch_no=batch_no,
            expected_count=expected_count,
            nominal_spine_label=meta.get("nominalSpineLabel"),
            nominal_min_lb=nominal_min,
            nominal_max_lb=nominal_max,
            diameter_id=meta.get("diameterId", 0),
            wood_id=meta.get("woodId", 0),
            shop_id=meta.get("shopId"),
            purchase_date=meta.get("purchaseDate"),
            description=meta.get("description"),
            entry_mode=meta.get("entryMode") or "per_shaft",
        )
        batches_created += 1

        for seq_str, shaft_data in group["shafts"].items():
            seq = int(seq_str)
            fields = {
                k: v
                for k, v in {
                    "spineA": shaft_data.get("spineA"),
                    "spineB": shaft_data.get("spineB"),
                    "weight": shaft_data.get("weightText"),
                    "weightUnit": shaft_data.get("weightUnit"),
                    "straightness": shaft_data.get("straightness"),
                    "notes": shaft_data.get("notes"),
                }.items()
                if v is not None
            }
            if fields:
                repo_shafts.patch_shaft_entry(conn, batch_id, seq, fields)
            shafts_written += 1

    conn.execute(
        "UPDATE import_run SET status = 'committed', created_count = ?, "
        "committed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE token = ?",
        (batches_created, token),
    )
    conn.commit()
    return {"batchesCreated": batches_created, "shaftsWritten": shafts_written}
