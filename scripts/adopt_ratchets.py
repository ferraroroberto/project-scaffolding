"""Adopt this scaffold's gate ratchets into another repo, in one command.

    python scripts/adopt_ratchets.py <target-repo> [--ratchets comment,structure,...]

For every chosen ratchet it copies the script and its sibling modules into
`<target>/scripts/` byte for byte, records each copy in the target's
`.fleet.toml` `[vendored]` table (so the ratchets skip their own vendored
copies), appends a minimal `[<name>_ratchet]` table, copies the cross-platform
runner `run_ratchets.py`, and runs `--init` to write each first baseline.

Idempotent: an identical copy, an existing table or an existing baseline is
left alone and reported. A copy that differs from this scaffold's is refused,
never overwritten -- the adopter decides. Needs Python 3.11+ (`tomllib`) and
`git`; no other dependency. The procedure it automates, and what each ratchet
checks, is docs/adopting-ratchets.md.

Exit codes: 0 every chosen ratchet adopted and its baseline written or
already present; 1 a ratchet was refused or its `--init` failed (each line
says which); 2 bad arguments or an unusable target.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

SCAFFOLD_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCAFFOLD_ROOT))  # a script's own dir is sys.path[0], not the repo root

from src import runtime_files  # noqa: E402 -- needs the sys.path line above
from src.no_window import NO_WINDOW  # noqa: E402 -- needs the sys.path line above

SCRIPTS = SCAFFOLD_ROOT / "scripts"
RUNNER = "run_ratchets.py"
INIT_TIMEOUT_S = 900
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


@dataclass(frozen=True)
class Ratchet:
    name: str  # the `.fleet.toml` table is `[<name>_ratchet]`
    siblings: tuple[str, ...]  # modules the script loads from beside itself
    needs: str  # prerequisites beyond Python 3.11 and git
    starter: str = ""  # extra lines the table needs before `--init` can run

    @property
    def table(self) -> str:
        return f"{self.name}_ratchet"

    @property
    def files(self) -> tuple[str, ...]:
        return (f"{self.table}.py", *(f"{s}.py" for s in self.siblings))


#: Every ratchet, in gate stage order (scripts/verify-before-ship.ps1, run_ratchets.py).
RATCHETS: tuple[Ratchet, ...] = (
    Ratchet("static", (), "ruff (pip install ruff); Node with npx for the duplicate check, else duplicates = false"),
    Ratchet("comment", (), "-"),
    Ratchet("docs", (), "-"),
    Ratchet("structure", ("structure_layout", "structure_band"), "-"),
    Ratchet("instruction", ("instruction_frontmatter", "instruction_repeats"), "-"),
    Ratchet("doc_refs", (), "-"),
    Ratchet("dead_code", (), "-"),
    Ratchet("conventions", ("conventions_readers", "conventions_state"), "-",
            'rules = ["subprocess-timeout"]  # pick more: docs/conventions-ratchet.md\n'),
    Ratchet("runtime_write", ("runtime_write_resolve",), "-"),
    Ratchet("usage_track", ("usage_track_scan",), "a web UI (HTML/JS) to scan",
            'rules = ["untracked-control", "untracked-sheet", "dynamic-id"]  # docs/usage-track-ratchet.md\n'),
)
BY_NAME = {r.name: r for r in RATCHETS}
#: Python-only, no choices to make: what `--ratchets` defaults to.
RECOMMENDED = ("comment", "docs", "structure", "instruction", "doc_refs", "dead_code", "runtime_write")


def _run(cmd: list[str], cwd: Path, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=timeout, check=False,
    )


def scaffold_sha() -> str | None:
    """This scaffold's commit, recorded as each copy's provenance; None when not a git checkout."""
    try:
        proc = _run(["git", "rev-parse", "HEAD"], SCAFFOLD_ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and len(sha) == 40 else None


def has_npx() -> bool:
    return shutil.which("npx") is not None


def has_ruff() -> bool:
    try:
        return _run([sys.executable, "-m", "ruff", "--version"], SCAFFOLD_ROOT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ------------------------------------------------------------------- copying

def copy_file(name: str, target: Path) -> str:
    """Copy one script into `<target>/scripts/`; returns `copied`, `same` or `refused`."""
    src, dest = SCRIPTS / name, target / "scripts" / name
    if dest.exists():
        return "same" if dest.read_bytes() == src.read_bytes() else "refused"
    runtime_files.make_dirs(dest.parent)
    runtime_files.copy_file(src, dest)
    return "copied"


# ---------------------------------------------------------------- .fleet.toml

def table_lines(r: Ratchet, *, npx: bool) -> str:
    body = f"[{r.table}]\nenabled = true\n{r.starter}"
    if r.name == "static" and not npx:
        body += "duplicates = false  # no npx here: the duplicate check reports OFF, never clean\n"
    return body


def vendored_line(name: str, sha: str | None) -> str:
    key = name.removesuffix(".py")
    pin = f', sha = "{sha}"' if sha else ""
    return f'{key} = {{ src = "scripts/{name}"{pin}, dest = "scripts/{name}" }}\n'


def merge_toml(text: str, tables: list[str], vendored: list[str]) -> str:
    """Append ratchet tables and insert `[vendored]` entries, keeping everything already there.

    A missing `[vendored]` table is appended; an existing one gets the new
    lines directly under its header, since TOML forbids a second header.
    """
    out = text if not text or text.endswith("\n") else text + "\n"
    if vendored:
        lines = out.splitlines(keepends=True)
        header = next((i for i, ln in enumerate(lines) if ln.strip() == "[vendored]"), None)
        if header is None:
            out += ("\n" if out else "") + "[vendored]\n" + "".join(vendored)
        else:
            out = "".join(lines[: header + 1] + vendored + lines[header + 1:])
    for table in tables:
        out += ("\n" if out else "") + table
    return out


def plan_toml(target: Path, chosen: list[Ratchet], files: list[str], sha: str | None,
              *, npx: bool) -> tuple[str, list[str]]:
    """(new text, notes) -- raises ValueError on an unusable file."""
    path = target / ".fleet.toml"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} is not valid TOML: {exc}") from exc
    vendored_table = before.get("vendored", {})
    if not isinstance(vendored_table, dict):
        raise ValueError(f"{path}: [vendored] is not a table")
    notes: list[str] = []
    tables = []
    for r in chosen:
        existing = before.get(r.table)
        if existing is None:
            tables.append(table_lines(r, npx=npx))
        elif isinstance(existing, dict) and existing.get("enabled") is not True:
            notes.append(f"{r.name}: [{r.table}] exists but is not enabled -- left as is; set enabled = true")
    vendored = [vendored_line(f, sha) for f in files if f.removesuffix(".py") not in vendored_table]
    new = merge_toml(text, tables, vendored)
    try:
        tomllib.loads(new)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"merging into {path} would produce invalid TOML ({exc}); edit it by hand") from exc
    return new, notes


# ---------------------------------------------------------------------- init

def baseline_path(target: Path, r: Ratchet) -> Path:
    """The ratchet's baseline file: the table's `baseline` key, else the scripts' shared default."""
    text = (target / ".fleet.toml").read_text(encoding="utf-8")
    table = tomllib.loads(text).get(r.table, {})
    default = "." + r.name.replace("_", "-") + "-ratchet-baseline.json"
    name = table.get("baseline", default) if isinstance(table, dict) else default
    return target / str(name)


