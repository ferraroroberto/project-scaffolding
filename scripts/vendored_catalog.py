"""Reader for this scaffold's `[components]` catalog in `.fleet.toml` (#230).

`project-scaffolding` publishes N vendor-verbatim components; each adopter repo
records what it copied in its own `.fleet.toml`'s `[vendored]` table. Until #230
there was no machine-readable list of what the scaffold *publishes* -- only three
partial, hand-maintained restatements of it (this script's former hardcoded twin
inside `scripts/verify-before-ship.ps1`, the union of whatever adopters happened
to declare, and prose in `README.md`). That gap is what let
`/propagate-vendored tailscale_cert` cover one repo out of seven and report
success: with no catalog, a repo carrying an undeclared component is
indistinguishable from a repo that never adopted it.

This module is the single reader for that table. Two consumers:

  * `scripts/verify-before-ship.ps1` derives its `mypy --strict` gate list from
    `mypy-targets`, so a newly added Python component is gated the day it lands
    rather than the day someone remembers to append it to a second list.
  * `fleet-config`'s `skills/_lib/vendored_drift.py` reads the same table (with
    its own `tomllib` parse -- no cross-repo import) to hash every fleet repo's
    copy of a known component path and name the undeclared carriers.

Stdlib-only and side-effect-free on import, so it stays runnable from a bare
interpreter (the gate calls it before it has proven the venv is healthy).

CLI:

  list [--json]     every component: `<key>\t<src>` (or one JSON object)
  mypy-targets      the Python subset, one path per line, sorted -- a `.py`
                    component as-is, a package component with a trailing `/`

Both subcommands exit non-zero on a missing/unreadable/absent catalog rather
than printing an empty list: an empty `mypy --strict` stage would pass the gate
while checking nothing, which is exactly the silent-partial shape #230 is about.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class CatalogError(RuntimeError):
    """The `[components]` table is missing, unreadable, or malformed."""


def parse_components(toml_text: str) -> dict[str, dict[str, str]]:
    """Parse a `.fleet.toml`'s `[components]` table -> ``{key: {"src": ...}}``.

    Raises `CatalogError` when the table is absent or empty -- unlike the
    adopter-side `[vendored]` table (whose absence is the normal state of most
    fleet repos), the scaffold's own catalog missing means the caller cannot do
    its job and must say so, not silently return nothing. An entry that is not a
    table, or carries no `src`, is a malformed declaration and is likewise
    fatal: a component that cannot be located is worse than one never declared,
    because it reads as covered.
    """
    data = tomllib.loads(toml_text)
    table = data.get("components")
    if not isinstance(table, dict) or not table:
        raise CatalogError("no [components] table in .fleet.toml")
    out: dict[str, dict[str, str]] = {}
    for key, entry in table.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("src"), str) or not entry["src"]:
            raise CatalogError(f"component '{key}': entry must be a table with a non-empty string `src`")
        out[key] = {"src": entry["src"]}
    return out


def load_catalog(repo_root: Path | None = None) -> dict[str, dict[str, str]]:
    """`parse_components` over `<repo_root>/.fleet.toml` (default: this repo)."""
    root = repo_root or REPO_ROOT
    path = root / ".fleet.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"cannot read {path}: {exc}") from exc
    try:
        return parse_components(text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"invalid TOML in {path}: {exc}") from exc


def mypy_targets(catalog: dict[str, dict[str, str]], repo_root: Path | None = None) -> list[str]:
    """The Python subset of the catalog, as mypy path arguments, sorted.

    A `.py` component is passed as-is; a package component (a directory holding
    at least one `.py`) is passed with a trailing `/`, matching how the gate's
    former hardcoded list spelled `src/notify/`. A component with no Python in
    it (every `_vendored/` UI folder) is skipped -- mypy has nothing to say
    about CSS. A declared `src` that does not exist on disk is NOT silently
    skipped: `tests/test_vendored_catalog.py` fails on it, and passing the
    missing path to mypy would fail the gate loudly too, which is the point.
    """
    root = repo_root or REPO_ROOT
    targets: list[str] = []
    for entry in catalog.values():
        src = entry["src"]
        path = root / src
        if src.endswith(".py"):
            targets.append(src)
        elif path.is_dir() and any(path.glob("*.py")):
            targets.append(src.rstrip("/") + "/")
    return sorted(targets)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read this scaffold's [components] catalog from .fleet.toml.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="every component as `<key>\\t<src>`")
    p_list.add_argument("--json", action="store_true", help="emit one JSON object instead")
    sub.add_parser("mypy-targets", help="the Python subset, one mypy path argument per line")

    args = ap.parse_args(argv)
    try:
        catalog = load_catalog()
    except CatalogError as exc:
        print(f"vendored_catalog: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "list":
        if args.json:
            print(json.dumps(catalog, indent=2, sort_keys=True))
        else:
            for key in sorted(catalog):
                print(f"{key}\t{catalog[key]['src']}")
        return 0

    targets = mypy_targets(catalog)
    if not targets:
        print("vendored_catalog: catalog declares no Python components", file=sys.stderr)
        return 2
    for target in targets:
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
