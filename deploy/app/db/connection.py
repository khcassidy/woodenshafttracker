"""SQLite connection factory: PRAGMAs, row factory, and a transaction helper.

One connection per request (FastAPI dependency, see app/deps.py). WAL plus a
5 s busy timeout is sufficient for one archer on a home network; a single
uvicorn worker is used, so there is no cross-process write contention to
guard against.

check_same_thread=False: FastAPI resolves a sync dependency and runs a sync
`def` endpoint via anyio's threadpool, which may hop between worker threads
within a single request (dependency resolution and the endpoint body are
not guaranteed to land on the same thread). The connection here is still
only ever used sequentially within one request, never concurrently from
two threads at once, so this is safe.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    """Commit the block on success, roll back on any exception."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
