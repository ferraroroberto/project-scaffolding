"""The restart sheet's on-demand update: check where the checkout stands, then pull.

Every test builds a real git checkout cloned from a local bare remote under
``tmp_path`` and moves one side or the other, so each state comes from git
itself rather than from a stub. The routes are driven through FastAPI's
TestClient; nothing here touches this repo's own checkout.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src import self_restart
from src.no_window import NO_WINDOW
from src.self_restart import RestartStore, RestartTarget, inspect_update, pull_update, restart_router

ORIGIN = {"origin": "http://testserver"}
APP_TARGET = RestartTarget("app", "Restart app", self_restart.TRAY_RESTART)
# A machine-wide commit hook (an author allowlist) must not gate a throwaway fixture repo.
_NO_HOOKS = Path(tempfile.gettempdir()) / "self-restart-update-no-hooks"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={_NO_HOOKS}", *args],
        capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW, check=True,
    )
    return done.stdout.strip()


def _commit(repo: Path, name: str, text: str, message: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "--", name)
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    """``(checkout, upstream)``: the app's clone and a second clone that pushes."""
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True,
                   timeout=30, creationflags=NO_WINDOW)
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, timeout=30,
                   creationflags=NO_WINDOW, capture_output=True)
    _git(seed, "checkout", "-q", "-b", "main")
    _commit(seed, "app.py", "v1\n", "first")
    _git(seed, "push", "-q", "-u", "origin", "main")
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(bare), str(checkout)], check=True, timeout=30,
                   creationflags=NO_WINDOW, capture_output=True)
    return checkout, seed


def _push(upstream: Path, *messages: str) -> None:
    for i, message in enumerate(messages):
        _commit(upstream, "app.py", f"{message} {i}\n", message)
    _git(upstream, "push", "-q", "origin", "main")


def _guard(request: Request) -> None:
    if request.headers.get("authorization") != "Bearer ok":
        raise HTTPException(status_code=401, detail="sign in")


