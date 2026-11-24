"""Tests for the clean tree ratchet.

Three layers, mirroring `test_port_host_ratchet.py`:

1. **Units**: the porcelain parser, the before/after comparison and the config.
2. **Ratchet behaviour** on throwaway git repos with a tiny smoke script: every
   mode, a write into a tracked file, an untracked file, an ignored file, a
   file already dirty before the run, a server smoke, and "not confirmed"
   (a smoke that fails, dies or never gets ready; git that cannot list).
3. **Self-adoption**: this repo's own declaration, catalogue entry and gate wiring.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import clean_tree_ratchet as ct
from src.no_window import NO_WINDOW
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parents[2]

FINITE = "[clean_tree_ratchet]\nenabled = true\nsmoke = ['{python}', 'smoke.py']\nsettle_s = 0\n"
SERVER = ("[clean_tree_ratchet]\nenabled = true\nsmoke = ['{python}', 'server.py', '{port}', '{data_dir}']\n"
          "ready_path = '/healthz'\nsettle_s = 0\ntimeout_s = 20\n")
# Serves /healthz and writes whatever WRITE names (relative to the repo) on start.
SERVER_PY = """\
import http.server, pathlib, sys
port, data_dir = int(sys.argv[1]), pathlib.Path(sys.argv[2])
(data_dir / "state.db").write_text("ok")
target = pathlib.Path("WRITE")
if str(target) != "WRITE":
    target.write_text("boot")
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


# ------------------------------------------------- units

def test_porcelain_lists_each_path_and_a_rename_source() -> None:
    raw = b" M src/a.py\0?? new.txt\0R  b.py\0old_b.py\0D  gone.py\0"
    assert ct.parse_porcelain(raw) == {
        "src/a.py": " M", "new.txt": "??", "b.py": "R ", "old_b.py": "R <", "gone.py": "D "}


def test_written_paths_names_new_changed_and_reverted_entries() -> None:
    before = {"dirty.py": (" M", "h1"), "reverted.py": (" M", "h2"), "same.py": (" M", "h3")}
    after = {"dirty.py": (" M", "h9"), "same.py": (" M", "h3"), "new.log": ("??", "h4")}
    assert ct.written_paths(before, after) == {
        "dirty.py": "M -> M (content changed)", "new.log": "clean -> ??", "reverted.py": "M -> clean"}


def test_placeholders_are_filled() -> None:
    argv = ct.expand(("{python}", "-m", "app", "--port={port}", "{data_dir}"), 8123, "/tmp/d")
    assert argv == [sys.executable, "-m", "app", "--port=8123", "/tmp/d"]


def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert ct.parse_config("") is None
    assert ct.parse_config("[clean_tree_ratchet]\nenabled = false\n") is None


def test_enabled_table_defaults() -> None:
    cfg = ct.parse_config("[clean_tree_ratchet]\nenabled = true\nsmoke = ['x']\n")
    assert cfg == ct.Config(ct.DEFAULT_BASELINE, ("x",), None, ct.DEFAULT_TIMEOUT_S, ct.DEFAULT_SETTLE_S, None)


@pytest.mark.parametrize("body", [
    "enabled = true",                                     # no smoke to run
    "enabled = true\nsmoke = []",
    "enabled = true\nsmoke = 'python app.py'",
    "enabled = true\nsmoke = ['x']\nready_path = 'healthz'",
    "enabled = true\nsmoke = ['x']\nready_path = '/healthz'",  # a server smoke with no {port}
    "enabled = true\nsmoke = ['x']\ntimeout_s = 0",
    "enabled = true\nsmoke = ['x']\nsettle_s = true",
    "enabled = true\nsmoke = ['x']\nsmok = ['y']",
    "enabled = 'yes'",
])
def test_a_malformed_table_is_a_config_error(body: str) -> None:
    with pytest.raises(ct.ConfigError):
        ct.parse_config(f"[clean_tree_ratchet]\n{body}\n")


