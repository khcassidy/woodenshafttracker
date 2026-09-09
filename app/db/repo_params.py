"""Analysis parameter presets and the singleton entry_rule row."""

from __future__ import annotations

import sqlite3

# Whitelist: db_fields passed to update_param_set become column names in an
# f-string UPDATE, so only names this module itself produces are trusted.
_ALLOWED_PARAM_COLUMNS = {
    "spine_tol_mlb",
    "weight_tol_cg",
    "objective",
    "dozen_size",
    "spec_min_mlb",
    "spec_max_mlb",
    "ab_tol_cp",
    "min_group_size",
    "name",
}


def list_param_sets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM param_set ORDER BY is_default DESC, name").fetchall()


def get_default_param_set(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM param_set WHERE is_default = 1").fetchone()


def create_param_set(
    conn: sqlite3.Connection,
    *,
    name: str,
    spine_tol_mlb: int,
    weight_tol_cg: int,
    objective: str,
    dozen_size: int,
    spec_min_mlb: int,
    spec_max_mlb: int,
    ab_tol_cp: int,
    min_group_size: int,
) -> int:
    """New sets are never created as the default -- is_default has a
    partial UNIQUE index (at most one row), so becoming the default is
    always a separate, explicit action (set_default_param_set)."""
    cur = conn.execute(
        """INSERT INTO param_set
           (name, spine_tol_mlb, weight_tol_cg, objective, dozen_size,
            spec_min_mlb, spec_max_mlb, ab_tol_cp, min_group_size)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name,
            spine_tol_mlb,
            weight_tol_cg,
            objective,
            dozen_size,
            spec_min_mlb,
            spec_max_mlb,
            ab_tol_cp,
            min_group_size,
        ),
    )
    conn.commit()
    return cur.lastrowid


def set_default_param_set(conn: sqlite3.Connection, param_set_id: int) -> None:
    """Clears the previous default before setting the new one, in that
    order, so the two UPDATEs never both leave two rows with is_default=1
    at once -- the partial UNIQUE index would reject that mid-transaction."""
    existing = conn.execute(
        "SELECT id FROM param_set WHERE id = ?", (param_set_id,)
    ).fetchone()
    if existing is None:
        raise ValueError(f"no such param set {param_set_id}")
    conn.execute("UPDATE param_set SET is_default = 0 WHERE is_default = 1")
    conn.execute("UPDATE param_set SET is_default = 1 WHERE id = ?", (param_set_id,))
    conn.commit()


def get_entry_rules(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM entry_rule WHERE id = 1").fetchone()


def update_param_set(conn: sqlite3.Connection, param_set_id: int, fields: dict) -> None:
    if not fields:
        return
    unknown = set(fields) - _ALLOWED_PARAM_COLUMNS
    if unknown:
        raise ValueError(f"not a param_set column: {unknown}")
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [param_set_id]
    conn.execute(
        f"UPDATE param_set SET {columns}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
        f"WHERE id = ?",
        values,
    )
    conn.commit()


_ALLOWED_ENTRY_RULE_COLUMNS = {
    "spine_max_dp",
    "weight_max_dp",
    "spine_step_cp",
    "weight_step_cg",
    "spine_hard_min_cp",
    "spine_hard_max_cp",
    "spine_warn_min_cp",
    "spine_warn_max_cp",
    "weight_hard_min_cg",
    "weight_hard_max_cg",
    "weight_warn_min_cg",
    "weight_warn_max_cg",
    "batch_outlier_spine_cp",
    "batch_outlier_weight_cg",
    "grains_per_gram",
}


def update_entry_rules(conn: sqlite3.Connection, fields: dict) -> None:
    if not fields:
        return
    unknown = set(fields) - _ALLOWED_ENTRY_RULE_COLUMNS
    if unknown:
        raise ValueError(f"not an entry_rule column: {unknown}")
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    conn.execute(f"UPDATE entry_rule SET {columns} WHERE id = 1", values)
    conn.commit()
