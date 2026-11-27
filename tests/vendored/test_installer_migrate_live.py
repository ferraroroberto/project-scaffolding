"""Migration for real, on a disposable pair: a throwaway app with its own origin, venv, server and port.

Nothing here touches an installed app. The pair lives under `tmp_path`: a bare
origin, an "installed" clone that runs a tiny version server from its own
`.venv`, and the clones the migration makes. The old copy is started through a
directory junction to its folder, so its command lines carry only that spelling,
while the migration is given the real path. It proves, with real processes:

* `-MigrateFrom` beside a running old copy fails verify, naming the old copy as
  the port's owner, even though both copies serve the same commit;
* `-InPlace -WhatIf` names every file the migration would copy, and changes nothing;
* `-InPlace` clones beside the old copy, stops it, renames it to
  `<folder>.bak-YYYYMMDD-1`, moves the clone to its path, migrates and verifies;
  the backup keeps the old state;
* verify finds the port in the app's own config and the scheme it really serves,
  where the declaration names another port and https;
* `-Replace`, run from a fresh clone beside an install whose own setup.bat predates
  `-InPlace` (clean, and with an uncommitted edit), changes nothing under `-WhatIf`
  (same folder listing, same PIDs), then migrates it in place: the edit stays in
  the backup and the clone serves the new commit on the install's port;
* no run leaves its `setup-inplace-*` folder in `%TEMP%`;
* no output contains a config or secret value.

Every process started under `tmp_path` is stopped at the end, by PID.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src import installer_migrate as m
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
CANARY = "CANARY-LIVE-91d2"
RUN_TIMEOUT_S = 600

pytestmark = [pytest.mark.windows_only,
              pytest.mark.skipif(shutil.which("git") is None or shutil.which("py") is None,
                                 reason="needs git and the py launcher")]

SERVER = '''import http.server, json, pathlib, subprocess
root = pathlib.Path(__file__).resolve().parent
sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
port = json.loads((root / "config.json").read_text(encoding="utf-8"))["port"]
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"git_sha": sha, "built_at": "t"}).encode()
        self.send_response(200 if self.path == "/api/version" else 404)
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
class Server(http.server.HTTPServer):
    allow_reuse_address = False  # on Windows reuse lets a second copy bind a port that is in use
Server(("127.0.0.1", port), Handler).serve_forever()
'''

# The declaration names a spare port and https; the app serves plain http on the port its config.json sets.
TOML = '''port = ":{declared}"

[install]
samples  = []
settings = ["config.json"]

[[install.config]]
sample = "config.sample.json"
target = "config.json"

[install.endpoint]
scheme      = "https"
port_config = "config.json"

[install.migrate]
copy    = ["config.json", "data", "secret.key"]
secrets = ["secret.key"]
start   = ["start.bat"]
'''


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          creationflags=NO_WINDOW, timeout=120)
    return done.stdout.strip()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed(tmp_path: Path, declared: int) -> Path:
    """A bare origin holding a minimal app that vendors the three installer modules."""
    seed, origin = tmp_path / "seed", tmp_path / "origin.git"
    (seed / "src").mkdir(parents=True)
    for name in ("installer.py", "installer_migrate.py", "installer_declaration.py", "installer_inplace.py"):
        shutil.copyfile(REPO_ROOT / "src" / name, seed / "src" / name)
    shutil.copyfile(REPO_ROOT / "scripts" / "templates" / "setup.bat", seed / "setup.bat")
    (seed / "server.py").write_text(SERVER, encoding="utf-8")
    (seed / "start.bat").write_text('@echo off\r\nstart "" /b "%~dp0.venv\\Scripts\\pythonw.exe" '
                                    '"%~dp0server.py"\r\n', encoding="ascii")
    (seed / "requirements.txt").write_text("", encoding="utf-8")
    (seed / "notes.txt").write_text("tracked\n", encoding="utf-8")
    (seed / "config.sample.json").write_text(json.dumps({"port": 0, "token": "", "data_dir": ""}), encoding="utf-8")
    (seed / ".fleet.toml").write_text(TOML.format(declared=declared), encoding="utf-8")
    (seed / ".gitignore").write_text(".venv/\nconfig.json\n*.json.bak-*\ndata/\nsecret.key\n__pycache__/\n",
                                     encoding="utf-8")
    _git(tmp_path, "init", "-q", "--bare", "--initial-branch=main", str(origin))
    _git(seed, "init", "-q", "--initial-branch=main")
    _git(seed, "add", "-A")
    # The machine's commit hooks are not under test.
    _git(seed, "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", "-c", "user.name=t",
         "-c", "user.email=t@example.invalid", "commit", "-qm", "seed")
    _git(seed, "push", "-q", str(origin), "main")
    return origin


def _temp(cwd: Path) -> Path:
    """The `%TEMP%` every setup.bat run of the pair gets, so what a run leaves there can be seen."""
    return cwd / "temp"


def _cmd(bat: Path, args: str, cwd: Path, log: Path) -> subprocess.CompletedProcess[str]:
    temp = _temp(cwd)
    temp.mkdir(exist_ok=True)
    env = {**os.environ, "TEMP": str(temp), "TMP": str(temp)}
    with open(log, "w", encoding="utf-8") as err:
        return subprocess.run(f'cmd.exe /d /s /c ""{bat}" {args}"', cwd=cwd, stdin=subprocess.DEVNULL, env=env,
                              stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", errors="replace",
                              timeout=RUN_TIMEOUT_S, check=False, creationflags=NO_WINDOW)


def _serving(port: int) -> dict[str, object] | None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        body = m.fetch_version(m.Endpoint(port=port))
        if body is not None:
            return body
        time.sleep(0.5)
    return None


def _install_old(tmp_path: Path, origin: Path, port: int, at: str | None = None) -> Path:
    """The "installed" copy: cloned (checked out ``at`` an older commit), configured, set up and running."""
    app = tmp_path / "app"
    _git(tmp_path, "clone", "-q", str(origin), str(app))
    if at:
        _git(app, "reset", "-q", "--hard", at)
    (app / "config.json").write_text(json.dumps({"port": port, "token": CANARY, "data_dir": str(app / "data")}),
                                     encoding="utf-8")
    (app / "data").mkdir()
    (app / "data" / "state.db").write_bytes(b"old state")
    (app / "data" / "state.db-wal").write_bytes(b"live sidecar")
    (app / "secret.key").write_text(CANARY, encoding="utf-8")
    done = _cmd(app / "setup.bat", "", tmp_path, tmp_path / "install.err")
    assert done.returncode == 0, done.stdout
    import _winapi  # Windows only, and the Mac nightly still imports this module to collect it

    link = tmp_path / "link"
    _winapi.CreateJunction(str(app), str(link))
    subprocess.run(f'cmd.exe /d /s /c ""{link / "start.bat"}""', cwd=link, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True,
                   creationflags=NO_WINDOW)
    assert _serving(port) is not None, "the old copy did not start"
    return app


@pytest.fixture
def pair(tmp_path: Path) -> Iterator[tuple[Path, Path, int]]:
    port, declared = _free_port(), _free_port()
    assert port != declared
    origin = _seed(tmp_path, declared)
    try:
        yield tmp_path, origin, port
    finally:
        snap = m.take_snapshot(subprocess.run)
        for proc in m.processes_from(snap, tmp_path, set()) if snap else []:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=60,
                           check=False, creationflags=NO_WINDOW)


def _rows(report: dict[str, object], section: str) -> list[dict[str, str]]:
    return report["sections"].get(section, [])  # type: ignore[union-attr, no-any-return]


def test_migrate_from_beside_a_running_old_copy_fails_verify_then_in_place_passes(
        pair: tuple[Path, Path, int]) -> None:
    tmp_path, origin, port = pair
    app = _install_old(tmp_path, origin, port)
    outputs: list[str] = []

    # Beside the old copy, without -StopOld: the old copy keeps the port, so verify must fail.
    new = tmp_path / "new"
    _git(tmp_path, "clone", "-q", str(origin), str(new))
    side = _cmd(new / "setup.bat", f'-MigrateFrom "{app}" -Json', tmp_path, tmp_path / "side.err")
    outputs += [side.stdout, (tmp_path / "side.err").read_text(encoding="utf-8", errors="replace")]
    assert side.returncode == 1, side.stdout
    report = json.loads(side.stdout)
    owner = [row for row in _rows(report, "verify") if row["item"] == f"port {port} owner"]
    assert owner and owner[0]["state"] == "failed" and "runs from the old copy" in owner[0]["detail"]
    assert {r["item"]: r["state"] for r in _rows(report, "copy")}["config.json"] == "copied"
    assert not (new / "data" / "state.db").exists(), "a database was copied while the old copy ran"

    # In place, what-if: every file the migration would copy, by name; nothing changes.
    preview = _cmd(app / "setup.bat", "-InPlace -WhatIf -Json", tmp_path, tmp_path / "whatif.err")
    outputs += [preview.stdout, (tmp_path / "whatif.err").read_text(encoding="utf-8", errors="replace")]
    assert preview.returncode == 0, preview.stdout + outputs[-1]
    stops = [r for r in _rows(json.loads(preview.stdout), "stop") if r["state"] == "would stop"]
    assert stops, "the processes started through the junction were not found by the folder's real path"
    would ={r["item"] for r in _rows(json.loads(preview.stdout), "copy") if r["state"] == "would copy"}
    assert {"config.json", "secret.key", "data/state.db"} <= would, preview.stdout
    assert "data/state.db-wal" not in would
    assert _serving(port) is not None and not any(tmp_path.glob("app.bak-*"))

    # In place: stop, rename to the backup, clone into the same path, migrate from the backup, verify.
    backup = tmp_path / f"app.bak-{datetime.date.today():%Y%m%d}-1"
    done = _cmd(app / "setup.bat", "-InPlace -Json", tmp_path, tmp_path / "inplace.err")
    outputs += [done.stdout, (tmp_path / "inplace.err").read_text(encoding="utf-8", errors="replace")]
    assert done.returncode == 0, done.stdout + outputs[-1]
    report = json.loads(done.stdout)
    assert report["ok"] and report["migration"]["ok"], done.stdout
    assert {r["item"]: r["state"] for r in _rows(report, "stop")}["app copies"] == "stopped"
    child = report["migration"]
    assert [row["state"] for row in _rows(child, "verify")] == ["ok", "ok"]

    assert (backup / ".git").is_dir() and (backup / "data" / "state.db-wal").is_file()
    assert _git(backup, "rev-parse", "HEAD") == _git(app, "rev-parse", "HEAD")
    assert json.loads((app / "config.json").read_text(encoding="utf-8"))["token"] == CANARY
    assert (app / "data" / "state.db").read_bytes() == b"old state"
    assert not (app / "data" / "state.db-wal").exists()
    assert (app / "secret.key").read_text(encoding="utf-8") == CANARY
    snap = m.take_snapshot(subprocess.run)
    assert snap is not None
    assert all(m.owner_of(snap, pid, app, backup)[0] == "clone" for pid in snap.listeners[port])
    assert not any(CANARY in text for text in outputs)
    assert not list(_temp(tmp_path).glob("setup-inplace-*")), "a run left its stage folder in %TEMP%"


# The last scaffold commit whose setup.bat has no -MigrateFrom or -InPlace: the installs in the field that
# predate them can only be replaced from a fresh clone.
PRE_IN_PLACE = "f774234"
OLD_TOML = TOML.split("[install.endpoint]")[0]


def _old_commit(tmp_path: Path, origin: Path) -> str:
    """Make the origin's history an old install followed by the current app: the old commit's sha."""
    work = tmp_path / "history"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "checkout", "-q", "--orphan", "old")
    for rel, published in (("src/installer.py", "src/installer.py"), ("setup.bat", "scripts/templates/setup.bat")):
        done = subprocess.run(["git", "show", f"{PRE_IN_PLACE}:{published}"], cwd=REPO_ROOT, capture_output=True,
                              timeout=60, check=False, creationflags=NO_WINDOW)
        if done.returncode != 0:
            pytest.skip(f"this checkout does not hold commit {PRE_IN_PLACE} (a shallow clone)")
        (work / rel).write_bytes(done.stdout)
    for rel in ("src/installer_migrate.py", "src/installer_declaration.py", "src/installer_inplace.py"):
        (work / rel).unlink()
    (work / ".fleet.toml").write_text(OLD_TOML, encoding="utf-8")
    hooks = ["-c", f"core.hooksPath={tmp_path / 'no-hooks'}", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    _git(work, "add", "-A")
    _git(work, *hooks, "commit", "-qm", "old install")
    old = _git(work, "rev-parse", "HEAD")
    new = _git(work, *hooks, "commit-tree", "main^{tree}", "-p", old, "-m", "current app")
    _git(work, "push", "-q", "--force", str(origin), f"{new}:refs/heads/main")
    return old


def _tree(tmp_path: Path) -> list[str]:
    """Every file and folder of the pair, leaving out run logs, %TEMP% and git's own folders."""
    temp = _temp(tmp_path)
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
                  if ".git" not in p.parts and p.suffix != ".err" and not p.is_relative_to(temp))