# ------------------------------------------------- ratchet on a git repo

def run_mode(repo: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return ct.run(repo, init=init, update=update, allow_additions=allow)


def smoke(repo: Path, body: str) -> None:
    write(repo, "smoke.py", "import pathlib\n" + body + "\n")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    write(tmp_path, ".fleet.toml", FINITE)
    write(tmp_path, ".gitignore", "data/\n")
    write(tmp_path, "src/app.py", "VALUE = 1\n")
    smoke(tmp_path, "pass")
    return tmp_path


def test_a_clean_smoke_passes_and_a_tracked_write_rises(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo, init=True) == ct.EXIT_PASS
    assert '"paths": []' in (repo / ct.DEFAULT_BASELINE).read_text(encoding="utf-8")
    assert run_mode(repo) == ct.EXIT_PASS
    smoke(repo, "pathlib.Path('src/app.py').write_text('VALUE = 2\\n')")
    capsys.readouterr()
    assert run_mode(repo) == ct.EXIT_RISE
    assert "src/app.py: [tree-write] A -> AM" in capsys.readouterr().out


def test_an_untracked_file_rises_and_an_ignored_one_does_not(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    smoke(repo, "pathlib.Path('data').mkdir(exist_ok=True); pathlib.Path('data/run.log').write_text('x')")
    assert run_mode(repo) == ct.EXIT_PASS
    smoke(repo, "pathlib.Path('src/cache.json').write_text('{}')")
    capsys.readouterr()
    assert run_mode(repo) == ct.EXIT_RISE
    assert "src/cache.json: [tree-write] clean -> ??" in capsys.readouterr().out


def test_work_in_progress_is_not_a_hit_unless_the_smoke_touches_it(repo: Path) -> None:
    run_mode(repo, init=True)
    (repo / "src/app.py").write_text("VALUE = 'editing'\n", encoding="utf-8")
    (repo / "notes.txt").write_text("draft\n", encoding="utf-8")
    assert run_mode(repo) == ct.EXIT_PASS
    smoke(repo, "pathlib.Path('src/app.py').write_text('VALUE = 3\\n')")
    assert run_mode(repo) == ct.EXIT_RISE


def test_a_baselined_path_passes_and_its_fix_hints_the_shrink(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    smoke(repo, "pathlib.Path('src/stamp.txt').write_text('boot')")
    assert run_mode(repo, init=True) == ct.EXIT_PASS
    assert '"src/stamp.txt"' in (repo / ct.DEFAULT_BASELINE).read_text(encoding="utf-8")
    (repo / "src/stamp.txt").unlink()
    assert run_mode(repo) == ct.EXIT_PASS
    smoke(repo, "pass")
    capsys.readouterr()
    assert run_mode(repo) == ct.EXIT_PASS
    assert "1 baselined path(s) were not written" in capsys.readouterr().out
    assert run_mode(repo, update=True) == ct.EXIT_PASS
    assert '"paths": []' in (repo / ct.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_update_refuses_additions_unless_allowed(repo: Path) -> None:
    run_mode(repo, init=True)
    smoke(repo, "pathlib.Path('src/app.py').write_text('VALUE = 4\\n')")
    assert run_mode(repo, update=True) == ct.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == ct.EXIT_PASS
    git(repo, "checkout", "--", "src/app.py")
    assert run_mode(repo) == ct.EXIT_PASS


def test_init_never_overwrites_and_a_missing_baseline_fails(repo: Path) -> None:
    assert run_mode(repo) == ct.EXIT_RISE
    run_mode(repo, init=True)
    assert run_mode(repo, init=True) == ct.EXIT_CONFIG


def test_not_enabled_passes_and_refuses_the_baseline_modes(repo: Path) -> None:
    write(repo, ".fleet.toml", "")
    assert run_mode(repo) == ct.EXIT_PASS
    assert run_mode(repo, init=True) == ct.EXIT_CONFIG


@pytest.mark.parametrize(("body", "says"), [
    ("raise SystemExit(4)", "the smoke exited 4"),
    ("import time; time.sleep(30)", "did not finish within 1s"),
])
def test_a_smoke_that_fails_is_not_confirmed(
    repo: Path, body: str, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, ".fleet.toml", FINITE.replace("settle_s = 0", "settle_s = 0\ntimeout_s = 1"))
    smoke(repo, body)
    assert run_mode(repo, init=True) == ct.EXIT_NOT_CONFIRMED
    assert says in capsys.readouterr().out
    assert not (repo / ct.DEFAULT_BASELINE).exists(), "--init writes nothing it could not confirm"


def test_a_server_smoke_boots_disposably_and_its_write_is_caught(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, ".fleet.toml", SERVER)
    write(repo, "server.py", SERVER_PY)
    assert run_mode(repo, init=True) == ct.EXIT_PASS
    assert "server ready at /healthz" in capsys.readouterr().out
    write(repo, "server.py", SERVER_PY.replace('"WRITE"', '"src/boot.txt"'))
    assert run_mode(repo) == ct.EXIT_RISE
    assert "src/boot.txt: [tree-write]" in capsys.readouterr().out


@pytest.mark.parametrize(("server", "says"), [
    ("import sys; sys.exit(7)", "the smoke exited 7 before"),
    ("import time; time.sleep(30)", "did not answer 200 within 1s"),
])
def test_a_server_that_dies_or_never_answers_is_not_confirmed(
    repo: Path, server: str, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, ".fleet.toml", SERVER.replace("timeout_s = 20", "timeout_s = 1"))
    write(repo, "server.py", server + "\n")
    assert run_mode(repo, init=True) == ct.EXIT_NOT_CONFIRMED
    assert says in capsys.readouterr().out


def test_a_rerun_of_a_red_check_stays_red_until_the_write_is_reverted(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    smoke(repo, "pathlib.Path('src/app.py').write_text('VALUE = 5\\n')")
    assert run_mode(repo) == ct.EXIT_RISE
    capsys.readouterr()
    assert run_mode(repo) == ct.EXIT_RISE, "the same bytes rewritten must not pass the second time"
    assert "left by an earlier smoke and not reverted" in capsys.readouterr().out
    git(repo, "checkout", "--", "src/app.py")
    smoke(repo, "pass")
    assert run_mode(repo) == ct.EXIT_PASS
    assert not list((repo / ".git").glob(ct.STATE_NAME)), "a pass clears the record"


@pytest.mark.parametrize(("var", "value"), [("GIT_DIR", "no-such-git-dir"), ("PATH", "empty")])
def test_git_that_cannot_list_the_tree_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str
) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv(var, str(repo / value))
    assert run_mode(repo) == ct.EXIT_NOT_CONFIRMED
    assert "NOT CONFIRMED: git" in capsys.readouterr().out


def test_the_script_runs_standalone(repo: Path) -> None:
    proc = subprocess.run([sys.executable, "-P", str(REPO_ROOT / "scripts" / "clean_tree_ratchet.py"), "--root",
                           str(repo), "--init"], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------- self-adoption

def test_the_scaffold_enables_the_stage_with_a_baseline() -> None:
    cfg = ct.load_config(REPO_ROOT)
    assert cfg is not None and (REPO_ROOT / cfg.baseline).is_file()


def test_gate_runs_the_stage_after_the_port_host_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (text.index(s) for s in (
        'Invoke-Stage "port host ratchet"', 'Invoke-Stage "clean tree ratchet"', 'Invoke-Stage "mypy'))
    assert before < stage < mypy


def test_the_script_is_catalogued() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["clean_tree_ratchet"]["src"] == "scripts/clean_tree_ratchet.py"


def test_every_rule_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "clean-tree-ratchet.md").read_text(encoding="utf-8")
    for rule in ct.RULES:
        assert f"`{rule}`" in doc and f"`{rule}`" in (ct.__doc__ or ""), rule
