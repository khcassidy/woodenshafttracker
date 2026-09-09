#!/usr/bin/env python
"""One-command backup: copies the live database to backups\\shafttracker-<UTC
timestamp>.db.

Uses sqlite3's own Connection.backup() API, not a raw file copy. A plain
copy can grab a torn, inconsistent snapshot of a WAL-mode database while
the server is writing to it; the backup API is safe against a live
connection and produces a complete, consistent file every time -- run
this with the server running, no need to stop it first.

Usage:
    python scripts\\backup.py
    python scripts\\backup.py --db shafttracker.db --out backups
"""

from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import settings  # noqa: E402


def backup(source_path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_path = dest_dir / f"shafttracker-{timestamp}.db"

    source_conn = sqlite3.connect(source_path)
    dest_conn = sqlite3.connect(dest_path)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()
    return dest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.DB_PATH)
    parser.add_argument("--out", type=Path, default=Path("backups"))
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"No database at {args.db} -- nothing to back up.", file=sys.stderr)
        return 1

    dest = backup(args.db, args.out)
    size_kb = dest.stat().st_size / 1024
    print(f"Backed up {args.db} -> {dest} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