def _app_pids(app: Path) -> list[int]:
    snap = m.take_snapshot(subprocess.run)
    assert snap is not None
    return sorted(p.pid for p in m.processes_from(snap, app, set()))


@pytest.mark.parametrize("edited", [False, True], ids=["clean", "uncommitted-edit"])
def test_replace_migrates_an_install_older_than_in_place(pair: tuple[Path, Path, int], edited: bool) -> None:
    tmp_path, origin, port = pair
    old_sha = _old_commit(tmp_path, origin)
    new_sha = _git(origin, "rev-parse", "main")
    app = _install_old(tmp_path, origin, port, at=old_sha)
    notes = "edited here, never committed\n" if edited else "tracked\n"
    (app / "notes.txt").write_text(notes, encoding="utf-8")
    outputs: list[str] = []

    # The old copy's own setup.bat cannot replace itself: the gap -Replace closes.
    gap = _cmd(app / "setup.bat", "-InPlace -WhatIf", tmp_path, tmp_path / "gap.err")
    err = (tmp_path / "gap.err").read_text(encoding="utf-8", errors="replace")
    assert gap.returncode != 0 and "unrecognized arguments: -InPlace" in err

    incoming = tmp_path / "app.incoming"
    _git(tmp_path, "clone", "-q", str(origin), str(incoming))

    # What-if, from the fresh clone: the folder listing and the running PIDs are the same before and after.
    tree, pids = _tree(tmp_path), _app_pids(app)
    assert pids, "the old copy is not running"
    preview = _cmd(incoming / "setup.bat", "-Replace app -WhatIf -Json", tmp_path, tmp_path / "whatif.err")
    outputs += [preview.stdout, (tmp_path / "whatif.err").read_text(encoding="utf-8", errors="replace")]
    assert preview.returncode == 0, preview.stdout + outputs[-1]
    would = {r["item"] for r in _rows(json.loads(preview.stdout), "copy") if r["state"] == "would copy"}
    assert {"config.json", "secret.key", "data/state.db"} <= would, preview.stdout
    assert _tree(tmp_path) == tree and _app_pids(app) == pids
    assert _serving(port) == {"git_sha": old_sha, "built_at": "t"}

    # For real: stop, rename to the backup, move the clone in, migrate from the backup, verify.
    backup = tmp_path / f"app.bak-{datetime.date.today():%Y%m%d}-1"
    done = _cmd(incoming / "setup.bat", "-Replace app -Json", tmp_path, tmp_path / "replace.err")
    outputs += [done.stdout, (tmp_path / "replace.err").read_text(encoding="utf-8", errors="replace")]
    assert done.returncode == 0, done.stdout + outputs[-1]
    report = json.loads(done.stdout)
    assert report["ok"] and report["migration"]["ok"], done.stdout
    assert [row["state"] for row in _rows(report["migration"], "verify")] == ["ok", "ok"]

    assert not incoming.exists() and _git(app, "rev-parse", "HEAD") == new_sha
    assert _git(backup, "rev-parse", "HEAD") == old_sha
    assert (backup / "notes.txt").read_text(encoding="utf-8") == notes
    assert bool(_git(backup, "status", "--porcelain", "--untracked-files=no")) == edited
    assert (app / "notes.txt").read_text(encoding="utf-8") == "tracked\n"
    assert json.loads((app / "config.json").read_text(encoding="utf-8"))["token"] == CANARY
    assert (app / "data" / "state.db").read_bytes() == b"old state"
    assert _serving(port) == {"git_sha": new_sha, "built_at": "t"}
    assert not any(CANARY in text for text in outputs)
    assert not list(_temp(tmp_path).glob("setup-inplace-*")), "a run left its stage folder in %TEMP%"
