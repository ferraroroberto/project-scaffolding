"""Run every enabled gate ratchet, in stage order, on any OS -- one pass/fail.

    python scripts/run_ratchets.py                              # the ratchet stages
    python scripts/run_ratchets.py --tests python -m pytest -q  # + the runtime write probe around the tests

Reads `.fleet.toml` beside `scripts/` and runs each `[<name>_ratchet]` table
with `enabled = true` through its `scripts/<name>_ratchet.py`. With `--tests`,
everything after it is the test command: the runtime write ratchet's
`--snapshot` is taken before it and `--probe` after it, so a file the tests
leave under a code folder fails the run (the same bracket the scaffold's own
gate draws). Without `--tests` the probe is reported as OFF, never as clean.

Exit codes (a state is never folded into a pass):

  0  every enabled stage passed
  1  a stage found a new hit, or the test command failed
  2  a configuration error, or no ratchet is enabled at all
  3  NOT CONFIRMED: a stage could not establish its result (its own exit 3, a
     script missing beside this one, a stage that could not start or timed out)

Copied into adopters by scripts/adopt_ratchets.py; stdlib-only, Python 3.11+.
Procedure: docs/adopting-ratchets.md in project-scaffolding.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: Gate stage order: the cheap whole-tree checks first, the runtime write ratchet last.
STAGES = ("static", "comment", "docs", "structure", "instruction", "doc_refs",
          "dead_code", "conventions", "runtime_write", "usage_track")
STAGE_TIMEOUT_S = 1800
EXIT_PASS, EXIT_FAIL, EXIT_CONFIG, EXIT_NOT_CONFIRMED = 0, 1, 2, 3
STATE = {EXIT_PASS: "PASS", EXIT_FAIL: "FAIL", EXIT_CONFIG: "CONFIG ERROR", EXIT_NOT_CONFIRMED: "NOT CONFIRMED"}
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def enabled_stages(root: Path) -> list[str]:
    """Stage names whose table says `enabled = true`; raises ValueError on an unusable file."""
    path = root / ".fleet.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} is not valid TOML: {exc}") from exc
    return [s for s in STAGES if isinstance(data.get(f"{s}_ratchet"), dict)
            and data[f"{s}_ratchet"].get("enabled") is True]


def run_step(label: str, cmd: list[str], root: Path, timeout: float) -> int:
    """Run one step with its output streaming through; an unstartable or hung step is exit 3."""
    print(f"\n>> {label}", flush=True)
    try:
        code = subprocess.run(cmd, cwd=root, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
                              timeout=timeout, check=False).returncode
    except OSError as exc:
        print(f"{label}: could not start: {exc}")
        code = EXIT_NOT_CONFIRMED
    except subprocess.TimeoutExpired:
        print(f"{label}: still running after {timeout:.0f}s -- stopped")
        code = EXIT_NOT_CONFIRMED
    print(f"[{STATE.get(code, f'exit {code}')}] {label}", flush=True)
    return code


def stage(root: Path, name: str, *extra: str) -> int:
    script = root / "scripts" / f"{name}_ratchet.py"
    label = f"{name.replace('_', ' ')} ratchet" + (f" {extra[0]}" if extra else "")
    if not script.is_file():
        print(f"\n>> {label}\n{label}: scripts/{script.name} is missing though [{name}_ratchet] is enabled")
        print(f"[NOT CONFIRMED] {label}")
        return EXIT_NOT_CONFIRMED
    return run_step(label, [sys.executable, str(script), *extra], root, STAGE_TIMEOUT_S)


def worst(codes: list[int]) -> int:
    """A new hit outranks a config error, which outranks an unknown; anything else is a failure."""
    for code in (EXIT_FAIL, EXIT_CONFIG, EXIT_NOT_CONFIRMED):
        if code in codes:
            return code
    return EXIT_PASS if all(c == EXIT_PASS for c in codes) else EXIT_FAIL


def run(root: Path, tests: list[str] | None, tests_timeout: float) -> int:
    try:
        stages = enabled_stages(root)
    except ValueError as exc:
        print(f"run ratchets: CONFIG ERROR: {exc}")
        return EXIT_CONFIG
    if not stages:
        print("run ratchets: CONFIG ERROR: no [<name>_ratchet] table has enabled = true in .fleet.toml")
        return EXIT_CONFIG
    results: list[tuple[str, int]] = [(s, stage(root, s)) for s in stages]
    probe = "runtime_write" in stages
    if tests:
        if probe:
            fd, snap = tempfile.mkstemp(prefix="runtime-write-snapshot-", suffix=".json")
            os.close(fd)
            try:
                results.append(("runtime write snapshot", stage(root, "runtime_write", "--snapshot", snap)))
                results.append(("tests", run_step("tests: " + " ".join(tests), tests, root, tests_timeout)))
                results.append(("runtime write probe", stage(root, "runtime_write", "--probe", snap)))
            finally:
                Path(snap).unlink(missing_ok=True)
        else:
            results.append(("tests", run_step("tests: " + " ".join(tests), tests, root, tests_timeout)))
    elif probe:
        print("\n[OFF] runtime write probe -- no --tests command given, so the test run was not checked")
    print("\nsummary:")
    for name, code in results:
        print(f"  {STATE.get(code, f'exit {code}'):<13} {name}")
    final = worst([c for _, c in results])
    print(f"run ratchets: {STATE.get(final, 'FAIL')}")
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repo root (default: the folder above scripts/)")
    parser.add_argument("--tests-timeout", type=float, default=3600, help="seconds the test command may run")
    parser.add_argument("--tests", nargs=argparse.REMAINDER, help="the test command; must come last")
    args = parser.parse_args(argv)
    return run(args.root.resolve(), args.tests or None, args.tests_timeout)


if __name__ == "__main__":
    sys.exit(main())
