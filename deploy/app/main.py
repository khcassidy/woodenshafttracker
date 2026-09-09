"""FastAPI app: router includes, static file mount, startup migration.

Every endpoint function is `def`, never `async def`: sqlite3 blocks, and a
`def` endpoint runs in Starlette's threadpool so it cannot stall the event
loop.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import settings
from app.api import analysis, batches, importexport, lookups, params, partitions, sets, shafts
from app.api.errors import register_error_handlers
from app.db.connection import connect
from app.db.migrate import migrate

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    conn = connect(settings.DB_PATH)
    migrate(conn)
    conn.close()
    yield


app = FastAPI(title="Wooden Shaft Tracker", lifespan=_lifespan)

register_error_handlers(app)


@app.middleware("http")
async def _no_cache_for_static(request, call_next):
    # ASGI middleware, not a route -- unlike the "every endpoint is def"
    # rule above, this touches no DB and just forces the browser to always
    # revalidate index.html/js/css with a conditional GET (still a cheap
    # 304 when unchanged) instead of skipping the request from its own
    # heuristic cache. Without this, an app.js edit can sit invisible in a
    # tab until a hard refresh, since the single-page router never
    # re-fetches app.js on its own -- only a real navigation does.
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith(("/js/", "/css/")):
        response.headers["Cache-Control"] = "no-cache"
    return response

app.include_router(batches.router)
app.include_router(shafts.router)
app.include_router(lookups.router)
app.include_router(params.router)
app.include_router(partitions.router)
app.include_router(sets.router)
app.include_router(analysis.router)
app.include_router(importexport.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
