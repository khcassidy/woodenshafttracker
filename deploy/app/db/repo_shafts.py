"""The only module that writes shaft + shaft_spine_reading.

Every write recomputes the materialised derived columns in the same
transaction, so avg_spine_mlb is never stale relative to the readings it
was built from. Validation runs in order -- shape (at parse), hard band,
step, warn band, batch outlier -- and only a hard-band failure blocks the
write; everything else comes back as a non-blocking warning.
"""

from __future__ import annotations

import sqlite3
import statistics

from core.derive import derive_spine
from core.units import UnitError, parse_spine_lb, parse_weight
from core.validate import ValidationBlocked, check_batch_outlier, check_spine_reading, check_weight_reading

_SORT_COLUMNS = {"seq": "seq", "weight": "weight_cg", "spine": "avg_spine_mlb"}


def get_shaft(conn: sqlite3.Connection, batch_id: int, seq: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM shaft_entry_v WHERE batch_id = ? AND seq = ?", (batch_id, seq)
    ).fetchone()


def list_shafts(
    conn: sqlite3.Connection, *, batch_id: int | None = None, sort: str = "seq"
) -> list[sqlite3.Row]:
    column = _SORT_COLUMNS.get(sort, "seq")
    where = "WHERE batch_id = ?" if batch_id is not None else ""
    params = (batch_id,) if batch_id is not None else ()
    return conn.execute(
        f"SELECT * FROM shaft_entry_v {where} ORDER BY {column}, seq", params
    ).fetchall()


def list_partition_shafts(
    conn: sqlite3.Connection, diameter_id: int, wood_id: int, available_only: bool = True
) -> list[sqlite3.Row]:
    """Candidate shafts for the manual set builder and the analysis
    engine: every shaft in this (diameter, wood) partition, or (by
    default) only the ones actually free to use -- not consumed, not
    junk, and fully measured, matching the same 'available' definition
    GET /api/partitions uses for its counts."""
    where = "WHERE diameter_id = ? AND wood_id = ?"
    params: list = [diameter_id, wood_id]
    if available_only:
        where += (
            " AND consumed_set_id IS NULL"
            " AND (straightness IS NULL OR straightness <> 'JUNK')"
            " AND avg_spine_mlb IS NOT NULL AND weight_cg IS NOT NULL"
        )
    return conn.execute(
        f"SELECT * FROM shaft_entry_v {where} ORDER BY batch_no, seq", params
    ).fetchall()


def _recompute_spine(conn: sqlite3.Connection, shaft_id: int) -> None:
    readings = conn.execute(
        "SELECT value_cp FROM shaft_spine_reading WHERE shaft_id = ? ORDER BY ordinal",
        (shaft_id,),
    ).fetchall()
    derived = derive_spine([r["value_cp"] for r in readings])
    if derived is None:
        conn.execute(
            """UPDATE shaft SET spine_count=0, spine_sum_cp=0, spine_min_cp=NULL,
               spine_max_cp=NULL, avg_spine_mlb=NULL, spine_spread_cp=NULL,
               updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id = ?""",
            (shaft_id,),
        )
    else:
        conn.execute(
            """UPDATE shaft SET spine_count=?, spine_sum_cp=?, spine_min_cp=?,
               spine_max_cp=?, avg_spine_mlb=?, spine_spread_cp=?,
               updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id = ?""",
            (
                derived.spine_count,
                derived.spine_sum_cp,
                derived.spine_min_cp,
                derived.spine_max_cp,
                derived.avg_spine_mlb,
                derived.spine_spread_cp,
                shaft_id,
            ),
        )


