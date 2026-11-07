"""Matrix, selection, test legs and the READY marker for the nightly Mac run.

`.github/workflows/nightly-mac.yml` calls each subcommand on the self-hosted
Mac (docs/mac-runner.md):

* ``build`` reads the adopter list, makes an anonymous, read-only shallow fetch
  of each adopter's ``main``, validates its ``[ci.nightly]`` table and keeps
  only the repos whose ``main`` moved since their last green night (every repo
  on Sunday or with ``--full true``). It writes the matrix as JSON.
* ``leg`` runs one pytest leg (unit or e2e) and re-runs its failures once. A
  pass on the retry is ``flaky`` (the test ids go to the run folder), a second
  failure is ``fail``.
* ``ready`` computes the night's result from the legs, writes ``READY`` by
  write-then-rename and, on a green night, records the tested SHA as the last
  green one in ``state.json``.

Adopter code and adopter ``.fleet.toml`` files are untrusted data here: every
value that reaches a command is checked against a conservative character set,
and nothing is executed through a shell. Stdlib only, Python 3.11+ (tomllib).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.no_window import NO_WINDOW  # noqa: E402 -- needs the sys.path line above

# A shallow fetch of one public repo; well past a slow network, short of a wedge.
GIT_TIMEOUT_S = 180
# One pytest attempt; the job's own 90-minute cap is the outer bound.
LEG_TIMEOUT_S = 60 * 60
MAX_FLEET_TOML_BYTES = 512_000
MAX_REASON_CHARS = 200
SUNDAY = 6

_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
# A command-line token an adopter may hand to pytest or pip: no space, quote,
# `$`, backtick, `;`, `|`, `&`, `<`, `>` or glob character.
_TOKEN = re.compile(r"^[A-Za-z0-9_./:=,@+-]{1,200}$")
_PYTHON = re.compile(r"^3\.\d{1,2}$")
_MARKER = re.compile(r"^[A-Za-z0-9_ ()]{1,200}$")

KEYS = {"python", "requirements", "samples", "unit", "e2e", "views", "exclude_marker", "skip_reason"}
DEFAULT_EXCLUDE = "not windows_only"
LEG_RESULTS = ("pass", "flaky", "fail", "not-run", "unknown")


# ------------------------------------------------------------------ git
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run git anonymously (no credential helper, no prompt); None on spawn failure or timeout."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        return subprocess.run(
            ["git", "-c", "credential.helper=", "-C", str(cwd), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=GIT_TIMEOUT_S, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def fetch_main(url: str, work: Path) -> tuple[str | None, str | None, str]:
    """(sha, .fleet.toml text, error) of *url*'s ``main``, read from one shallow fetch.

    Reading both from the same fetch means the settings always belong to the
    commit that gets tested. A missing ``.fleet.toml`` gives text None, no error.
    """
    # runtime-write-exempt: a temporary directory the caller created, removed after the build
    work.mkdir(parents=True, exist_ok=True)
    for args in (("init", "-q"), ("fetch", "-q", "--depth", "1", "--no-tags", url, "refs/heads/main")):
        out = _git(work, *args)
        if out is None or out.returncode != 0:
            return None, None, f"git {args[0]} failed"
    rev = _git(work, "rev-parse", "FETCH_HEAD")
    sha = rev.stdout.strip() if rev is not None and rev.returncode == 0 else ""
    if not _SHA.match(sha):
        return None, None, "git rev-parse gave no commit"
    shown = _git(work, "show", "FETCH_HEAD:.fleet.toml")
    if shown is None:
        return sha, None, "git show failed"
    return sha, (shown.stdout if shown.returncode == 0 else None), ""


# ------------------------------------------------------------------ table
def _tokens(value: Any, key: str, *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise ValueError(f"`{key}` is required")
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"`{key}` must be a list of strings")
    if required and not value:
        raise ValueError(f"`{key}` must not be empty")
    for v in value:
        if not _TOKEN.match(v):
            raise ValueError(f"`{key}` holds a value outside the allowed characters")
    return list(value)


def clean_reason(text: str) -> str:
    """Printable, summary-safe text: no control characters, backticks or table pipes."""
    return re.sub(r"[^\x20-\x7e]|[`|]", "", text).strip()[:MAX_REASON_CHARS]


def parse_table(text: str | None) -> dict[str, Any]:
    """The validated ``[ci.nightly]`` table of a ``.fleet.toml``; raises ValueError when unusable.

    An opt-out returns ``{"skip_reason": ...}`` only.
    """
    if text is None:
        raise ValueError("no .fleet.toml on main")
    if len(text.encode("utf-8")) > MAX_FLEET_TOML_BYTES:
        raise ValueError(".fleet.toml is over the size cap")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError(".fleet.toml does not parse") from None
    table = data.get("ci", {}).get("nightly") if isinstance(data.get("ci"), dict) else None
    if not isinstance(table, dict):
        raise ValueError("no [ci.nightly] table")
    unknown = sorted(set(table) - KEYS)
    if unknown:
        raise ValueError(f"unknown [ci.nightly] keys: {', '.join(clean_reason(k) for k in unknown)}")
    if "skip_reason" in table:
        reason = table["skip_reason"]
        if not isinstance(reason, str) or not clean_reason(reason):
            raise ValueError("`skip_reason` must be a non-empty string")
        return {"skip_reason": clean_reason(reason)}
    python = table.get("python")
    if not isinstance(python, str) or not _PYTHON.match(python):
        raise ValueError("`python` must be a version string like \"3.14\"")
    samples = table.get("samples", "")
    if not isinstance(samples, str) or (samples and not _TOKEN.match(samples)):
        raise ValueError("`samples` must be a folder path")
    marker = table.get("exclude_marker", DEFAULT_EXCLUDE)
    if not isinstance(marker, str) or not _MARKER.match(marker):
        raise ValueError("`exclude_marker` must be a pytest marker expression")
    entry = {
        "python": python,
        "requirements": _tokens(table.get("requirements"), "requirements", required=True),
        "samples": samples,
        "unit": _tokens(table.get("unit"), "unit"),
        "e2e": _tokens(table.get("e2e"), "e2e"),
        "views": _tokens(table.get("views"), "views"),
        "exclude_marker": marker,
    }
    if not entry["unit"] and not entry["e2e"]:
        raise ValueError("declare at least one of `unit` or `e2e`")
    if entry["views"] and not entry["e2e"]:
        raise ValueError("`views` needs `e2e` (the smoke reuses its WebKit install)")
    return entry


# ------------------------------------------------------------------ selection
def read_adopters(path: Path) -> list[str]:
    """Repo names from the adopter list: one per line, `#` comments and blanks ignored."""
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        if not _REPO_NAME.match(name):
            raise ValueError(f"not a repo name: {clean_reason(name)!r}")
        if name not in names:
            names.append(name)
    return names


def last_green(state: Path) -> str | None:
    """The last green SHA in *state*, or None when there is none or the file is unusable."""
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    sha = data.get("last_green_sha") if isinstance(data, dict) else None
    return sha if isinstance(sha, str) and _SHA.match(sha) else None


def is_full_night(full: bool, today: dt.date) -> bool:
    return full or today.weekday() == SUNDAY


def _matrix_entry(repo: str, sha: str, entry: dict[str, Any], status: str, reason: str) -> dict[str, str]:
    """One flat matrix row: lists joined by spaces (their tokens hold none)."""
    return {
        "repo": repo,
        "sha": sha,
        "status": status,
        "reason": reason,
        "python": entry.get("python", ""),
        "requirements": " ".join(entry.get("requirements", [])),
        "samples": entry.get("samples", ""),
        "unit": " ".join(entry.get("unit", [])),
        "e2e": " ".join(entry.get("e2e", [])),
        "views": " ".join(entry.get("views", [])),
        "exclude_marker": entry.get("exclude_marker", DEFAULT_EXCLUDE),
    }


Fetcher = Callable[[str, Path], tuple[str | None, str | None, str]]


def build(
    adopters: list[str], url_base: str, state_root: Path, work: Path, full: bool, fetch: Fetcher | None = None,
) -> tuple[list[dict[str, str]], list[tuple[str, str, str]]]:
    """(matrix rows, decisions) for one night. A decision is (repo, run|skip|unknown, reason).

    A repo whose ``main`` or table cannot be read is kept as an ``unknown`` row,
    so its run writes a READY that says so instead of silently disappearing.
    """
    rows: list[dict[str, str]] = []
    decisions: list[tuple[str, str, str]] = []
    for repo in adopters:
        sha, text, error = (fetch or fetch_main)(f"{url_base}{repo}.git", work / repo)
        if sha is None:
            reason = f"could not read main: {error}"
            rows.append(_matrix_entry(repo, "", {}, "unknown", reason))
            decisions.append((repo, "unknown", reason))
            continue
        try:
            entry = parse_table(text)
        except ValueError as exc:
            reason = clean_reason(str(exc))
            rows.append(_matrix_entry(repo, sha, {}, "unknown", reason))
            decisions.append((repo, "unknown", reason))
            continue
        if "skip_reason" in entry:
            decisions.append((repo, "skip", f"opted out: {entry['skip_reason']}"))
            continue
        if full:
            reason = "full night"
        elif last_green(state_root / repo / "state.json") == sha:
            decisions.append((repo, "skip", "main unchanged since the last green night"))
            continue
        else:
            reason = "main changed since the last green night"
        rows.append(_matrix_entry(repo, sha, entry, "run", reason))
        decisions.append((repo, "run", reason))
    return rows, decisions


def cmd_build(args: argparse.Namespace) -> int:
    try:
        adopters = read_adopters(Path(args.adopters))
    except (OSError, ValueError) as exc:
        print(f"SELECT=unknown reason=adopter list unusable: {clean_reason(str(exc))}")
        return 3
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.UTC).date()
    full = is_full_night(args.full == "true", today)
    with tempfile.TemporaryDirectory(prefix="nightly-select-") as tmp:
        rows, decisions = build(adopters, args.url_base, Path(args.state_root).expanduser(), Path(tmp), full)
    matrix = json.dumps({"include": rows}, separators=(",", ":"))
    if args.github_output:
        # runtime-write-exempt: --github-output is the Actions output file, outside every checkout
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"matrix={matrix}\ncount={len(rows)}\n")
    counts = {k: sum(1 for d in decisions if d[1] == k) for k in ("run", "skip", "unknown")}
    if args.summary_file:
        # runtime-write-exempt: --summary-file is the Actions step summary, outside every checkout
        with open(args.summary_file, "a", encoding="utf-8") as fh:
            fh.write(f"### Nightly selection ({'full' if full else 'changed repos only'})\n")
            fh.write("| Repo | Decision | Reason |\n|---|---|---|\n")
            for repo, decision, reason in decisions:
                fh.write(f"| {repo} | {decision} | {reason} |\n")
            if not rows:
                fh.write("\nNothing changed since the last green night: no repo runs tonight.\n")
            fh.write("\n")
    full_word = "true" if full else "false"
    print(f"SELECT=ok run={counts['run']} skip={counts['skip']} unknown={counts['unknown']} full={full_word}")
    return 0


# ------------------------------------------------------------------ legs
def failed_ids(junit: Path) -> set[str] | None:
    """Ids (classname::name) of failed or errored testcases; None when the file is missing or unreadable."""
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError):
        return None
    ids: set[str] = set()
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            ids.add(f"{case.get('classname', '')}::{case.get('name', '')}")
    return ids


def _pytest(python: str, cwd: Path, args: list[str]) -> int | None:
    """Exit code of one pytest run (output streams to the log); None on timeout or spawn failure."""
    try:
        return subprocess.run(
            [python, "-m", "pytest", *args], cwd=cwd, stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW, timeout=LEG_TIMEOUT_S, check=False,
        ).returncode
    except (OSError, subprocess.TimeoutExpired):
        return None


def run_leg(
    python: str, cwd: Path, args: list[str], retry_args: list[str], junit: Path, retry_junit: Path, flaky_out: Path,
    runner: Callable[[str, Path, list[str]], int | None] = _pytest,
) -> tuple[str, int, str]:
    """(result, flaky count, reason) of one leg: run, and on failure re-run the failures once.

    Exit 5 (nothing collected) is unknown, not a pass. A failure on the retry is
    fail. A pass on the retry is flaky, and the ids that failed first and passed
    second are written to *flaky_out*.
    """
    first = runner(python, cwd, [*args, "--junitxml", str(junit)])
    if first == 0:
        return "pass", 0, ""
    if first == 5:
        return "unknown", 0, "no tests collected"
    if first is None:
        # A second hour-long attempt would run past the job's cap; a hang is red.
        return "fail", 0, "timed out"
    second = runner(python, cwd, [*args, *retry_args, "--last-failed", "--junitxml", str(retry_junit)])
    if second != 0:
        return "fail", 0, "timed out on retry" if second is None else "failed twice"
    first_ids = failed_ids(junit) or set()
    flaky = sorted(first_ids - (failed_ids(retry_junit) or set()))
    # runtime-write-exempt: --flaky-out is in the caller's run folder on the runner host, outside every checkout
    flaky_out.parent.mkdir(parents=True, exist_ok=True)
    # runtime-write-exempt: same caller-chosen run folder
    flaky_out.write_text("".join(f"{i}\n" for i in flaky), encoding="utf-8")
    return "flaky", len(flaky), "passed on retry"


def cmd_leg(args: argparse.Namespace) -> int:
    tokens = args.args.split()
    retry_tokens = args.retry_args.split()
    usable = bool(tokens) and all(_TOKEN.match(t) for t in tokens + retry_tokens)
    if not usable or (args.marker and not _MARKER.match(args.marker)):
        print(f"LEG={args.name} result=unknown flaky=0 reason=arguments outside the allowed characters")
        return 3
    if args.marker:
        tokens += ["-m", args.marker]
    result, count, reason = run_leg(
        args.python, Path(args.cwd), tokens, retry_tokens, Path(args.junit), Path(args.retry_junit), Path(args.flaky_out),
    )
    print(f"LEG={args.name} result={result} flaky={count}" + (f" reason={reason}" if reason else ""))
    return {"pass": 0, "flaky": 0, "fail": 1}.get(result, 3)


# ------------------------------------------------------------------ READY
_STEP_TO_LEG = {"success": "pass", "failure": "fail", "skipped": "not-run", "": "not-run", "cancelled": "unknown"}


def leg_from(leg_output: str, step_outcome: str) -> str:
    """A leg's result: its own `result=` output when it printed one, else from the step outcome."""
    if leg_output in LEG_RESULTS:
        return leg_output
    return _STEP_TO_LEG.get(step_outcome, "unknown")


