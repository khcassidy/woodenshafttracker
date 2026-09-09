"""Runtime configuration, overridable via environment variables."""

from __future__ import annotations

import os
from pathlib import Path

DB_PATH = Path(os.environ.get("SHAFTTRACKER_DB", "shafttracker.db"))
HOST = os.environ.get("SHAFTTRACKER_HOST", "0.0.0.0")
PORT = int(os.environ.get("SHAFTTRACKER_PORT", "8765"))
