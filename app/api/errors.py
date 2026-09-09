"""Structured error envelope and exception handlers.

core/ raises plain, DB-agnostic exceptions (UnitError, ValidationBlocked);
this is the one place that maps them to HTTP status codes and a consistent
{"error": {...}} body.
"""

from __future__ import annotations

import re
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db.repo_lookups import UnknownLookupKind
from core.units import UnitError
from core.validate import ValidationBlocked

_HTTP_STATUS_CODES = {400: "BAD_REQUEST", 404: "NOT_FOUND", 409: "CONFLICT"}
_UNIQUE_CONSTRAINT_RE = re.compile(r"UNIQUE constraint failed: \w+\.(\w+)")


def _envelope(code: str, message: str, **extra) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


def register_error_handlers(app: FastAPI) -> None:
    # Registered on the Starlette base class, per FastAPI's documented way
    # to override the default {"detail": ...} body -- this also catches
    # fastapi.HTTPException, which subclasses it.
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        code = _HTTP_STATUS_CODES.get(exc.status_code, "ERROR")
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))

    @app.exception_handler(UnitError)
    async def _unit_error(request: Request, exc: UnitError):
        return JSONResponse(status_code=422, content=_envelope(exc.code, str(exc)))

    @app.exception_handler(ValidationBlocked)
    async def _validation_blocked(request: Request, exc: ValidationBlocked):
        issues = [{"code": i.code, "message": i.message} for i in exc.issues]
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_BLOCKED", "value rejected", issues=issues),
        )

    @app.exception_handler(KeyError)
    async def _key_error(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content=_envelope("NOT_FOUND", str(exc)))

    @app.exception_handler(UnknownLookupKind)
    async def _unknown_lookup_kind(request: Request, exc: UnknownLookupKind):
        return JSONResponse(
            status_code=404, content=_envelope("NOT_FOUND", f"unknown lookup kind {exc}")
        )

    # A UNIQUE constraint (batch_no, a shaft label, a lookup label, a set
    # name, ...) is a real, expected user mistake -- e.g. reusing a batch
    # number -- not a server fault. Without this handler it falls through
    # to Starlette's default 500, which is both the wrong status code and
    # unreadable to the entry form that triggered it.
    @app.exception_handler(sqlite3.IntegrityError)
    async def _integrity_error(request: Request, exc: sqlite3.IntegrityError):
        match = _UNIQUE_CONSTRAINT_RE.search(str(exc))
        if match:
            message = f"a record with this {match.group(1)} already exists"
        else:
            message = "that change conflicts with existing data"
        return JSONResponse(status_code=409, content=_envelope("ALREADY_EXISTS", message))
