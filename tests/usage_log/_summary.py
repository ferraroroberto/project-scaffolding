"""Read a usage-log file the way the app does: read-only, through ``summarize``."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.usage_log import open_read_only, summarize


def summary_of(db: Path, days: int, *, now: datetime | None = None) -> dict[str, Any]:
    """Aggregate ``db`` over ``days`` days via the router's and the CLI's read path."""
    conn = open_read_only(db)
    try:
        return summarize(conn, days, now=now)
    finally:
        conn.close()
