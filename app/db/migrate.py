"""Applies app/db/migrations/*.sql in order, tracked by PRAGMA user_version.
There is no separate schema.sql to drift out of sync with the migrations."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")


def _migrations() -> list[tuple[int, Path]]:
    found = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = _MIGRATION_RE.match(path.name)
        if not match:
            continue
        found.append((int(match.group(1)), path))
    return sorted(found, key=lambda item: item[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every migration newer than the connection's user_version.
    Returns the resulting user_version. Safe to call on every startup."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    applied = current
    for version, path in _migrations():
        if version <= current:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {version}")
        applied = version
    conn.commit()
    return applied
