"""Replace any adopter app's install with a fresh clone, run from a project-scaffolding clone.

    py -3 -I <scaffold>\\scripts\\tools\\replace_app.py <app> --root <root> [-WhatIf] [-Json]

The same flow as the app's own ``<app>.incoming\\setup.bat -Replace <app>``, run with this scaffold's
``src/installer_inplace.py`` rather than the copy vendored into the app, so an installer fix reaches
every app with a ``git pull`` of the scaffold, before any app is re-vendored. The app's own
``.fleet.toml`` declaration still decides what moves, and its own ``setup.bat -MigrateFrom`` still does
the install. Docs: ``docs/installer.md``.

A ``<root>\\<app>.incoming`` that is already there is used as the fresh clone. Otherwise the run clones
the origin of ``<root>\\<app>``, or of the one sibling copy named after the app's repository when that
folder is missing or is another app; ``-WhatIf`` clones nothing and reads the declaration from that copy's origin.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SRC = Path(__file__).resolve().parents[2] / "src"


def load_inplace() -> ModuleType:
    """This scaffold's ``installer_inplace.py``, by path, with ``installer_migrate.py`` beside it."""
    for name in ("installer_declaration", "installer_migrate", "installer_inplace"):
        if name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(name, SRC / f"{name}.py")
        if spec is None or spec.loader is None:
            raise SystemExit(f"replace_app: {SRC / name}.py is missing")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses resolve their module by name
        spec.loader.exec_module(module)
    return sys.modules["installer_inplace"]


def pick_anchor(inplace: ModuleType, folder: Path, runner: Any) -> tuple[Path | None, str]:
    """The copy whose origin is cloned: ``folder``, else the one sibling named after its repository; or why not.

    ``folder`` is passed over when it is another app: its origin is not named after the app, and it is no copy
    of any sibling whose origin is.
    """
    named = [s for s in inplace.siblings(folder, None)
             if inplace.repo_name(inplace.m.git(["remote", "get-url", "origin"], s, runner)) == folder.name.casefold()]
    wrong = "is not a checkout"
    if os.path.lexists(folder / ".git"):
        here = inplace.read_checkout(folder, runner)
        if (not named or inplace.repo_name(here.origin) == folder.name.casefold()
                or any(inplace.same_app(here, inplace.read_checkout(s, runner))[0] for s in named)):
            return folder, ""
        wrong = "is another app's checkout"
    if len(named) == 1:
        return named[0], ""
    found = ", ".join(s.name for s in named) or "none"
    return None, (f"{folder} {wrong} and the sibling copies whose origin is {folder.name} are: {found}; "
                  f"clone the app to {folder.name}{inplace.INCOMING_SUFFIX} yourself and run this again")


def main(argv: list[str] | None = None, runner: Any = subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="replace_app.py", description="Replace an app's install, wherever it "
                                     "runs, with a fresh clone at <root>\\<app>, keeping every replaced folder.")
    parser.add_argument("app", help="the app's folder name, which is where the clone lands")
    parser.add_argument("--root", "-Root", required=True, help="the folder that holds the app")
    parser.add_argument("-WhatIf", "--what-if", dest="what_if", action="store_true",
                        help="list every step and change nothing")
    parser.add_argument("-Json", "--json", dest="as_json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    if Path(args.app).name != args.app or args.app in ("", ".", ".."):
        parser.error("app is a folder name inside --root, not a path")
    inplace = load_inplace()
    folder = Path(args.root).resolve() / args.app
    incoming = inplace.incoming_path(folder)
    if os.path.lexists(incoming):
        report = inplace.replace(folder, incoming, what_if=args.what_if, as_json=args.as_json, runner=runner)
        return int(inplace.finish(report, args.as_json))
    anchor, why = pick_anchor(inplace, folder, runner)
    if anchor is None:
        report = inplace.m.MigrationReport(mode="replace", what_if=args.what_if)
        report.add("guard", "refused", "origin", why)
        return int(inplace.finish(report, args.as_json))
    report = inplace.replace(folder, None, what_if=args.what_if, as_json=args.as_json, runner=runner, anchor=anchor)
    return int(inplace.finish(report, args.as_json))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