def _upsert_reading(
    conn: sqlite3.Connection, shaft_id: int, ordinal: int, raw: str | None, rules: sqlite3.Row,
    warnings: list[dict],
) -> None:
    if raw is None:
        conn.execute(
            "DELETE FROM shaft_spine_reading WHERE shaft_id = ? AND ordinal = ?",
            (shaft_id, ordinal),
        )
        return
    value_cp = parse_spine_lb(raw)  # UnitError propagates -> 422 at the API layer
    issues = check_spine_reading(
        value_cp,
        step_cp=rules["spine_step_cp"],
        hard_min_cp=rules["spine_hard_min_cp"],
        hard_max_cp=rules["spine_hard_max_cp"],
        warn_min_cp=rules["spine_warn_min_cp"],
        warn_max_cp=rules["spine_warn_max_cp"],
    )
    blocking = [i for i in issues if i.blocking]
    if blocking:
        raise ValidationBlocked(blocking)
    warnings.extend({"code": i.code, "message": i.message} for i in issues)
    existing = conn.execute(
        "SELECT id FROM shaft_spine_reading WHERE shaft_id = ? AND ordinal = ?",
        (shaft_id, ordinal),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE shaft_spine_reading SET value_cp = ?, entered_text = ? WHERE id = ?",
            (value_cp, raw, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO shaft_spine_reading(shaft_id, ordinal, value_cp, entered_text) "
            "VALUES (?, ?, ?, ?)",
            (shaft_id, ordinal, value_cp, raw),
        )


def _apply_weight(
    conn: sqlite3.Connection, shaft_id: int, raw: str | None, unit: str, rules: sqlite3.Row,
    warnings: list[dict],
) -> None:
    if raw is None:
        conn.execute(
            "UPDATE shaft SET weight_cg=NULL, weight_text=NULL, weight_unit=NULL, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
            (shaft_id,),
        )
        return
    value_cg = parse_weight(raw, unit)  # UnitError propagates -> 422
    issues = check_weight_reading(
        value_cg,
        step_cg=rules["weight_step_cg"],
        hard_min_cg=rules["weight_hard_min_cg"],
        hard_max_cg=rules["weight_hard_max_cg"],
        warn_min_cg=rules["weight_warn_min_cg"],
        warn_max_cg=rules["weight_warn_max_cg"],
    )
    blocking = [i for i in issues if i.blocking]
    if blocking:
        raise ValidationBlocked(blocking)
    warnings.extend({"code": i.code, "message": i.message} for i in issues)
    conn.execute(
        "UPDATE shaft SET weight_cg=?, weight_text=?, weight_unit=?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
        (value_cg, raw, unit, shaft_id),
    )


def _batch_outlier_warnings(
    conn: sqlite3.Connection, batch_id: int, shaft_id: int, column: str, tolerance: int,
    unit_label: str,
) -> list[dict]:
    """Once a batch holds 5+ other measured shafts, warn when this shaft's
    value sits far from the batch median. This is the check that catches a
    transposed digit (566 typed for 56) that every range check passes."""
    rows = conn.execute(
        f"SELECT {column} AS v FROM shaft WHERE batch_id = ? AND {column} IS NOT NULL AND id != ?",
        (batch_id, shaft_id),
    ).fetchall()
    if len(rows) < 5:
        return []
    median = statistics.median_low(sorted(r["v"] for r in rows))
    current = conn.execute(f"SELECT {column} AS v FROM shaft WHERE id = ?", (shaft_id,)).fetchone()["v"]
    if current is None:
        return []
    issues = check_batch_outlier(current, median, tolerance, unit_label)
    return [{"code": i.code, "message": i.message} for i in issues]


def patch_shaft_entry(conn: sqlite3.Connection, batch_id: int, seq: int, fields: dict) -> dict:
    """fields holds only the keys the caller actually set (the API layer
    passes body.model_dump(exclude_unset=True)), so an omitted field is
    left untouched and an explicit null clears it."""
    shaft = conn.execute(
        "SELECT id FROM shaft WHERE batch_id = ? AND seq = ?", (batch_id, seq)
    ).fetchone()
    if shaft is None:
        raise KeyError((batch_id, seq))
    shaft_id = shaft["id"]
    rules = conn.execute("SELECT * FROM entry_rule WHERE id = 1").fetchone()
    warnings: list[dict] = []

    spine_touched = False
    if "spineA" in fields:
        _upsert_reading(conn, shaft_id, 1, fields["spineA"], rules, warnings)
        spine_touched = True
    if "spineB" in fields:
        _upsert_reading(conn, shaft_id, 2, fields["spineB"], rules, warnings)
        spine_touched = True

    if spine_touched:
        _recompute_spine(conn, shaft_id)
        warnings.extend(
            _batch_outlier_warnings(
                conn, batch_id, shaft_id, "avg_spine_mlb", rules["batch_outlier_spine_cp"] * 10, "mlb"
            )
        )

    if "weight" in fields:
        _apply_weight(conn, shaft_id, fields["weight"], fields.get("weightUnit", "g"), rules, warnings)
        if fields["weight"] is not None:
            warnings.extend(
                _batch_outlier_warnings(
                    conn, batch_id, shaft_id, "weight_cg", rules["batch_outlier_weight_cg"], "cg"
                )
            )

    if "straightness" in fields:
        conn.execute(
            "UPDATE shaft SET straightness = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
            "WHERE id = ?",
            (fields["straightness"], shaft_id),
        )

    if "notes" in fields:
        conn.execute(
            "UPDATE shaft SET notes = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
            "WHERE id = ?",
            (fields["notes"], shaft_id),
        )

    conn.commit()
    return {"warnings": warnings}


def bulk_patch(conn: sqlite3.Connection, batch_id: int, items: list[dict]) -> dict:
    """Applies each item independently: one item's failure does not abort
    the rest. A flaky-wifi queue must not lose 40 shafts of work because
    one value now fails validation."""
    results = []
    for item in items:
        try:
            outcome = patch_shaft_entry(conn, batch_id, item["seq"], item["fields"])
            results.append({"seq": item["seq"], "ok": True, "warnings": outcome["warnings"]})
        except (UnitError, ValidationBlocked) as exc:
            results.append({"seq": item["seq"], "ok": False, "error": str(exc)})
        except KeyError:
            results.append({"seq": item["seq"], "ok": False, "error": "no such shaft"})
    return {"results": results}


def entry_state(conn: sqlite3.Connection, batch_id: int) -> dict:
    """weight_cg stays the single canonical column regardless of which
    unit was typed, so 'weight done' and pass selection below don't change
    with the grams/grains split. nextFocus for weight always names the
    grams column ('weightG') as the default entry point -- the grid's ring
    has separate grams and grains cells, and grains is the derived one."""
    batch = conn.execute("SELECT * FROM batch WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise KeyError(batch_id)

    counts = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN spine_count >= 1 THEN 1 ELSE 0 END) AS spine_a_done,
             SUM(CASE WHEN spine_count >= 2 THEN 1 ELSE 0 END) AS spine_b_done,
             SUM(CASE WHEN weight_cg IS NOT NULL THEN 1 ELSE 0 END) AS weight_done,
             SUM(CASE WHEN straightness IS NOT NULL THEN 1 ELSE 0 END) AS straightness_done
           FROM shaft WHERE batch_id = ?""",
        (batch_id,),
    ).fetchone()

    mode = batch["entry_mode"]
    pass_: str | None = None

    if mode == "per_shaft":
        row = conn.execute(
            """SELECT seq, spine_count FROM shaft
               WHERE batch_id = ? AND (spine_count < 2 OR weight_cg IS NULL)
               ORDER BY seq LIMIT 1""",
            (batch_id,),
        ).fetchone()
        if row is None:
            next_focus = None
        elif row["spine_count"] < 1:
            next_focus = {"seq": row["seq"], "field": "spineA"}
        elif row["spine_count"] < 2:
            next_focus = {"seq": row["seq"], "field": "spineB"}
        else:
            next_focus = {"seq": row["seq"], "field": "weightG"}
    else:
        spine_row = conn.execute(
            "SELECT seq FROM shaft WHERE batch_id = ? AND spine_count < 1 ORDER BY seq LIMIT 1",
            (batch_id,),
        ).fetchone()
        if spine_row is not None:
            pass_ = "spine"
            next_focus = {"seq": spine_row["seq"], "field": "spineA"}
        else:
            weight_row = conn.execute(
                "SELECT seq FROM shaft WHERE batch_id = ? AND weight_cg IS NULL ORDER BY seq LIMIT 1",
                (batch_id,),
            ).fetchone()
            if weight_row is not None:
                pass_ = "weight"
                next_focus = {"seq": weight_row["seq"], "field": "weightG"}
            else:
                straight_row = conn.execute(
                    "SELECT seq FROM shaft WHERE batch_id = ? AND straightness IS NULL "
                    "ORDER BY seq LIMIT 1",
                    (batch_id,),
                ).fetchone()
                if straight_row is not None:
                    pass_ = "straightness"
                    next_focus = {"seq": straight_row["seq"], "field": "straightness"}
                else:
                    next_focus = None
        if pass_ != batch["entry_pass"]:
            conn.execute("UPDATE batch SET entry_pass = ? WHERE id = ?", (pass_, batch_id))
            conn.commit()

    pool_version = conn.execute(
        "SELECT int_value FROM app_meta WHERE key = 'pool_version'"
    ).fetchone()["int_value"]

    return {
        "mode": mode,
        "pass": pass_,
        "counts": {
            "total": counts["total"],
            "spineA": counts["spine_a_done"],
            "spineB": counts["spine_b_done"],
            "weight": counts["weight_done"],
            "straightness": counts["straightness_done"],
        },
        "nextFocus": next_focus,
        "complete": next_focus is None,
        "poolVersion": pool_version,
    }