def init_ratchet(target: Path, r: Ratchet) -> tuple[int, str]:
    """(exit code, last output line) of `--init`, or of a plain check when a baseline exists."""
    mode = [] if baseline_path(target, r).exists() else ["--init"]
    try:
        proc = _run([sys.executable, f"scripts/{r.table}.py", *mode], target, INIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 3, f"could not run: {exc}"
    lines = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode, (lines[-1] if lines else "(no output)")


EXIT_MEANING = {0: "ok", 1: "fail", 2: "config error", 3: "NOT CONFIRMED"}


# ----------------------------------------------------------------------- CLI

def parse_names(raw: str | None) -> list[Ratchet]:
    names = list(RECOMMENDED) if raw in (None, "recommended") else (
        [r.name for r in RATCHETS] if raw == "all" else [n.strip().removesuffix("_ratchet") for n in raw.split(",") if n.strip()]
    )
    unknown = [n for n in names if n not in BY_NAME]
    if unknown:
        raise ValueError(f"unknown ratchet(s) {', '.join(unknown)}; choose from {', '.join(BY_NAME)}")
    return [r for r in RATCHETS if r.name in names]  # stage order, whatever order was typed


def check_target(target: Path) -> str | None:
    """Why `target` cannot be adopted into, or None."""
    if not target.is_dir():
        return f"{target} is not a directory"
    if target.resolve() == SCAFFOLD_ROOT:
        return "the target is this scaffold itself"
    try:
        proc = _run(["git", "rev-parse", "--is-inside-work-tree"], target)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git is not usable: {exc}"
    if proc.stdout.strip() != "true":
        return f"{target} is not inside a git work tree (the ratchets read `git ls-files`); run `git init` first"
    return None


def adopt(target: Path, chosen: list[Ratchet]) -> int:
    npx = has_npx()
    failed = False
    if any(r.name == "static" for r in chosen) and not has_ruff():
        print("static: NOT ADOPTED -- ruff is not installed for this Python (pip install ruff), and the static ratchet needs it")
        chosen = [r for r in chosen if r.name != "static"]
        failed = True
    refused: set[str] = set()
    files: list[str] = []
    for r in chosen:
        for name in r.files:
            state = copy_file(name, target)
            print(f"  scripts/{name}: {state}")
            if state == "refused":
                print(f"    differs from this scaffold's copy -- not overwritten; compare, then delete it or keep {r.name} out")
                refused.add(r.name)
            else:
                files.append(name)
    runner_state = copy_file(RUNNER, target)
    print(f"  scripts/{RUNNER}: {runner_state}")
    if runner_state == "refused":
        print("    differs from this scaffold's copy -- not overwritten")
        failed = True
    else:
        files.append(RUNNER)
    sha = scaffold_sha()
    if sha is None:
        print("  provenance: unknown (this scaffold is not a git checkout) -- [vendored] entries carry no sha")
    usable = [r for r in chosen if r.name not in refused]
    try:
        text, notes = plan_toml(target, usable, files, sha, npx=npx)
    except ValueError as exc:
        print(f"adopt ratchets: .fleet.toml: {exc}")
        return EXIT_FAILED
    runtime_files.save_text(target / ".fleet.toml", text, newline="\n")
    for note in notes:
        print(f"  {note}")
    if any(r.name == "static" for r in usable) and not npx:
        print("  static: duplicates = false written (no npx here) -- the duplicate check reports OFF on every run")
    failed |= bool(refused)
    print("baselines:")
    for r in chosen:
        if r.name in refused:
            print(f"  {r.name}: REFUSED (a modified copy is in the way)")
            continue
        code, last = init_ratchet(target, r)
        print(f"  {r.name}: exit {code} ({EXIT_MEANING.get(code, 'unexpected')}) -- {last}")
        failed |= code != 0
    print("next: review and commit scripts/, .fleet.toml and the .*-ratchet-baseline.json files; "
          f"then wire `python scripts/{RUNNER}` into the gate (docs/adopting-ratchets.md)")
    return EXIT_FAILED if failed else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("target", type=Path, help="the repo to adopt the ratchets into")
    parser.add_argument("--ratchets", help=f"comma list, `recommended` (default: {','.join(RECOMMENDED)}) or `all`")
    args = parser.parse_args(argv)
    try:
        chosen = parse_names(args.ratchets)
    except ValueError as exc:
        parser.error(str(exc))
    target = args.target.resolve()
    problem = check_target(target)
    if problem:
        print(f"adopt ratchets: {problem}")
        return EXIT_USAGE
    print(f"adopting {', '.join(r.name for r in chosen)} into {target}")
    return adopt(target, chosen)


if __name__ == "__main__":
    sys.exit(main())
