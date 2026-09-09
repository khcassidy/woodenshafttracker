"""JSON: the full-fidelity backup format. Unlike CSV's derived grams/grains
pair, a shaft's weight here is its exact (weightText, weightUnit) --
whichever the archer actually typed -- so a round trip through export and
back never loses or re-derives anything.
"""

from __future__ import annotations

import sqlite3


def _label_for(options: list[sqlite3.Row], option_id: int | None) -> str | None:
    if option_id is None:
        return None
    for option in options:
        if option["id"] == option_id:
            return option["label"]
    return None


def export_json(conn: sqlite3.Connection) -> dict:
    diameters_all = conn.execute(
        "SELECT id, label, sixty_fourths, is_unknown FROM diameter_option ORDER BY sort_order"
    ).fetchall()
    woods_all = conn.execute(
        "SELECT id, label, is_unknown FROM wood_option ORDER BY sort_order"
    ).fetchall()
    shops_all = conn.execute("SELECT id, label, url, notes FROM shop ORDER BY sort_order").fetchall()

    batches = []
    for batch in conn.execute("SELECT * FROM batch ORDER BY batch_no").fetchall():
        shafts = []
        for shaft in conn.execute(
            "SELECT * FROM shaft_entry_v WHERE batch_id = ? ORDER BY seq", (batch["id"],)
        ).fetchall():
            shafts.append(
                {
                    "seq": shaft["seq"],
                    "spineA": shaft["spine_a_text"],
                    "spineB": shaft["spine_b_text"],
                    "weightText": shaft["weight_text"],
                    "weightUnit": shaft["weight_unit"],
                    "straightness": shaft["straightness"],
                    "notes": shaft["notes"],
                }
            )
        batches.append(
            {
                "batchNo": batch["batch_no"],
                "nominalSpineLabel": batch["nominal_spine_label"],
                "diameter": _label_for(diameters_all, batch["diameter_id"]),
                "wood": _label_for(woods_all, batch["wood_id"]),
                "shop": _label_for(shops_all, batch["shop_id"]),
                "purchaseDate": batch["purchase_date"],
                "description": batch["description"],
                "entryMode": batch["entry_mode"],
                "shafts": shafts,
            }
        )

    return {
        "diameters": [
            {"label": d["label"], "sixtyFourths": d["sixty_fourths"]}
            for d in diameters_all
            if not d["is_unknown"]
        ],
        "woods": [{"label": w["label"]} for w in woods_all if not w["is_unknown"]],
        "shops": [{"label": s["label"], "url": s["url"], "notes": s["notes"]} for s in shops_all],
        "batches": batches,
    }


def to_staged_rows(data: dict) -> list[dict]:
    """Flattens the export shape above into the canonical staged-row list
    app/db/repo_import.py works in -- one dict per shaft, batch-level
    fields copied onto every row, exactly like a CSV row would carry them."""
    rows = []
    for batch in data.get("batches", []):
        for shaft in batch.get("shafts", []):
            rows.append(
                {
                    "batchNo": batch.get("batchNo"),
                    "seq": shaft.get("seq"),
                    "diameter": batch.get("diameter"),
                    "wood": batch.get("wood"),
                    "shop": batch.get("shop"),
                    "purchaseDate": batch.get("purchaseDate"),
                    "nominalSpineLabel": batch.get("nominalSpineLabel"),
                    "description": batch.get("description"),
                    "entryMode": batch.get("entryMode"),
                    "spineA": shaft.get("spineA"),
                    "spineB": shaft.get("spineB"),
                    "weightText": shaft.get("weightText"),
                    "weightUnit": shaft.get("weightUnit"),
                    "straightness": shaft.get("straightness"),
                    "notes": shaft.get("notes"),
                }
            )
    return rows
