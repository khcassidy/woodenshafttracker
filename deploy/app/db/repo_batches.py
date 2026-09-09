"""Batch creation and listing.

Creating a batch pre-creates its blank shaft rows in the same transaction,
so entry becomes pure UPDATE: seq and label are allocated up front, no row
ever appears or shifts under the cursor, and "partly measured" is the
natural resting state rather than a special case.
"""

from __future__ import annotations

import re
import sqlite3

from core.labels import required_seq_width, shaft_label

_NOMINAL_RANGE_RE = re.compile(r"^(\d+)-(\d+)#?$")


def parse_nominal_range(label: str | None) -> tuple[int | None, int | None]:
    """'55-60#' -> (55, 60). Display-only: never feeds the analysis."""
    if not label:
        return None, None
    match = _NOMINAL_RANGE_RE.match(label.strip())
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def create_batch(
    conn: sqlite3.Connection,
    *,
    batch_no: int,
    expected_count: int,
    nominal_spine_label: str | None = None,
    nominal_min_lb: int | None = None,
    nominal_max_lb: int | None = None,
    diameter_id: int = 0,
    wood_id: int = 0,
    shop_id: int | None = None,
    purchase_date: str | None = None,
    description: str | None = None,
    entry_mode: str = "per_shaft",
) -> int:
    seq_width = required_seq_width(expected_count)
    cur = conn.execute(
        """INSERT INTO batch
           (batch_no, seq_width, nominal_spine_label, nominal_min_lb, nominal_max_lb,
            diameter_id, wood_id, shop_id, purchase_date, expected_count,
            description, entry_mode, entry_pass)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            batch_no,
            seq_width,
            nominal_spine_label,
            nominal_min_lb,
            nominal_max_lb,
            diameter_id,
            wood_id,
            shop_id,
            purchase_date,
            expected_count,
            description,
            entry_mode,
            "spine" if entry_mode == "per_field" else None,
        ),
    )
    batch_id = cur.lastrowid
    for seq in range(1, expected_count + 1):
        label = shaft_label(batch_no, seq, seq_width)
        conn.execute(
            "INSERT INTO shaft(batch_id, seq, label, diameter_id, wood_id) VALUES (?, ?, ?, ?, ?)",
            (batch_id, seq, label, diameter_id, wood_id),
        )
    conn.commit()
    return batch_id


def get_batch(conn: sqlite3.Connection, batch_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM batch WHERE id = ?", (batch_id,)).fetchone()


def delete_batch(conn: sqlite3.Connection, batch_id: int) -> None:
    """Deletes a batch and every one of its shafts. Refused if any shaft
    is already consumed into a set -- same rule as delete_shaft, for the
    same reason: that record needs to stay put for the set's history.
    Spine readings cascade with their shaft (ON DELETE CASCADE); the
    shaft rows must be deleted before the batch row, since
    shaft.batch_id REFERENCES batch(id) ON DELETE RESTRICT.
    """
    batch = get_batch(conn, batch_id)
    if batch is None:
        raise ValueError(f"no such batch {batch_id}")
    consumed = conn.execute(
        "SELECT COUNT(*) AS n FROM shaft WHERE batch_id = ? AND consumed_set_id IS NOT NULL",
        (batch_id,),
    ).fetchone()["n"]
    if consumed:
        raise ValueError(
            f"cannot delete batch {batch['batch_no']}: {consumed} of its shafts "
            f"are already used in a set"
        )
    conn.execute("DELETE FROM shaft WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM batch WHERE id = ?", (batch_id,))
    conn.commit()


def list_batches(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM batch ORDER BY batch_no").fetchall()


# Whitelist: db_fields passed to update_batch become column names in an
# f-string UPDATE, so only names this module itself produces are trusted.
_ALLOWED_BATCH_COLUMNS = {
    "nominal_spine_label",
    "nominal_min_lb",
    "nominal_max_lb",
    "diameter_id",
    "wood_id",
    "shop_id",
    "purchase_date",
    "description",
}


def update_batch(conn: sqlite3.Connection, batch_id: int, fields: dict) -> None:
    """Edits batch metadata after creation: spine label, diameter, wood,
    shop, purchase date, comments. batch_no goes through rename_batch_no
    instead, since it needs to relabel every shaft in the batch. seq_width
    is never editable: it is derived once from the count at creation and
    every label's padding depends on it staying fixed. Does NOT cascade
    diameter_id or wood_id to existing shafts; those carry the truth the
    analysis reads (see the shaft table's own diameter_id/wood_id), and
    only ever change there explicitly, never as a silent side effect of a
    batch edit.
    """
    if not fields:
        return
    unknown = set(fields) - _ALLOWED_BATCH_COLUMNS
    if unknown:
        raise ValueError(f"not a batch column: {unknown}")
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [batch_id]
    conn.execute(
        f"UPDATE batch SET {columns}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
        f"WHERE id = ?",
        values,
    )
    conn.commit()


def rename_batch_no(conn: sqlite3.Connection, batch_id: int, new_batch_no: int) -> None:
    """Changes a batch's number and relabels every one of its shafts to
    match (seq and seq_width stay fixed, only the batch_no prefix changes).
    The batch_no UPDATE hits the table's UNIQUE constraint first if the
    number is already taken, so relabelling never runs against a batch_no
    that didn't actually become ours -- and once it succeeds, no other
    batch can hold that prefix, so the relabel can't collide either.
    """
    batch = get_batch(conn, batch_id)
    if batch is None:
        raise ValueError(f"no such batch {batch_id}")
    conn.execute(
        "UPDATE batch SET batch_no = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
        "WHERE id = ?",
        (new_batch_no, batch_id),
    )
    shafts = conn.execute(
        "SELECT id, seq FROM shaft WHERE batch_id = ?", (batch_id,)
    ).fetchall()
    for shaft in shafts:
        new_label = shaft_label(new_batch_no, shaft["seq"], batch["seq_width"])
        conn.execute("UPDATE shaft SET label = ? WHERE id = ?", (new_label, shaft["id"]))
    conn.commit()


def set_entry_mode(conn: sqlite3.Connection, batch_id: int, entry_mode: str) -> None:
    """Backs the F2 mode-toggle key in the entry grid. entry_pass resets to
    the first per_field pass on entry, or clears entirely for per_shaft."""
    entry_pass = "spine" if entry_mode == "per_field" else None
    conn.execute(
        "UPDATE batch SET entry_mode = ?, entry_pass = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
        (entry_mode, entry_pass, batch_id),
    )
    conn.commit()


def batch_summary(conn: sqlite3.Connection, batch_id: int) -> dict:
    row = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN weight_cg IS NOT NULL AND avg_spine_mlb IS NOT NULL
                      AND (straightness IS NULL OR straightness <> 'JUNK')
                 THEN 1 ELSE 0 END) AS available,
             SUM(CASE WHEN straightness = 'JUNK' THEN 1 ELSE 0 END) AS junk,
             SUM(CASE WHEN consumed_set_id IS NOT NULL THEN 1 ELSE 0 END) AS consumed,
             MIN(avg_spine_mlb) AS min_avg_spine_mlb,
             MAX(avg_spine_mlb) AS max_avg_spine_mlb,
             MIN(weight_cg) AS min_weight_cg,
             MAX(weight_cg) AS max_weight_cg
           FROM shaft WHERE batch_id = ?""",
        (batch_id,),
    ).fetchone()
    return dict(row)


def extend_batch(conn: sqlite3.Connection, batch_id: int, additional_count: int) -> int:
    """Handle a miscounted purchase: append more blank rows. seq_width is
    fixed at creation, so a physically marked shaft's label never changes
    silently when the batch grows -- extending past the fixed width fails
    instead."""
    batch = get_batch(conn, batch_id)
    if batch is None:
        raise ValueError(f"no such batch {batch_id}")
    current_max_seq = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS n FROM shaft WHERE batch_id = ?", (batch_id,)
    ).fetchone()["n"]
    new_total = current_max_seq + additional_count
    new_seq_width = required_seq_width(new_total)
    if new_seq_width != batch["seq_width"]:
        raise ValueError(
            f"extending batch {batch_id} to {new_total} shafts needs seq_width "
            f"{new_seq_width}, but it was fixed at {batch['seq_width']} at creation"
        )
    for seq in range(current_max_seq + 1, new_total + 1):
        label = shaft_label(batch["batch_no"], seq, batch["seq_width"])
        conn.execute(
            "INSERT INTO shaft(batch_id, seq, label, diameter_id, wood_id) VALUES (?, ?, ?, ?, ?)",
            (batch_id, seq, label, batch["diameter_id"], batch["wood_id"]),
        )
    conn.execute("UPDATE batch SET expected_count = ? WHERE id = ?", (new_total, batch_id))
    conn.commit()
    return new_total