def _client(root: Path, status_dir: Path, *, update: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(restart_router(
        targets=(APP_TARGET,), status_dir=status_dir, guard=_guard, root=root,
        spawn=lambda spec, cwd: None, update=update,
    ))
    return TestClient(app, headers={"authorization": "Bearer ok"})


def test_in_sync_says_up_to_date(pair: tuple[Path, Path]) -> None:
    checkout, _ = pair
    result = inspect_update(checkout, fetch=True)
    assert (result["state"], result["behind"], result["ahead"]) == ("up-to-date", 0, 0)


def test_behind_counts_and_lists_the_new_subjects(pair: tuple[Path, Path]) -> None:
    checkout, upstream = pair
    _push(upstream, "fix the thing", "add the other thing")
    assert inspect_update(checkout, fetch=False)["state"] == "up-to-date"  # nothing fetched yet
    result = inspect_update(checkout, fetch=True)
    assert (result["state"], result["behind"]) == ("behind", 2)
    assert result["subjects"] == ["add the other thing", "fix the thing"]


def test_ahead_and_diverged_are_their_own_states(pair: tuple[Path, Path]) -> None:
    checkout, upstream = pair
    _commit(checkout, "local.py", "x\n", "local only")
    assert inspect_update(checkout, fetch=True)["state"] == "ahead"
    _push(upstream, "remote only")
    result = inspect_update(checkout, fetch=True)
    assert (result["state"], result["behind"], result["ahead"]) == ("diverged", 1, 1)


def test_dirty_and_wrong_branch_are_their_own_states(pair: tuple[Path, Path]) -> None:
    checkout, upstream = pair
    _push(upstream, "new")
    (checkout / "app.py").write_text("edited\n", encoding="utf-8")
    assert inspect_update(checkout, fetch=True)["state"] == "dirty"
    _git(checkout, "checkout", "-q", "--", "app.py")
    (checkout / "notes.txt").write_text("untracked\n", encoding="utf-8")
    assert inspect_update(checkout, fetch=True)["state"] == "behind"  # untracked files do not block
    _git(checkout, "checkout", "-q", "-b", "feature")
    result = inspect_update(checkout, fetch=True)
    assert (result["state"], result["current"]) == ("wrong-branch", "feature")


def test_a_failed_fetch_is_unknown_never_in_sync(pair: tuple[Path, Path], tmp_path: Path) -> None:
    checkout, _ = pair
    _git(checkout, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    result = inspect_update(checkout, fetch=True)
    assert result["state"] == "unknown"
    assert result["reason"].startswith("git fetch failed")


def test_a_fetch_timeout_is_unknown_with_its_reason(pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    checkout, _ = pair
    real_run = subprocess.run

    def slow_fetch(argv: list[str], *args: Any, **kwargs: Any) -> Any:
        if "fetch" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(self_restart.subprocess, "run", slow_fetch)
    result = inspect_update(checkout, fetch=True)
    assert result["state"] == "unknown"
    assert "did not finish" in result["reason"]


def test_pull_fast_forwards_and_answers_the_new_sha(pair: tuple[Path, Path]) -> None:
    checkout, upstream = pair
    _push(upstream, "one", "two")
    inspect_update(checkout, fetch=True)
    result = pull_update(checkout)
    assert (result["state"], result["pulled"]) == ("pulled", 2)
    assert result["sha"] == _git(checkout, "rev-parse", "--short", "HEAD")
    assert _git(checkout, "rev-parse", "HEAD") == _git(upstream, "rev-parse", "HEAD")
    assert inspect_update(checkout, fetch=False)["state"] == "up-to-date"


@pytest.mark.parametrize("setup", ["dirty", "ahead", "in-sync", "wrong-branch"])
def test_pull_refuses_anything_but_behind(pair: tuple[Path, Path], setup: str) -> None:
    checkout, upstream = pair
    if setup != "in-sync":
        _push(upstream, "new")
    if setup == "dirty":
        (checkout / "app.py").write_text("edited\n", encoding="utf-8")
    elif setup == "ahead":
        _commit(checkout, "local.py", "x\n", "local only")
    elif setup == "wrong-branch":
        _git(checkout, "checkout", "-q", "-b", "feature")
    inspect_update(checkout, fetch=True)
    head = _git(checkout, "rev-parse", "HEAD")
    result = pull_update(checkout)
    assert result["state"] == "refused"
    assert _git(checkout, "rev-parse", "HEAD") == head


def test_pull_refuses_while_the_index_is_locked_and_leaves_the_lock(pair: tuple[Path, Path]) -> None:
    checkout, upstream = pair
    _push(upstream, "new")
    inspect_update(checkout, fetch=True)
    lock = checkout / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    result = pull_update(checkout)
    assert result["state"] == "refused"
    assert "locked" in result["reason"]
    assert lock.exists()


def test_pull_refuses_to_delete_a_live_file_it_stops_tracking(pair: tuple[Path, Path]) -> None:
    checkout, upstream = pair
    _commit(upstream, "config.json", "{}\n", "track config")
    _git(upstream, "push", "-q", "origin", "main")
    inspect_update(checkout, fetch=True)
    assert pull_update(checkout)["state"] == "pulled"
    (checkout / "config.json").write_text('{"live": true}\n', encoding="utf-8")
    _git(checkout, "update-index", "--assume-unchanged", "config.json")  # a live edit, not dirt
    _git(upstream, "rm", "-q", "--cached", "config.json")
    _commit(upstream, ".gitignore", "config.json\n", "untrack config")
    _git(upstream, "push", "-q", "origin", "main")
    inspect_update(checkout, fetch=True)
    result = pull_update(checkout)
    assert result["state"] == "refused"
    assert "config.json" in result["reason"]
    assert (checkout / "config.json").read_text(encoding="utf-8") == '{"live": true}\n'


def test_pull_lets_an_ordinary_deletion_through(pair: tuple[Path, Path]) -> None:
    checkout, upstream = pair
    _commit(upstream, "old.py", "x\n", "add old")
    _git(upstream, "push", "-q", "origin", "main")
    inspect_update(checkout, fetch=True)
    pull_update(checkout)
    _git(upstream, "rm", "-q", "old.py")
    _git(upstream, "commit", "-q", "-m", "drop old")
    _git(upstream, "push", "-q", "origin", "main")
    inspect_update(checkout, fetch=True)
    assert pull_update(checkout)["state"] == "pulled"
    assert not (checkout / "old.py").exists()


def test_routes_check_then_pull_behind_guard_and_origin(pair: tuple[Path, Path], tmp_path: Path) -> None:
    checkout, upstream = pair
    _push(upstream, "new")
    client = _client(checkout, tmp_path / "status")
    assert client.get("/api/restart").json()["update"] is True
    assert client.post("/api/restart/check", headers={**ORIGIN, "authorization": ""}).status_code == 401
    assert client.post("/api/restart/check").status_code == 403  # no Origin
    assert client.post("/api/restart/pull", headers={"origin": "https://evil.example"}).status_code == 403
    check = client.post("/api/restart/check", headers=ORIGIN).json()
    assert (check["state"], check["behind"]) == ("behind", 1)
    pulled = client.post("/api/restart/pull", headers=ORIGIN).json()
    assert pulled["state"] == "pulled"


def test_pull_is_refused_while_a_restart_runs(pair: tuple[Path, Path], tmp_path: Path) -> None:
    checkout, upstream = pair
    _push(upstream, "new")
    client = _client(checkout, tmp_path / "status")
    client.post("/api/restart/check", headers=ORIGIN)
    assert client.post("/api/restart", json={"target": "app"}, headers=ORIGIN).status_code == 202
    assert RestartStore(tmp_path / "status").current()["state"] == "running"
    result = client.post("/api/restart/pull", headers=ORIGIN).json()
    assert (result["state"], result["reason"]) == ("refused", "a restart is running")


def test_update_off_mounts_no_update_routes(pair: tuple[Path, Path], tmp_path: Path) -> None:
    checkout, _ = pair
    client = _client(checkout, tmp_path / "status", update=False)
    assert client.get("/api/restart").json()["update"] is False
    assert client.post("/api/restart/check", headers=ORIGIN).status_code in (404, 405)
