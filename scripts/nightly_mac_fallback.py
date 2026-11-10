"""PC-side fallback trigger for the nightly Mac run.

GitHub's ``schedule`` trigger for ``nightly-mac.yml`` has not created a run on
any night, so a scheduled PC job runs this once a night. It dispatches
``nightly-mac.yml`` on ``main`` through ``gh`` -- unless a run of that workflow
was already created for today's UTC date, so a schedule that starts working
never doubles up (``docs/mac-runner.md``, "Fallback trigger").

Each path ends in one log line and its own exit code:

* ``0`` -- dispatched and the run showed up, or skipped because today already
  has a run (the two are told apart by the log line, not the exit code);
* ``1`` -- ``gh`` failed (not installed, not logged in, no network, a refused
  dispatch);
* ``3`` -- the dispatch was accepted but no run appeared within the wait, so
  the night is *not confirmed*, never reported as dispatched.

Stdlib only; needs ``gh`` on PATH, logged in with write access to the repo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.no_window import NO_WINDOW  # noqa: E402 -- needs the sys.path line above

logger = logging.getLogger("nightly_mac_fallback")

DEFAULT_REPO = "ferraroroberto/project-scaffolding"
WORKFLOW = "nightly-mac.yml"
REF = "main"
# Enough to reach back past the day's runs: the workflow makes one per night
# plus the odd manual one.
LIST_LIMIT = 30
# One `gh` call; well past a slow API round trip, short of a wedge.
GH_TIMEOUT_S = 60
# How long a dispatch gets to show up as a run, and how often to look.
CONFIRM_ATTEMPTS = 6
CONFIRM_INTERVAL_S = 10

EXIT_OK = 0
EXIT_GH_FAILED = 1
EXIT_NOT_CONFIRMED = 3

GhRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class GhError(Exception):
    """``gh`` could not be run, timed out or exited non-zero."""


def run_gh(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` with *args*; raises GhError on a spawn failure or a timeout."""
    try:
        return subprocess.run(
            ["gh", *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=GH_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GhError(f"could not run gh: {exc}") from exc


def _checked(gh: GhRunner, args: Sequence[str]) -> str:
    """Stdout of ``gh *args*``; raises GhError carrying gh's own message on failure."""
    proc = gh(args)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "no output"
        raise GhError(f"gh {' '.join(args[:2])} exited {proc.returncode}: {detail}")
    return proc.stdout


def runs_created_on(gh: GhRunner, repo: str, day: dt.date) -> list[dict]:
    """Runs of the workflow (any event) whose ``createdAt`` falls on UTC date *day*."""
    out = _checked(gh, [
        "run", "list", "--repo", repo, "--workflow", WORKFLOW,
        "--limit", str(LIST_LIMIT), "--json", "databaseId,event,createdAt",
    ])
    try:
        rows = json.loads(out)
    except json.JSONDecodeError as exc:
        raise GhError(f"gh run list returned unreadable output: {exc}") from exc
    if not isinstance(rows, list):
        raise GhError("gh run list returned an unexpected shape")
    return [r for r in rows if isinstance(r, dict) and str(r.get("createdAt", "")).startswith(day.isoformat())]


def run(
    repo: str,
    gh: GhRunner = run_gh,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Dispatch the nightly run unless today (UTC) already has one; returns the exit code."""
    day = now().date()
    try:
        existing = runs_created_on(gh, repo, day)
        if existing:
            first = existing[0]
            logger.info(
                "ℹ️ skipped: %s already has a run for %s (id %s, event %s)",
                WORKFLOW, day, first.get("databaseId"), first.get("event"),
            )
            return EXIT_OK
        _checked(gh, ["workflow", "run", WORKFLOW, "--repo", repo, "--ref", REF])
        for attempt in range(CONFIRM_ATTEMPTS):
            sleep(CONFIRM_INTERVAL_S)
            created = runs_created_on(gh, repo, day)
            if created:
                logger.info(
                    "✅ dispatched: %s on %s, run id %s created for %s",
                    WORKFLOW, REF, created[0].get("databaseId"), day,
                )
                return EXIT_OK
            logger.info("ℹ️ waiting for the dispatched run to appear (%d/%d)", attempt + 1, CONFIRM_ATTEMPTS)
    except GhError as exc:
        logger.error("❌ gh failed, nothing confirmed dispatched: %s", exc)
        return EXIT_GH_FAILED
    logger.warning(
        "⚠️ not confirmed: dispatch of %s was accepted but no run for %s appeared within %ds",
        WORKFLOW, day, CONFIRM_ATTEMPTS * CONFIRM_INTERVAL_S,
    )
    return EXIT_NOT_CONFIRMED


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name of the repo (default: %(default)s)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    return run(args.repo)


if __name__ == "__main__":
    sys.exit(main())
