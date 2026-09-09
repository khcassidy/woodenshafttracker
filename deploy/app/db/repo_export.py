"""Builds export row dicts, joining shaft_entry_v with the lookup labels
a human-readable file needs instead of raw ids."""

from __future__ import annotations

import sqlite3


def export_shaft_rows(conn: sqlite3.Connection, batch_id: int | None = None) -> list[dict]:
    where = "WHERE sev.batch_id = ?" if batch_id is not None else ""
    params = (batch_id,) if batch_id is not None else ()
    rows = conn.execute(
        f"""SELECT sev.batch_no, sev.seq, sev.label,
                   d.label AS diameter_label, w.label AS wood_label, sh.label AS shop_label,
                   b.purchase_date, b.nominal_spine_label,
                   sev.spine_a_text, sev.spine_b_text,
                   sev.weight_text, sev.weight_unit,
                   sev.straightness, sev.notes
            FROM shaft_entry_v sev
            JOIN batch b ON b.id = sev.batch_id
            JOIN diameter_option d ON d.id = sev.diameter_id
            JOIN wood_option w ON w.id = sev.wood_id
            LEFT JOIN shop sh ON sh.id = b.shop_id
            {where}
            ORDER BY sev.batch_no, sev.seq""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]