def insert_shaft(conn: sqlite3.Connection, batch_id: int, after_seq: int) -> int:
    """Inserts one new blank shaft immediately after after_seq (0 inserts
    at the very front; after_seq == the current last seq is equivalent to
    appending). Every shaft at or past that position shifts up by one --
    processed highest-seq-first, so no (batch_id, seq) or label collides
    with a row that hasn't moved yet. Same seq_width guard as extend_batch:
    a shaft's label never changes silently because the batch grew past the
    width fixed at creation.
    """
    batch = get_batch(conn, batch_id)
    if batch is None:
        raise ValueError(f"no such batch {batch_id}")
    current_max_seq = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS n FROM shaft WHERE batch_id = ?", (batch_id,)
    ).fetchone()["n"]
    if after_seq < 0 or after_seq > current_max_seq:
        raise ValueError(f"after_seq {after_seq} is out of range for batch {batch_id}")

    new_total = current_max_seq + 1
    new_seq_width = required_seq_width(new_total)
    if new_seq_width != batch["seq_width"]:
        raise ValueError(
            f"inserting into batch {batch_id} needs seq_width {new_seq_width}, "
            f"but it was fixed at {batch['seq_width']} at creation"
        )

    shifting = conn.execute(
        "SELECT id, seq FROM shaft WHERE batch_id = ? AND seq > ? ORDER BY seq DESC",
        (batch_id, after_seq),
    ).fetchall()
    for row in shifting:
        new_seq = row["seq"] + 1
        new_label = shaft_label(batch["batch_no"], new_seq, batch["seq_width"])
        conn.execute(
            "UPDATE shaft SET seq = ?, label = ? WHERE id = ?", (new_seq, new_label, row["id"])
        )

    inserted_seq = after_seq + 1
    inserted_label = shaft_label(batch["batch_no"], inserted_seq, batch["seq_width"])
    conn.execute(
        "INSERT INTO shaft(batch_id, seq, label, diameter_id, wood_id) VALUES (?, ?, ?, ?, ?)",
        (batch_id, inserted_seq, inserted_label, batch["diameter_id"], batch["wood_id"]),
    )
    conn.execute("UPDATE batch SET expected_count = ? WHERE id = ?", (new_total, batch_id))
    conn.commit()
    return inserted_seq


