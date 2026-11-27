"""The probe fake ratchet: each probe module is pinned per platform by a fake, and a probe change moves its test.

Every rule runs on a throwaway git repo with a `main` branch as the merge base, so the diff rule sees
the same committed, staged and untracked changes a lane's branch would.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import probe_fake_ratchet as pfr
from src.no_window import NO_WINDOW
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "probe_fake_ratchet.py"

FLEET = """\
[probe_fake_ratchet]
enabled  = true
probes   = ["src/listeners.py"]
base_ref = "main"
"""
PROBE = "def holders(rows):\n    return [r for r in rows if r['state'] == 'LISTEN']\n"
# The shape of the fake the rule asks for: each platform's recorded probe output through a seam.
FAKE_TEST = '''\
from src import listeners

WIN32_NETSTAT = [{"state": "LISTEN", "addr": "127.0.0.1"}]
DARWIN_LSOF = [{"state": "LISTEN", "addr": "::1"}]


def test_holders_win32():
    assert listeners.holders(WIN32_NETSTAT)


def test_holders_darwin():
    assert listeners.holders(DARWIN_LSOF)
'''


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo on a `feature` branch off `main`, whose probe module has both platform fakes."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))  # the machine's commit hooks are not under test
    write(root, ".fleet.toml", FLEET)
    write(root, "src/listeners.py", PROBE)
    write(root, "tests/test_listeners.py", FAKE_TEST)
    git(root, "commit", "-q", "-m", "init")
    git(root, "checkout", "-q", "-b", "feature")
    write(root, ".ratchets/probe-fake.json", pfr.render_baseline([]))
    return root


def run(root: Path, *args: str) -> int:
    return pfr.main(["--root", str(root), *args])


def hits(root: Path) -> dict[str, str]:
    cfg = pfr.parse_config(pfr.read_toml(root))
    assert cfg is not None
    return pfr.scan(root, cfg)[0]


def test_probe_change_without_a_fake_change_is_red_then_green_with_it(repo: Path,
                                                                       capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "src/listeners.py", PROBE + "\n\ndef other(rows):\n    return rows\n")
    assert run(repo) == pfr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[probe-changed-no-fake] src/listeners.py" in out
    assert "MAC_NIGHTLY: unverified" in out

    write(repo, "tests/test_listeners.py", FAKE_TEST + "\n\ndef test_other_darwin():\n"
          "    assert listeners.other(DARWIN_LSOF)\n")
    assert run(repo) == pfr.EXIT_PASS
    out = capsys.readouterr().out
    assert "MAC_NIGHTLY: unverified (this diff changes probe module(s) src/listeners.py" in out


def test_an_untouched_probe_passes_with_no_nightly_line(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "README.md", "text\n")
    assert run(repo) == pfr.EXIT_PASS
    assert "MAC_NIGHTLY" not in capsys.readouterr().out


def test_a_missing_platform_fake_is_one_hit_per_platform(repo: Path) -> None:
    write(repo, "tests/test_listeners.py", "from src import listeners\n\n\ndef test_holders_windows():\n"
          "    assert listeners.holders([{'state': 'LISTEN'}])\n")
    assert set(hits(repo)) == {"probe-fake-missing: src/listeners.py [darwin]"}

    write(repo, "tests/test_listeners.py", "def test_nothing():\n    pass\n")
    assert set(hits(repo)) == {"probe-fake-missing: src/listeners.py [win32]",
                               "probe-fake-missing: src/listeners.py [darwin]"}


def test_a_platform_named_only_in_a_skip_or_a_docstring_is_not_a_fake(repo: Path) -> None:
    write(repo, "tests/test_listeners.py", '''\
"""Pins the darwin and macOS listener shapes."""
import sys

import pytest

from src import listeners


@pytest.mark.skipif(sys.platform == "darwin", reason="not on mac")
def test_holders_win32():
    assert listeners.holders([{"state": "LISTEN"}])
''')
    assert set(hits(repo)) == {"probe-fake-missing: src/listeners.py [darwin]"}


def test_a_test_reaching_the_probe_by_path_or_dotted_string_counts(repo: Path) -> None:
    write(repo, "tests/test_listeners.py", '''\
def test_holders_win32_and_darwin(monkeypatch):
    monkeypatch.setattr("src.listeners.holders", lambda rows: rows)
    assert ["win32", "darwin"]
''')
    assert hits(repo) == {}


def test_exempt_markers(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "tests/test_listeners.py", "def test_nothing():\n    pass\n")
    write(repo, "src/listeners.py", "# probe-fake-exempt: reads a fixed file, same on every OS\n" + PROBE)
    assert run(repo) == pfr.EXIT_PASS
    out = capsys.readouterr().out
    assert "probe-fake-missing exempt: reads a fixed file" in out
    assert "probe-changed-no-fake exempt in this diff" in out

    write(repo, "src/listeners.py", "# probe-fake-exempt:\n" + PROBE)
    assert "bare-exempt: src/listeners.py" in hits(repo)


def test_a_new_untracked_probe_counts_as_changed(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(FLEET.replace('["src/listeners.py"]', '["src/*.py"]'), encoding="utf-8")
    write(repo, "src/ports.py", PROBE, track=False)
    assert "probe-changed-no-fake: src/ports.py" in hits(repo)


def test_modes_never_baseline_a_diff_hit(repo: Path) -> None:
    (repo / ".ratchets/probe-fake.json").unlink()
    write(repo, "tests/test_listeners.py", "def test_nothing():\n    pass\n")
    write(repo, "src/listeners.py", PROBE + "# changed\n")
    assert run(repo, "--init") == pfr.EXIT_PASS
    stored = json.loads((repo / ".ratchets/probe-fake.json").read_text(encoding="utf-8"))["hits"]
    assert stored == ["probe-fake-missing: src/listeners.py [darwin]", "probe-fake-missing: src/listeners.py [win32]"]
    assert run(repo, "--init") == pfr.EXIT_CONFIG
    assert run(repo) == pfr.EXIT_RISE  # the diff hit still fails the change

    write(repo, "tests/test_listeners.py", FAKE_TEST)
    assert run(repo, "--update-baseline") == pfr.EXIT_PASS
    assert json.loads((repo / ".ratchets/probe-fake.json").read_text(encoding="utf-8"))["hits"] == []

    write(repo, "tests/test_listeners.py", "def test_nothing():\n    pass\n")
    assert run(repo, "--update-baseline") == pfr.EXIT_RISE
    assert run(repo, "--update-baseline", "--allow-additions") == pfr.EXIT_PASS


def test_unknown_states_are_not_confirmed(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(FLEET.replace('"main"', '"no-such-ref"'), encoding="utf-8")
    assert run(repo) == pfr.EXIT_NOT_CONFIRMED

    (repo / ".fleet.toml").write_text(FLEET, encoding="utf-8")
    write(repo, "tests/test_broken.py", "def test_(:\n")
    assert run(repo) == pfr.EXIT_NOT_CONFIRMED


@pytest.mark.parametrize("table", [
    'enabled = true\nprobes = ["src/x.py"]\nbogus = 1\n',
    'enabled = true\nprobes = ["src/x.py"]\nplatforms = ["beos"]\n',
    'enabled = true\n',
    'enabled = "yes"\nprobes = ["src/x.py"]\n',
])
def test_bad_config_is_exit_2(repo: Path, table: str) -> None:
    (repo / ".fleet.toml").write_text("[probe_fake_ratchet]\n" + table, encoding="utf-8")
    assert run(repo) == pfr.EXIT_CONFIG


def test_not_enabled_passes(repo: Path) -> None:
    (repo / ".fleet.toml").write_text("[probe_fake_ratchet]\nenabled = false\n", encoding="utf-8")
    assert run(repo) == pfr.EXIT_PASS
    assert run(repo, "--init") == pfr.EXIT_CONFIG


def test_the_scaffold_baseline_matches_its_tree() -> None:
    cfg = pfr.parse_config(pfr.read_toml(REPO_ROOT))
    assert cfg is not None, "the scaffold dogfoods [probe_fake_ratchet]"
    tree_hits = pfr._baselinable(pfr.scan(REPO_ROOT, cfg, with_diff=False)[0])
    assert tree_hits == pfr.read_baseline(REPO_ROOT / cfg["baseline"])


def test_runs_as_a_script() -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                          creationflags=NO_WINDOW, timeout=60, check=False)
    assert proc.returncode == 0 and "--update-baseline" in proc.stdout
