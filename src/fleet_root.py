"""Where the fleet's repositories live on this machine.

Fleet code that needs a sibling repo (a shared helper, another app's
checkout, a scratch folder beside the repos) asks this module for the root
instead of spelling a drive letter, so the same code runs unchanged on a
machine whose repos sit somewhere else. The conventions ratchet's
``no-drive-path`` rule is what stops a new drive literal from creeping back.

Resolution order, highest precedence first:

1. ``FLEET_ROOT`` — an environment variable naming the root directory.
2. The machine-local config file ``$XDG_CONFIG_HOME/fleet/fleet.toml``
   (``~/.config/fleet/fleet.toml`` when ``XDG_CONFIG_HOME`` is unset), key
   ``root``. It lives in the user's home, never in a repo, because the root
   is a fact about the machine rather than about any checkout.
3. The parent of the git checkout holding this file. A repo cloned at
   ``<root>/<repo>`` (or a sibling worktree ``<root>/<repo>-wt-<N>``) finds
   ``<root>`` with no setup at all.

Each step either yields an existing absolute directory or raises
``FleetRootError`` naming the step and the value it read. A set-but-wrong
value never falls through to the next step: a typo in ``FLEET_ROOT`` must
surface, not quietly resolve to wherever the checkout happens to be. When no
step applies (no variable, no config, and this file is not inside a git
checkout), the error says so rather than guessing a path.

Vendor-verbatim: adopters copy this file byte-identical into their own
``src/`` (like ``src/runtime_data.py``). Stdlib-only (Python 3.11+ for
``tomllib``) and side-effect-free at import; resolution happens per call so a
test or a long-lived process sees a changed environment.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

FLEET_ROOT_ENV = "FLEET_ROOT"
CONFIG_KEY = "root"


class FleetRootError(RuntimeError):
    """The fleet root could not be established; the message names the step."""


def fleet_config_path() -> Path:
    """The machine-local config file consulted after ``FLEET_ROOT``."""
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_home = Path(base) if base else Path.home() / ".config"
    return config_home / "fleet" / "fleet.toml"


def _checked(raw: str, source: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise FleetRootError(f"{source} is not an absolute path: {raw!r}")
    if not path.is_dir():
        raise FleetRootError(f"{source} is not an existing directory: {raw!r}")
    return path


def _from_config(config: Path) -> Path | None:
    if not config.is_file():
        return None
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise FleetRootError(f"cannot read fleet config {config}: {exc}") from exc
    if CONFIG_KEY not in data:
        return None
    value = data[CONFIG_KEY]
    if not isinstance(value, str) or not value.strip():
        raise FleetRootError(f"{config} key {CONFIG_KEY!r} must be a non-empty string")
    return _checked(value.strip(), f"{config} key {CONFIG_KEY!r}")


def _checkout_parent(anchor: Path) -> Path | None:
    # A worktree or submodule has a `.git` file rather than a folder; both mark
    # the checkout root.
    for folder in anchor.resolve().parents:
        if (folder / ".git").exists():
            return folder.parent
    return None


def fleet_root(*, anchor: Path | None = None) -> Path:
    """Resolve the directory that holds the fleet's repositories.

    ``anchor`` is the file whose git checkout step 3 starts from; it defaults
    to this module, so callers normally pass nothing.
    """
    override = os.environ.get(FLEET_ROOT_ENV, "").strip()
    if override:
        return _checked(override, f"${FLEET_ROOT_ENV}")
    config = fleet_config_path()
    from_config = _from_config(config)
    if from_config is not None:
        return from_config
    start = anchor if anchor is not None else Path(__file__)
    parent = _checkout_parent(start)
    if parent is not None:
        return parent
    raise FleetRootError(
        f"fleet root not resolvable: ${FLEET_ROOT_ENV} is unset, {config} has no "
        f"{CONFIG_KEY!r} key, and {start} is not inside a git checkout"
    )