def delete_shaft(conn: sqlite3.Connection, batch_id: int, seq: int) -> None:
    """Deletes one shaft and closes the numbering gap: every later shaft
    shifts down by one -- processed lowest-seq-first, so the slot each row
    moves into is always already empty. Readings cascade-delete with their
    shaft (ON DELETE CASCADE); a shaft already consumed into a set is
    refused, since that record needs to stay put for the set's history.
    """
    batch = get_batch(conn, batch_id)
    if batch is None:
        raise ValueError(f"no such batch {batch_id}")
    shaft = conn.execute(
        "SELECT id, consumed_set_id FROM shaft WHERE batch_id = ? AND seq = ?",
        (batch_id, seq),
    ).fetchone()
    if shaft is None:
        raise ValueError(f"no such shaft {batch_id}-{seq}")
    if shaft["consumed_set_id"] is not None:
        raise ValueError("cannot delete a shaft that has already been used in a set")

    conn.execute("DELETE FROM shaft WHERE id = ?", (shaft["id"],))

    shifting = conn.execute(
        "SELECT id, seq FROM shaft WHERE batch_id = ? AND seq > ? ORDER BY seq ASC",
        (batch_id, seq),
    ).fetchall()
    for row in shifting:
        new_seq = row["seq"] - 1
        new_label = shaft_label(batch["batch_no"], new_seq, batch["seq_width"])
        conn.execute(
            "UPDATE shaft SET seq = ?, label = ? WHERE id = ?", (new_seq, new_label, row["id"])
        )

    conn.execute(
        "UPDATE batch SET expected_count = ? WHERE id = ?",
        (batch["expected_count"] - 1, batch_id),
    )
    conn.commit()
