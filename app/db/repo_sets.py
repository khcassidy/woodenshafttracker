"""The manual set builder: build a matched set from chosen shafts, and
disband one back to the pool.

Membership lives on shaft.consumed_set_id (see 0001_initial.sql), not a
join table, so "is this shaft free" is a plain WHERE and a 409 race is a
single UPDATE...WHERE whose row count either matches the request or
doesn't -- no separate lock is needed.
"""

from __future__ import annotations

import sqlite3


class SetMembersConsumedError(Exception):
    """Raised when one or more requested shafts were already consumed into
    another set by the time this build actually ran -- the concurrency
    case slice 2's contract requires a 409 for."""

    def __init__(self, shaft_ids: list[int]):
        self.shaft_ids = shaft_ids
        super().__init__(f"already used in another set: {shaft_ids}")


def _set_row_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "targetSize": row["target_size"],
        "diameterId": row["diameter_id"],
        "diameterLabel": row["diameter_label"],
        "woodId": row["wood_id"],
        "woodLabel": row["wood_label"],
        "memberCount": row["member_count"],
        "notes": row["notes"],
        "createdAt": row["created_at"],
        "disbandedAt": row["disbanded_at"],
    }


_SET_LIST_SQL = """
  SELECT a.*, d.label AS diameter_label, w.label AS wood_label,
         (SELECT COUNT(*) FROM shaft WHERE consumed_set_id = a.id) AS member_count
  FROM arrow_set a
  JOIN diameter_option d ON d.id = a.diameter_id
  JOIN wood_option w ON w.id = a.wood_id
"""


def list_sets(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"{_SET_LIST_SQL} ORDER BY a.created_at DESC, a.id DESC").fetchall()
    return [_set_row_dict(r) for r in rows]


def get_set(conn: sqlite3.Connection, set_id: int) -> dict | None:
    row = conn.execute(f"{_SET_LIST_SQL} WHERE a.id = ?", (set_id,)).fetchone()
    if row is None:
        return None
    members = conn.execute(
        "SELECT * FROM shaft_entry_v WHERE consumed_set_id = ? ORDER BY batch_no, seq",
        (set_id,),
    ).fetchall()
    return {**_set_row_dict(row), "members": [dict(m) for m in members]}


def _validate_shafts_for_partition(
    conn: sqlite3.Connection, shaft_ids: list[int], diameter_id: int, wood_id: int
) -> None:
    """Every shaft must exist, sit in the given (diameter, wood) partition
    -- a set may span batches, but never wood or diameter, per the
    confirmed product decision -- and not already belong to another set.
    Shared by create_set and add_members, since adding to an existing set
    must satisfy the exact same rules a fresh build does."""
    rows = conn.execute(
        f"SELECT id, diameter_id, wood_id, consumed_set_id FROM shaft "
        f"WHERE id IN ({','.join('?' * len(shaft_ids))})",
        shaft_ids,
    ).fetchall()
    found_ids = {r["id"] for r in rows}
    missing = [sid for sid in shaft_ids if sid not in found_ids]
    if missing:
        raise ValueError(f"no such shaft(s): {missing}")

    mixed = [
        r["id"] for r in rows if r["diameter_id"] != diameter_id or r["wood_id"] != wood_id
    ]
    if mixed:
        raise ValueError(
            f"shaft(s) {mixed} do not match the set's diameter/wood partition"
        )

    already_consumed = [r["id"] for r in rows if r["consumed_set_id"] is not None]
    if already_consumed:
        raise SetMembersConsumedError(already_consumed)


def _consume_shafts(conn: sqlite3.Connection, set_id: int, shaft_ids: list[int]) -> None:
    """Marks shaft_ids consumed by set_id, racing safely against a
    concurrent build/add that might grab the same shaft first -- a 409
    is a single UPDATE...WHERE whose row count either matches the
    request or doesn't, no separate lock needed. Raises
    SetMembersConsumedError naming exactly the shafts that lost the
    race, and rolls back so nothing is left half-consumed; the caller's
    own uncommitted work (a just-inserted arrow_set row, say) rolls back
    with it."""
    placeholders = ",".join("?" * len(shaft_ids))
    cur = conn.execute(
        f"""UPDATE shaft SET consumed_set_id = ?, consumed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE id IN ({placeholders}) AND consumed_set_id IS NULL""",
        [set_id, *shaft_ids],
    )
    if cur.rowcount != len(shaft_ids):
        still_free = {
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM shaft WHERE id IN ({placeholders}) AND consumed_set_id = ?",
                [*shaft_ids, set_id],
            ).fetchall()
        }
        conflicting = [sid for sid in shaft_ids if sid not in still_free]
        conn.rollback()
        raise SetMembersConsumedError(conflicting)


