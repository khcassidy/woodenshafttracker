"""Per-request SQLite connection. One connection per request (not shared
across requests), matching the plan's WAL / busy_timeout / single-worker
concurrency model."""

from __future__ import annotations

import sqlite3
from typing import Iterator

from app import settings
from app.db.connection import connect
from app.db.migrate import migrate


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect(settings.DB_PATH)
    migrate(conn)
    try:
        yield conn
    finally:
        conn.close()
