"""The `host-identity` rule: a test reading the real account name or home folder.

On the developer's machine the real value is the expected one, so such a test passes there and fails
on every other host. The rule fails the direct read in a test module, passes the same test written
against the `synthetic_host` fixture, and never looks at app code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import conventions_ratchet as cr
from tests._git_repo import git, write

RULE = "host-identity"
CFG = cr.Config(cr.DEFAULT_BASELINE, (RULE,))
TEST_PATH = "tests/test_paths.py"


def hits(src: str, path: str = TEST_PATH) -> list[str]:
    return [f"{h.rule}:{h.line}" for h in cr.scan_source(src, path, cr.rules_for(path, CFG))]


def test_the_rule_is_known_opt_in_and_test_only() -> None:
    assert RULE in cr.RULES
    cfg = cr.parse_config(f'[conventions_ratchet]\nenabled = true\nrules = ["{RULE}"]\n')
    assert cfg is not None and cfg.rules == (RULE,)
    assert cr.rules_for(TEST_PATH, CFG) == {RULE}
    assert cr.rules_for("tests/conftest.py", CFG) == {RULE}
    assert cr.rules_for("src/paths.py", CFG) == frozenset()
    assert cr.rules_for("tests/page.html", CFG) == frozenset()
    assert cr.rules_for(TEST_PATH, cr.Config(cr.DEFAULT_BASELINE, ("no-window",))) == {"no-window"}


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("import getpass\nx = getpass.getuser()\n", id="getuser"),
        pytest.param("from getpass import getuser as who\nx = who()\n", id="getuser-alias"),
        pytest.param("import os\nx = os.getlogin()\n", id="getlogin"),
        pytest.param("import pwd, os\nx = pwd.getpwuid(os.getuid())\n", id="pwd"),
        pytest.param("from pathlib import Path\nx = Path.home()\n", id="path-home"),
        pytest.param("import pathlib\nx = pathlib.Path.home() / 'a'\n", id="pathlib-home"),
        pytest.param("import os\nx = os.path.expanduser('~/.config')\n", id="os-expanduser"),
        pytest.param("from os.path import expanduser\nx = expanduser('~')\n", id="from-expanduser"),
        pytest.param("from pathlib import Path\nx = Path('~/a').expanduser()\n", id="path-expanduser"),
        pytest.param("import os\nx = os.environ['USERNAME']\n", id="environ-username"),
        pytest.param("import os\nx = os.environ.get('HOME', '')\n", id="environ-get-home"),
        pytest.param("import os\nx = os.getenv('USERPROFILE')\n", id="getenv-userprofile"),
        pytest.param("from os import environ\nx = environ['USER']\n", id="from-environ"),
    ],
)
def test_a_direct_read_in_a_test_fails_by_rule_name(src: str) -> None:
    assert hits(src) == [f"{RULE}:2"]


def test_the_same_test_written_against_the_fixture_passes() -> None:
    bad = "from pathlib import Path\ndef test_cfg():\n    assert cfg_path() == Path.home() / '.cfg'\n"
    good = "def test_cfg(synthetic_host):\n    assert cfg_path() == synthetic_host.home / '.cfg'\n"
    assert hits(bad) == [f"{RULE}:3"]
    assert hits(good) == []


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("def test_x(monkeypatch):\n    monkeypatch.setenv('HOME', '/h')\n", id="setenv"),
        pytest.param("def test_x(monkeypatch):\n    monkeypatch.delenv('USERNAME')\n", id="delenv"),
        pytest.param("import os\nos.environ['HOME'] = '/h'\n", id="environ-write"),
        pytest.param("import os\ndel os.environ['HOME']\n", id="environ-del"),
        pytest.param("import os\nx = os.environ['PATH']\n", id="other-var"),
        pytest.param("import os\nx = os.path.expanduser(p)\n", id="expanduser-unknown-arg"),
        pytest.param("import os\nx = os.path.expanduser('/abs')\n", id="expanduser-no-tilde"),
        pytest.param("import sys\nx = sys.executable\n", id="interpreter-path"),
        pytest.param("x = env['HOME']\n", id="a-copied-dict"),
        pytest.param("x = 'Path.home()'\n", id="a-string"),
    ],
)
def test_writes_unknown_values_and_other_names_are_not_reads(src: str) -> None:
    assert hits(src) == []


def test_app_code_reads_the_real_host_on_purpose() -> None:
    assert hits("from pathlib import Path\nx = Path.home()\n", "src/paths.py") == []


def test_the_exempt_marker_needs_a_reason() -> None:
    src = "from pathlib import Path\n# host-identity-exempt{}\nx = Path.home()\n"
    assert hits(src.format(": compares against the real home on purpose")) == []
    assert hits(src.format(":")) == [f"{RULE}:3"]


def test_a_seeded_repo_fails_the_gate_on_a_new_direct_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(f'[conventions_ratchet]\nenabled = true\nrules = ["{RULE}"]\n',
                                          encoding="utf-8")
    write(tmp_path, TEST_PATH, "def test_cfg(synthetic_host):\n    assert synthetic_host.home\n")
    assert cr.run(tmp_path, init=True, update=False, allow_additions=False) == cr.EXIT_PASS
    write(tmp_path, TEST_PATH, "import getpass\ndef test_who():\n    assert getpass.getuser()\n")
    assert cr.run(tmp_path, init=False, update=False, allow_additions=False) == cr.EXIT_RISE
    assert f"{TEST_PATH}:3: [{RULE}] `getpass.getuser()` reads the real host's identity" in capsys.readouterr().out
