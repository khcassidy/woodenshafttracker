"""core/ must import the standard library only: no DB, no HTTP, no web
framework. This is enforced mechanically, not by convention, so that
core/grouping.py (slice 2) lands on the same guarantee."""

import ast
from pathlib import Path

FORBIDDEN = {
    "sqlite3",
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "http",
    "socket",
    "requests",
    "urllib",
}

CORE_DIR = Path(__file__).resolve().parent.parent / "core"


def _imported_top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def test_core_modules_import_no_forbidden_packages():
    offenders = {}
    for path in CORE_DIR.glob("*.py"):
        found = _imported_top_level_names(path) & FORBIDDEN
        if found:
            offenders[path.name] = found
    assert not offenders, f"core/ modules must stay pure: {offenders}"
