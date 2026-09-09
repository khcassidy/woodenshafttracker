"""CRUD for the three ordered lookup lists: diameter, wood, shop.

sort_order is deliberately not unique. Reordering rewrites 1..n in one
transaction so a pull-down never falls back to alphabetical order -- that
is the explicit requirement the column exists for.
"""

from __future__ import annotations

import sqlite3

_TABLES = {"diameter": "diameter_option", "wood": "wood_option", "shop": "shop"}


class UnknownLookupKind(ValueError):
    pass


def _table(kind: str) -> str:
    try:
        return _TABLES[kind]
    except KeyError:
        raise UnknownLookupKind(kind) from None


def list_options(conn: sqlite3.Connection, kind: str) -> list[sqlite3.Row]:
    table = _table(kind)
    return conn.execute(f"SELECT * FROM {table} ORDER BY sort_order, id").fetchall()


def get_option(conn: sqlite3.Connection, kind: str, option_id: int) -> sqlite3.Row | None:
    table = _table(kind)
    return conn.execute(f"SELECT * FROM {table} WHERE id = ?", (option_id,)).fetchone()


def reorder_options(conn: sqlite3.Connection, kind: str, ordered_ids: list[int]) -> None:
    table = _table(kind)
    for position, option_id in enumerate(ordered_ids, start=1):
        conn.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (position, option_id))
    conn.commit()


def _next_sort_order(conn: sqlite3.Connection, table: str) -> int:
    # Exclude the Unknown sentinel (sort_order = 999) for diameter/wood, so
    # a newly created option lands after the real entries, not after
    # Unknown -- shop has no such sentinel to exclude.
    where = "WHERE is_unknown = 0" if table in ("diameter_option", "wood_option") else ""
    row = conn.execute(
        f"SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM {table} {where}"
    ).fetchone()
    return row["n"]


def create_diameter_option(conn: sqlite3.Connection, label: str, sixty_fourths: int | None) -> int:
    sort_order = _next_sort_order(conn, "diameter_option")
    cur = conn.execute(
        "INSERT INTO diameter_option(label, sixty_fourths, sort_order) VALUES (?, ?, ?)",
        (label, sixty_fourths, sort_order),
    )
    conn.commit()
    return cur.lastrowid


def create_wood_option(conn: sqlite3.Connection, label: str) -> int:
    sort_order = _next_sort_order(conn, "wood_option")
    cur = conn.execute(
        "INSERT INTO wood_option(label, sort_order) VALUES (?, ?)", (label, sort_order)
    )
    conn.commit()
    return cur.lastrowid


def create_shop(conn: sqlite3.Connection, label: str, url: str | None, notes: str | None) -> int:
    sort_order = _next_sort_order(conn, "shop")
    cur = conn.execute(
        "INSERT INTO shop(label, sort_order, url, notes) VALUES (?, ?, ?, ?)",
        (label, sort_order, url, notes),
    )
    conn.commit()
    return cur.lastrowid


def set_active(conn: sqlite3.Connection, kind: str, option_id: int, is_active: bool) -> None:
    table = _table(kind)
    conn.execute(
        f"UPDATE {table} SET is_active = ? WHERE id = ?", (1 if is_active else 0, option_id)
    )
    conn.commit()


# Per-kind whitelist beyond "label", which every kind allows. Guards the
# f-string UPDATE below the same way the other repo modules' whitelists do.
_EXTRA_COLUMNS = {
    "diameter": {"sixty_fourths"},
    "wood": set(),
    "shop": {"url", "notes"},
}


def update_option(conn: sqlite3.Connection, kind: str, option_id: int, fields: dict) -> None:
    """fields uses DB column names (label, sixty_fourths, url, notes)."""
    if not fields:
        return
    table = _table(kind)
    allowed = {"label"} | _EXTRA_COLUMNS[kind]
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"not editable on {kind}: {unknown}")
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [option_id]
    conn.execute(f"UPDATE {table} SET {columns} WHERE id = ?", values)
    conn.commit()
