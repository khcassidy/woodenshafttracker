#!/usr/bin/env python
"""One-off importer for a workbook-shaped CSV export: one file per batch,
title row 'BATCH <n> <label>', header row 'Shaft#,Spine A (lb),Spine B
(lb),Weight (g)', then one data row per shaft. Dry run by default; pass
--commit to write.

This is the same shape scripts/import_workbook.py reads from one xlsx
sheet -- this script only swaps the xlsx cell reader for a CSV reader and
reuses that module's build_report()/commit_batch() (already exercised by
tests/test_import_workbook.py) unchanged, so a CSV import and an xlsx
import of the same data land identically.

Usage:
    python scripts\\import_csv_batch.py planning\\batch19.csv planning\\batch20.csv
    python scripts\\import_csv_batch.py planning\\batch19.csv planning\\batch20.csv `
        --commit --diameter '11/32"' --wood 'Northern Pine'
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.connection import connect  # noqa: E402
from app.db.migrate import migrate  # noqa: E402
from core.labels import parse_label  # noqa: E402
from scripts.import_workbook import (  # noqa: E402
    BATCH_TITLE_RE,
    HEADER,
    WorkbookFormatError,
    build_report,
    commit_batch,
)

_HEADER_ORDER = ["A", "B", "C", "D"]


def _cell(row: list[str], index: int) -> str | None:
    if index >= len(row):
        return None
    value = row[index].strip()
    return value if value else None


def read_batch_csv(path: Path) -> tuple[int, str, list[dict]]:
    """Returns (batch_no, nominal_spine_label, shaft_rows), the same shape
    scripts/import_workbook.py's read_batch_sheet() returns from an xlsx
    sheet."""
    text = path.read_text(encoding="utf-8-sig")  # tolerates a BOM
    rows = list(csv.reader(text.splitlines()))
    if len(rows) < 2:
        raise WorkbookFormatError(f"{path}: expected a title row and a header row")

    title = rows[0][0] if rows[0] else ""
    match = BATCH_TITLE_RE.match(title.strip())
    if not match:
        raise WorkbookFormatError(f"{path}: cannot parse batch title {title!r}")
    batch_no = int(match.group(1))
    nominal_label = match.group(2).strip()

    header_row = rows[1]
    for i, col in enumerate(_HEADER_ORDER):
        expected = HEADER[col]
        actual = header_row[i].strip() if i < len(header_row) else None
        if actual != expected:
            raise WorkbookFormatError(
                f"{path}: unexpected header column {i}={actual!r}, expected {expected!r}"
            )

    shaft_rows = []
    for row_num, row in enumerate(rows[2:], start=3):
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        label_batch_no, seq = parse_label(label)
        if label_batch_no != batch_no:
            raise WorkbookFormatError(
                f"{path} row {row_num}: label {label!r} does not belong to batch {batch_no}"
            )
        shaft_rows.append(
            {
                "row": row_num,
                "seq": seq,
                "label": label,
                "spine_a_raw": _cell(row, 1),
                "spine_b_raw": _cell(row, 2),
                "weight_raw": _cell(row, 3),
            }
        )
    return batch_no, nominal_label, shaft_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_files", type=Path, nargs="+")
    parser.add_argument(
        "--commit", action="store_true", help="write to the database (default: dry run)"
    )
    parser.add_argument("--db", type=Path, default=Path("shafttracker.db"))
    parser.add_argument("--diameter", default=None, help="diameter_option label, e.g. '11/32\"'")
    parser.add_argument("--wood", default=None, help="wood_option label, e.g. 'Northern Pine'")
    args = parser.parse_args(argv)

    reports = []
    had_errors = False
    for csv_path in args.csv_files:
        batch_no, nominal_label, shaft_rows = read_batch_csv(csv_path)
        report = build_report(batch_no, nominal_label, shaft_rows)
        reports.append(report)
        print(f"{csv_path}: batch {batch_no} ({nominal_label}), {report['count']} shafts")
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
