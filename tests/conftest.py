import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db.migrate import migrate


@pytest.fixture
def db():
    # check_same_thread=False: the `client` fixture below reuses this same
    # connection through TestClient requests, which FastAPI may serve from
    # a different threadpool worker thread than this fixture ran on.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    """A TestClient wired to the shared in-memory `db` fixture, so API
    tests exercise the same migrated schema as the DB-level tests, with
    no file I/O."""
    from app.deps import get_db
    from app.main import app

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    # Deliberately not `with TestClient(app) as ...`: that would run the
    # app's lifespan startup, which migrates the real on-disk database file
    # as a side effect. Routes need no lifespan state here -- get_db is
    # fully overridden above -- so plain instantiation keeps tests off disk.
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()