def create_set(
    conn: sqlite3.Connection,
    *,
    name: str,
    diameter_id: int,
    wood_id: int,
    shaft_ids: list[int],
    target_size: int = 12,
    notes: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Builds one set from shaft_ids.

    A replayed idempotency_key returns the set already built by the first
    call rather than erroring or building a duplicate, so a retried
    request after a dropped response is safe.
    """
    if idempotency_key:
        existing = conn.execute(
            "SELECT id FROM arrow_set WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            return get_set(conn, existing["id"])

    if not shaft_ids:
        raise ValueError("a set needs at least one shaft")

    _validate_shafts_for_partition(conn, shaft_ids, diameter_id, wood_id)

    pool_version = conn.execute(
        "SELECT int_value FROM app_meta WHERE key = 'pool_version'"
    ).fetchone()["int_value"]

    cur = conn.execute(
        """INSERT INTO arrow_set
           (name, target_size, diameter_id, wood_id, pool_version_at_build,
            idempotency_key, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, target_size, diameter_id, wood_id, pool_version, idempotency_key, notes),
    )
    set_id = cur.lastrowid

    _consume_shafts(conn, set_id, shaft_ids)

    conn.commit()
    return get_set(conn, set_id)


def add_members(conn: sqlite3.Connection, set_id: int, shaft_ids: list[int]) -> dict:
    """Adds already-available shafts from the same (diameter, wood)
    partition into an existing, still-active set, without disturbing its
    current members. A disbanded set can't gain new members -- rebuild a
    fresh set instead, same as a disbanded set can't be re-disbanded."""
    set_row = conn.execute(
        "SELECT id, diameter_id, wood_id, disbanded_at FROM arrow_set WHERE id = ?", (set_id,)
    ).fetchone()
    if set_row is None:
        raise KeyError(set_id)
    if set_row["disbanded_at"] is not None:
        raise ValueError(f"set {set_id} is disbanded and can't gain members")

    _validate_shafts_for_partition(conn, shaft_ids, set_row["diameter_id"], set_row["wood_id"])
    _consume_shafts(conn, set_id, shaft_ids)

    conn.commit()
    return get_set(conn, set_id)


def remove_members(conn: sqlite3.Connection, set_id: int, shaft_ids: list[int]) -> dict:
    """Returns specific shafts from an existing, still-active set back to
    the pool, leaving the rest of the set's members untouched -- unlike
    disband_set, which releases every member at once and marks the whole
    set disbanded. A set may end up with zero members this way; that's a
    valid, still-active state, not an automatic disband, so shafts can
    still be added back to it afterward."""
    set_row = conn.execute(
        "SELECT id, disbanded_at FROM arrow_set WHERE id = ?", (set_id,)
    ).fetchone()
    if set_row is None:
        raise KeyError(set_id)
    if set_row["disbanded_at"] is not None:
        raise ValueError(f"set {set_id} is already disbanded")

    placeholders = ",".join("?" * len(shaft_ids))
    rows = conn.execute(
        f"SELECT id, consumed_set_id FROM shaft WHERE id IN ({placeholders})", shaft_ids
    ).fetchall()
    found_ids = {r["id"] for r in rows}
    missing = [sid for sid in shaft_ids if sid not in found_ids]
    if missing:
        raise ValueError(f"no such shaft(s): {missing}")

    not_members = [r["id"] for r in rows if r["consumed_set_id"] != set_id]
    if not_members:
        raise ValueError(f"shaft(s) {not_members} are not members of set {set_id}")

    conn.execute(
        f"UPDATE shaft SET consumed_set_id = NULL, consumed_at = NULL WHERE id IN ({placeholders})",
        shaft_ids,
    )
    conn.commit()
    return get_set(conn, set_id)


def update_set_notes(conn: sqlite3.Connection, set_id: int, notes: str | None) -> dict:
    """Edits a set's comment after creation. Works on a disbanded set too,
    same as a batch's own description field, since a note about why a set
    was built or later broken up stays useful after the fact."""
    existing = conn.execute("SELECT id FROM arrow_set WHERE id = ?", (set_id,)).fetchone()
    if existing is None:
        raise KeyError(set_id)
    conn.execute("UPDATE arrow_set SET notes = ? WHERE id = ?", (notes, set_id))
    conn.commit()
    return get_set(conn, set_id)


def disband_set(conn: sqlite3.Connection, set_id: int) -> dict:
    """Returns every member shaft to the pool and marks the set disbanded.
    The set row itself stays, as a record of what was once built."""
    existing = conn.execute("SELECT id, disbanded_at FROM arrow_set WHERE id = ?", (set_id,)).fetchone()
    if existing is None:
        raise KeyError(set_id)
    if existing["disbanded_at"] is not None:
        raise ValueError(f"set {set_id} is already disbanded")

    conn.execute(
        "UPDATE shaft SET consumed_set_id = NULL, consumed_at = NULL WHERE consumed_set_id = ?",
        (set_id,),
    )
    conn.execute(
        "UPDATE arrow_set SET disbanded_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
        (set_id,),
    )
    conn.commit()
    return get_set(conn, set_id)


def delete_set(conn: sqlite3.Connection, set_id: int) -> None:
    """Permanently removes a disbanded set's own record. A set must be
    disbanded first -- that step is what guarantees no shaft still points
    at consumed_set_id = set_id, so a live set can't be purged out from
    under its members."""
    existing = conn.execute(
        "SELECT id, disbanded_at FROM arrow_set WHERE id = ?", (set_id,)
    ).fetchone()
    if existing is None:
        raise KeyError(set_id)
    if existing["disbanded_at"] is None:
        raise ValueError(f"set {set_id} must be disbanded before it can be deleted")
    conn.execute("DELETE FROM arrow_set WHERE id = ?", (set_id,))
    conn.commit()
