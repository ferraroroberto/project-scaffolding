"""Summarize one fleet app's local usage log for a design review (#349).

Reads ``<runtime-data root>/<app>/usage.sqlite3`` (the file the vendored
``src/usage_log.py`` router writes) read-only and prints per-view visit
counts, per-control tap counts, the device/OS split by session, the session
count and the first/last timestamps over the last ``--days`` days.

    python scripts/usage_summary.py --app app-launcher --days 30 --json

``/design-review``'s full-app inventory fills its frequency column from this
output. A missing database exits 2 with a message on stderr — "no data yet"
(the app has not adopted the log, or nobody has opened it since) must never
read as "zero usage", which is an existing database with no rows in range.

Run from anywhere: the repo root is put on ``sys.path`` before the ``src``
imports, since a script's own directory is ``sys.path[0]``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.runtime_data import runtime_db_path  # noqa: E402
from src.usage_log import open_read_only, summarize  # noqa: E402

EXIT_NO_DATA = 2
EXIT_UNREADABLE = 3


def _render_text(app: str, db_path: Path, summary: dict[str, object]) -> str:
    lines = [
        f"usage log: {app} ({db_path})",
        f"last {summary['days']} days since {summary['since']}: "
        f"{summary['sessions']} sessions, {summary['events']} events, "
        f"first {summary['first_ts'] or '-'}, last {summary['last_ts'] or '-'}",
    ]
    for title, key in (("views", "views"), ("controls (taps)", "controls"),
                       ("devices (sessions)", "devices"), ("os (sessions)", "os")):
        counts = summary[key]
        assert isinstance(counts, dict)
        lines.append(f"{title}:")
        if not counts:
            lines.append("  (none)")
        for name, n in counts.items():
            lines.append(f"  {n:>6}  {name}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Summarize a fleet app's local usage log.")
    ap.add_argument("--app", required=True, help="app slug, e.g. app-launcher (its runtime-data directory name)")
    ap.add_argument("--days", type=int, default=30, help="window in days (default 30)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--db", type=Path, help="explicit usage.sqlite3 path (overrides --app resolution)")
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days must be at least 1")

    db_path: Path = args.db or runtime_db_path(args.app, "usage.sqlite3")
    try:
        conn = open_read_only(db_path)
    except FileNotFoundError:
        print(
            f"no usage data yet for {args.app}: {db_path} does not exist "
            "(the app has not adopted the usage log, or has recorded nothing). "
            "This is not zero usage.",
            file=sys.stderr,
        )
        return EXIT_NO_DATA
    try:
        summary = summarize(conn, args.days)
    except sqlite3.Error as exc:
        print(f"cannot read usage log {db_path}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    finally:
        conn.close()

    if args.json:
        print(json.dumps({"app": args.app, **summary}, indent=2))
    else:
        print(_render_text(args.app, db_path, summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
