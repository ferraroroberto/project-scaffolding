"""The vendored self-restart server half: routes, records and the detached runner.

The routes are driven through FastAPI's TestClient with a stub spawn, so no
recipe runs; the runner is driven with harmless Python one-liners as recipes.
The Windows-only test starts the real detached runner from a parent process,
kills that parent's tree with ``taskkill /T`` (what ``tray.bat --restart``
does to the webapp) and asserts the runner still records its ending.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src import self_restart
from src.no_window import NO_WINDOW
from src.self_restart import RestartStore, RestartTarget, restart_router, run_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGIN = {"origin": "http://testserver"}
APP_TARGET = RestartTarget("app", "Restart app", self_restart.TRAY_RESTART)


def _guard(request: Request) -> None:
    if request.headers.get("authorization") != "Bearer ok":
        raise HTTPException(status_code=401, detail="sign in")


def _client(tmp_path: Path, spawned: list[Any], *, fail: bool = False,
            targets: tuple[RestartTarget, ...] = (APP_TARGET,)) -> TestClient:
    def spawn(spec_path: Path, root: Path) -> None:
        if fail:
            raise OSError("no cmd.exe")
        spawned.append((spec_path, root))

    app = FastAPI()
    app.include_router(restart_router(
        targets=targets, status_dir=tmp_path, guard=_guard, root=Path("E:/fleet/my-app"), spawn=spawn,
    ))
    return TestClient(app, headers={"authorization": "Bearer ok"})


def test_both_routes_sit_behind_the_apps_guard(tmp_path: Path) -> None:
    spawned: list[Any] = []
    client = _client(tmp_path, spawned)
    assert client.get("/api/restart", headers={"authorization": ""}).status_code == 401
    answer = client.post("/api/restart", json={"target": "app"}, headers={**ORIGIN, "authorization": ""})
    assert answer.status_code == 401
    assert spawned == []


def test_get_lists_the_declared_targets(tmp_path: Path) -> None:
    body = _client(tmp_path, []).get("/api/restart").json()
    assert body == {"targets": [{"id": "app", "label": "Restart app", "warning": ""}], "last": None}


@pytest.mark.parametrize("headers", [{}, {"origin": "https://evil.example"}])
def test_post_refuses_a_missing_or_foreign_origin(tmp_path: Path, headers: dict[str, str]) -> None:
    spawned: list[Any] = []
    answer = _client(tmp_path, spawned).post("/api/restart", json={"target": "app"}, headers=headers)
    assert answer.status_code == 403
    assert spawned == []


@pytest.mark.parametrize("payload", [{"target": "session-host"}, {"command": "tray.bat"}, ["app"]])
def test_post_runs_only_a_declared_target(tmp_path: Path, payload: Any) -> None:
    spawned: list[Any] = []
    answer = _client(tmp_path, spawned).post("/api/restart", json=payload, headers=ORIGIN)
    assert answer.status_code == 400
    assert spawned == []


def test_post_records_the_run_and_spawns_the_declared_command(tmp_path: Path) -> None:
    spawned: list[Any] = []
    client = _client(tmp_path, spawned)
    answer = client.post("/api/restart", json={"target": "app"}, headers=ORIGIN)
    assert answer.status_code == 202
    restart_id = answer.json()["restart_id"]
    spec = json.loads((tmp_path / "spec.json").read_text(encoding="utf-8"))
    assert spec["command"] == list(self_restart.TRAY_RESTART)
    assert spec["root"] == str(Path("E:/fleet/my-app"))
    assert spawned == [(tmp_path / "spec.json", Path("E:/fleet/my-app"))]
    last = client.get("/api/restart").json()["last"]
    assert (last["id"], last["target"], last["state"]) == (restart_id, "app", "running")


def test_a_second_post_while_running_is_refused(tmp_path: Path) -> None:
    spawned: list[Any] = []
    client = _client(tmp_path, spawned)
    first = client.post("/api/restart", json={"target": "app"}, headers=ORIGIN).json()
    second = client.post("/api/restart", json={"target": "app"}, headers=ORIGIN)
    assert second.status_code == 409
    assert second.json()["restart_id"] == first["restart_id"]
    assert len(spawned) == 1


def test_a_running_record_past_its_timeout_reads_unknown_and_frees_the_slot(tmp_path: Path) -> None:
    spawned: list[Any] = []
    client = _client(tmp_path, spawned)
    RestartStore(tmp_path).write({
        "id": "old", "target": "app", "state": "running", "started_ts": time.time() - 1000, "timeout_s": 180,
    })
    assert client.get("/api/restart").json()["last"]["state"] == "unknown"
    assert client.post("/api/restart", json={"target": "app"}, headers=ORIGIN).status_code == 202


def test_a_runner_that_cannot_start_is_an_error_not_a_success(tmp_path: Path) -> None:
    client = _client(tmp_path, [], fail=True)
    answer = client.post("/api/restart", json={"target": "app"}, headers=ORIGIN)
    assert answer.status_code == 500
    assert client.get("/api/restart").json()["last"]["state"] == "error"


@pytest.mark.parametrize("targets", [
    (RestartTarget("App!", "x", ("a",)),),
    (APP_TARGET, APP_TARGET),
    (RestartTarget("app", "x", ()),),
])
def test_bad_target_declarations_fail_at_mount(tmp_path: Path, targets: tuple[RestartTarget, ...]) -> None:
    with pytest.raises(ValueError):
        restart_router(targets=targets, status_dir=tmp_path, guard=_guard)


def _spec(tmp_path: Path, command: list[str], timeout_s: float = 30) -> Path:
    store = RestartStore(tmp_path)
    store.write({"id": "r1", "target": "app", "state": "running", "started_ts": time.time(), "timeout_s": timeout_s})
    store.write_spec({"id": "r1", "target": "app", "command": command, "root": str(tmp_path),
                      "timeout_s": timeout_s, "delay_s": 0})
    return store.spec_path


@pytest.mark.parametrize(("command", "timeout_s", "state", "exit_code"), [
    ([sys.executable, "-c", "print('restarted')"], 30, "ok", 0),
    ([sys.executable, "-c", "print('ERROR: reclaim failed'); raise SystemExit(3)"], 30, "failed", 3),
    ([sys.executable, "-c", "import time; time.sleep(10)"], 0.5, "timeout", None),
    ([str(Path("no-such-dir") / "no-such-recipe.exe")], 30, "error", None),
])
def test_the_runner_records_each_ending_as_its_own_state(
    tmp_path: Path, command: list[str], timeout_s: float, state: str, exit_code: Any,
) -> None:
    assert run_spec(_spec(tmp_path, command, timeout_s)) == state
    record = RestartStore(tmp_path).read()
    assert record is not None
    assert (record["state"], record["exit_code"]) == (state, exit_code)
    assert record["finished_at"]


def test_a_failed_run_shows_its_log_tail(tmp_path: Path) -> None:
    run_spec(_spec(tmp_path, [sys.executable, "-c", "print('ERROR: reclaim failed'); raise SystemExit(3)"]))
    last = _client(tmp_path, []).get("/api/restart").json()["last"]
    assert last["log_tail"] == ["ERROR: reclaim failed"]


def _stub_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "tray.bat").write_text("@echo off\r\necho restarted %1\r\nexit /b 0\r\n", encoding="ascii")
    return checkout


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe's executable search is Windows-only")
@pytest.mark.parametrize(("command", "state"), [
    (self_restart.TRAY_RESTART, "ok"),
    # The control: a bare name is what ``cmd`` cannot find once the working
    # directory is off the executable search path, so it must read ``failed``.
    (("cmd.exe", "/c", "tray.bat", "--restart"), "failed"),
])
def test_the_tray_recipe_starts_when_the_cwd_is_off_the_exe_search_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: tuple[str, ...], state: str,
) -> None:
    checkout = _stub_checkout(tmp_path)
    status = tmp_path / "status"
    spec = _spec(status, list(command))
    RestartStore(status).write_spec({
        "id": "r1", "target": "app", "command": list(command), "root": str(checkout),
        "timeout_s": 30, "delay_s": 0,
    })
    monkeypatch.setenv("NoDefaultCurrentDirectoryInExePath", "1")
    assert run_spec(spec) == state


def test_launch_root_keeps_the_launch_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "prefix", str(Path("E:/automation/my-app/.venv")))
    monkeypatch.setattr(sys, "base_prefix", str(Path("C:/Python311")))
    assert self_restart.launch_root() == Path(os.path.abspath("E:/automation/my-app"))


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill /T is the Windows tray restart's kill")
def test_the_detached_runner_survives_a_tree_kill_of_its_parent(tmp_path: Path) -> None:
    spec = _spec(tmp_path, [sys.executable, "-c", "import time; time.sleep(2)"])
    parent_code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from src.self_restart import spawn_detached\n"
        f"spawn_detached(Path({str(spec)!r}), Path({str(REPO_ROOT)!r}))\n"
        "print('spawned', flush=True)\n"
        "time.sleep(60)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code], cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
        text=True, creationflags=NO_WINDOW,
    )
    try:
        assert parent.stdout is not None
        assert parent.stdout.readline().strip() == "spawned"
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(parent.pid)], capture_output=True,
                       timeout=30, creationflags=NO_WINDOW, check=False)
        parent.wait(timeout=30)
        deadline = time.monotonic() + 30
        state = None
        while time.monotonic() < deadline:
            record = RestartStore(tmp_path).read() or {}
            state = record.get("state")
            if state != "running":
                break
            time.sleep(0.25)
        assert state == "ok"
    finally:
        if parent.poll() is None:
            parent.kill()
        if parent.stdout is not None:
            parent.stdout.close()