def night_result(status: str, legs: dict[str, str], declared: set[str]) -> str:
    """green, red or unknown for one repo's night.

    Any failed leg, or a declared leg that never ran (its install or setup
    failed), is red. Otherwise any unknown leg makes the night unknown. A flaky
    leg is green: the flake is recorded, not hidden.
    """
    if status != "run":
        return "unknown"
    for name, value in legs.items():
        if value == "fail" or (name in declared and value == "not-run"):
            return "red"
    if any(legs[name] == "unknown" for name in declared):
        return "unknown"
    return "green"


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _atomic_write(path: Path, text: str) -> None:
    # runtime-write-exempt: --results/--state are the caller's run folder and state file in the runner user's home, outside every checkout
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # runtime-write-exempt: same caller-chosen file, written beside itself and renamed over it
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_ready(results: Path, fields: dict[str, str]) -> None:
    _atomic_write(results / "READY", "".join(f"{k}={v}\n" for k, v in fields.items()))


def record_green(state: Path, sha: str, run: str) -> None:
    payload = {"last_green_sha": sha, "last_green_run": run, "updated": dt.datetime.now(dt.UTC).isoformat()}
    _atomic_write(state, json.dumps(payload, indent=2) + "\n")


def cmd_ready(args: argparse.Namespace) -> int:
    results = Path(args.results)
    legs = {
        "unit": leg_from(args.unit, args.unit_step),
        "e2e": leg_from(args.e2e, args.e2e_step),
        "smoke": leg_from(args.smoke, args.smoke_step),
    }
    declared = {name for name in args.declared.split(",") if name}
    result = night_result(args.status, legs, declared)
    flaky = _count_lines(results / "unit-flaky.txt") + _count_lines(results / "e2e-flaky.txt")
    sha = args.sha if _SHA.match(args.sha) else "unknown"
    write_ready(results, {
        "run": args.run, "repo": args.repo, "sha": sha, "result": result,
        "unit": legs["unit"], "e2e": legs["e2e"], "smoke": legs["smoke"],
        "flaky": str(flaky), "audit": args.audit or "not-run",
    })
    if result == "green" and sha != "unknown":
        record_green(Path(args.state), sha, args.run)
    print(f"NIGHT={result} unit={legs['unit']} e2e={legs['e2e']} smoke={legs['smoke']} flaky={flaky}")
    return 0 if result == "green" else 1


