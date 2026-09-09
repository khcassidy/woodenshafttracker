#!/usr/bin/env python
"""One-off importer for the legacy workbook (planning/Arrow Batch 19 20
20260901.xlsx). Dry run by default; pass --commit to write.

Reads every cell as text via app/io/xlsx_read.py, so no spine or weight
value in the workbook ever passes through a Python float.

Usage:
    python scripts\\import_workbook.py "planning\\Arrow Batch 19 20 20260901.xlsx"
    python scripts\\import_workbook.py "planning\\Arrow Batch 19 20 20260901.xlsx" \\
        --commit --diameter '11/32"' --wood 'Northern Pine'
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.connection import connect  # noqa: E402
from app.db.migrate import migrate  # noqa: E402
from app.io.xlsx_read import Workbook, open_workbook  # noqa: E402
from core.derive import SpineDerivation, derive_spine  # noqa: E402
from core.labels import parse_label, required_seq_width, shaft_label  # noqa: E402
from core.units import UnitError, parse_spine_lb, parse_weight_g  # noqa: E402

BATCH_TITLE_RE = re.compile(r"^BATCH\s+(\d+)\s+(.+)$")
NOMINAL_RANGE_RE = re.compile(r"^(\d+)-(\d+)#?$")

HEADER = {"A": "Shaft#", "B": "Spine A (lb)", "C": "Spine B (lb)", "D": "Weight (g)"}


class WorkbookFormatError(Exception):
    pass


def _parse_nominal_range(label: str) -> tuple[int | None, int | None]:
    match = NOMINAL_RANGE_RE.match(label.strip())
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def read_batch_sheet(wb: Workbook, sheet_name: str) -> tuple[int, str, list[dict]]:
    """Returns (batch_no, nominal_spine_label, shaft_rows)."""
    rows = wb.read_rows(sheet_name)

    title = rows.get(1, {}).get("A", "")
    match = BATCH_TITLE_RE.match(title.strip())
    if not match:
        raise WorkbookFormatError(f"{sheet_name}: cannot parse batch title {title!r}")
    batch_no = int(match.group(1))
    nominal_label = match.group(2).strip()

    header = rows.get(2, {})
    for col, expected in HEADER.items():
        if header.get(col) != expected:
            raise WorkbookFormatError(
                f"{sheet_name}: unexpected header {col}={header.get(col)!r}, "
                f"expected {expected!r}"
            )

    shaft_rows = []
    for row_num in sorted(k for k in rows if k >= 3):
        cells = rows[row_num]
        if "A" not in cells:
            continue
        label = cells["A"].strip()
        label_batch_no, seq = parse_label(label)
        if label_batch_no != batch_no:
            raise WorkbookFormatError(
                f"{sheet_name} row {row_num}: label {label!r} does not belong to "
                f"batch {batch_no}"
            )
        shaft_rows.append(
            {
                "row": row_num,
                "seq": seq,
                "label": label,
                "spine_a_raw": cells.get("B"),
                "spine_b_raw": cells.get("C"),
                "weight_raw": cells.get("D"),
            }
        )
    return batch_no, nominal_label, shaft_rows


def build_report(
    batch_no: int,
    nominal_label: str,
    shaft_rows: list[dict],
    spec_min_mlb: int = 54000,
    spec_max_mlb: int = 60000,
) -> dict:
    """Pure computation over parsed rows: no DB, so a dry run and a commit
    see identical numbers."""
    parsed = []
    errors = []
    for row in shaft_rows:
        try:
            spine_a_cp = None
            spine_b_cp = None
            if row["spine_a_raw"] is None:
                raise UnitError("MISSING", f"row {row['row']} has no Spine A")
            spine_a_cp = parse_spine_lb(row["spine_a_raw"])
            readings = [spine_a_cp]
            if row["spine_b_raw"] is not None:
                spine_b_cp = parse_spine_lb(row["spine_b_raw"])
                readings.append(spine_b_cp)
            derived = derive_spine(readings)
            weight_cg = None
            if row["weight_raw"] is not None:
                weight_cg = parse_weight_g(row["weight_raw"])
            parsed.append(
                {
                    **row,
                    "spine_a_cp": spine_a_cp,
                    "spine_b_cp": spine_b_cp,
                    "weight_cg": weight_cg,
                    "derived": derived,
                }
            )
        except UnitError as exc:
            errors.append(f"row {row['row']} ({row['label']}): {exc.code} {exc}")

    in_spec = sum(
        1 for p in parsed if spec_min_mlb <= p["derived"].avg_spine_mlb <= spec_max_mlb
    )
    below = sum(1 for p in parsed if p["derived"].avg_spine_mlb < spec_min_mlb)
    above = sum(1 for p in parsed if p["derived"].avg_spine_mlb > spec_max_mlb)
    weights = [p["weight_cg"] for p in parsed if p["weight_cg"] is not None]

    return {
        "batch_no": batch_no,
        "nominal_label": nominal_label,
        "count": len(parsed),
        "in_spec": in_spec,
        "below_floor": below,
        "above_ceiling": above,
        "weight_min_cg": min(weights) if weights else None,
        "weight_max_cg": max(weights) if weights else None,
        "weight_sum_cg": sum(weights) if weights else None,
        "avg_spine_sum_mlb": sum(p["derived"].avg_spine_mlb for p in parsed),
        "parsed": parsed,
        "errors": errors,
    }


def _lookup_option_id(conn: sqlite3.Connection, table: str, label: str | None) -> int:
    if not label:
        return 0
    row = conn.execute(f"SELECT id FROM {table} WHERE label = ?", (label,)).fetchone()
    if row is None:
        raise WorkbookFormatError(f"unknown {table} label {label!r}")
    return row["id"]


def commit_batch(
    conn: sqlite3.Connection,
    report: dict,
    diameter_label: str | None,
    wood_label: str | None,
) -> int:
    nominal_min, nominal_max = _parse_nominal_range(report["nominal_label"])
    seq_width = required_seq_width(report["count"])
    diameter_id = _lookup_option_id(conn, "diameter_option", diameter_label)
    wood_id = _lookup_option_id(conn, "wood_option", wood_label)

    cur = conn.execute(
        """INSERT INTO batch
           (batch_no, seq_width, nominal_spine_label, nominal_min_lb, nominal_max_lb,
            diameter_id, wood_id, expected_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report["batch_no"],
            seq_width,
            report["nominal_label"],
            nominal_min,
            nominal_max,
            diameter_id,
            wood_id,
            report["count"],
        ),
    )
    batch_id = cur.lastrowid

    for p in report["parsed"]:
        label = shaft_label(report["batch_no"], p["seq"], seq_width)
        derived: SpineDerivation = p["derived"]
        weight_cg = p["weight_cg"]
        weight_text = p["weight_raw"] if weight_cg is not None else None
        cur = conn.execute(
            """INSERT INTO shaft
               (batch_id, seq, label, diameter_id, wood_id,
                spine_count, spine_sum_cp, spine_min_cp, spine_max_cp,
                avg_spine_mlb, spine_spread_cp,
                weight_cg, weight_text, weight_unit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                batch_id,
                p["seq"],
                label,
                diameter_id,
                wood_id,
                derived.spine_count,
                derived.spine_sum_cp,
                derived.spine_min_cp,
                derived.spine_max_cp,
                derived.avg_spine_mlb,
                derived.spine_spread_cp,
                weight_cg,
                weight_text,
                "g" if weight_cg is not None else None,
            ),
        )
        shaft_id = cur.lastrowid
        conn.execute(
            "INSERT INTO shaft_spine_reading(shaft_id, ordinal, value_cp, entered_text) "
            "VALUES (?, 1, ?, ?)",
            (shaft_id, p["spine_a_cp"], p["spine_a_raw"]),
        )
        if p["spine_b_cp"] is not None:
            conn.execute(
                "INSERT INTO shaft_spine_reading(shaft_id, ordinal, value_cp, entered_text) "
                "VALUES (?, 2, ?, ?)",
                (shaft_id, p["spine_b_cp"], p["spine_b_raw"]),
            )
    return batch_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument(
        "--commit", action="store_true", help="write to the database (default: dry run)"
    )
    parser.add_argument("--db", type=Path, default=Path("shafttracker.db"))
    parser.add_argument("--diameter", default=None, help="diameter_option label, e.g. '11/32\"'")
    parser.add_argument("--wood", default=None, help="wood_option label, e.g. 'Northern Pine'")
    parser.add_argument(
        "--sheets", nargs="+", default=None, help="sheet names (default: autodetect BATCH*)"
    )
    args = parser.parse_args(argv)

    wb = open_workbook(args.workbook)
    sheet_names = args.sheets or [n for n in wb.sheet_names() if n.upper().startswith("BATCH")]
    if not sheet_names:
        print("No BATCH* sheets found.", file=sys.stderr)
        return 1

    reports = []
    had_errors = False
    for sheet_name in sheet_names:
        batch_no, nominal_label, shaft_rows = read_batch_sheet(wb, sheet_name)
        report = build_report(batch_no, nominal_label, shaft_rows)
        reports.append(report)
        print(f"{sheet_name}: batch {batch_no} ({nominal_label}), {report['count']} shafts")
        print(
            f"  in spec: {report['in_spec']}  below floor: {report['below_floor']}  "
            f"above ceiling: {report['above_ceiling']}"
        )
        if report["errors"]:
            had_errors = True
            for err in report["errors"]:
                print(f"  ERROR: {err}")

    combined_count = sum(r["count"] for r in reports)
    combined_in_spec = sum(r["in_spec"] for r in reports)
    print(f"Combined: {combined_count} shafts, {combined_in_spec} in spec")

    if had_errors:
        print("Import aborted: fix the errors above.", file=sys.stderr)
        return 1

    if not args.commit:
        print("Dry run only. Pass --commit to write to the database.")
        return 0

    conn = connect(args.db)
    migrate(conn)
    try:
        for report in reports:
            batch_id = commit_batch(conn, report, args.diameter, args.wood)
            print(f"Committed batch {report['batch_no']} as batch_id={batch_id}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