# ------------------------------------------------------------------ cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="read the adopters' tables and emit tonight's matrix")
    b.add_argument("--adopters", required=True)
    b.add_argument("--url-base", required=True, help="e.g. https://github.com/<owner>/ (repo name and .git appended)")
    b.add_argument("--state-root", required=True, help="folder holding <repo>/state.json")
    b.add_argument("--full", choices=("true", "false"), default="false")
    b.add_argument("--today", default="", help="YYYY-MM-DD (UTC); default: today")
    b.add_argument("--github-output", default="")
    b.add_argument("--summary-file", default="")
    b.set_defaults(func=cmd_build)

    leg = sub.add_parser("leg", help="run one pytest leg and re-run its failures once")
    leg.add_argument("--name", required=True, choices=("unit", "e2e"))
    leg.add_argument("--python", required=True)
    leg.add_argument("--cwd", required=True)
    leg.add_argument("--args", required=True, help="pytest arguments, space separated")
    leg.add_argument("--retry-args", default="", help="extra arguments for the retry only")
    leg.add_argument("--marker", default="", help="pytest -m expression (e.g. the Windows-only exclusion)")
    leg.add_argument("--junit", required=True)
    leg.add_argument("--retry-junit", required=True)
    leg.add_argument("--flaky-out", required=True)
    leg.set_defaults(func=cmd_leg)

    r = sub.add_parser("ready", help="write READY and record a green night")
    r.add_argument("--results", required=True)
    r.add_argument("--state", required=True)
    r.add_argument("--run", required=True)
    r.add_argument("--repo", required=True)
    r.add_argument("--sha", default="")
    r.add_argument("--status", required=True)
    r.add_argument("--declared", default="", help="legs the adopter declares, comma separated")
    for name in ("unit", "e2e", "smoke"):
        r.add_argument(f"--{name}", default="", help=f"the {name} leg's own result, when it printed one")
        r.add_argument(f"--{name}-step", default="", help=f"the {name} step's outcome")
    r.add_argument("--audit", default="")
    r.set_defaults(func=cmd_ready)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
